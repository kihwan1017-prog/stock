from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from stock_platform.operation.idempotency_repository import (
    PostgreSqlIdempotencyRepository,
)
from stock_platform.order.outbox_dispatcher import (
    OrderOutboxDispatcher,
)
from stock_platform.order.outbox_fencing import (
    OutboxAmbiguousError,
    OutboxFencingError,
    record_outbox_audit,
    stable_request_hash,
)
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_repository import (
    OrderOutboxRepository,
)


@dataclass(frozen=True, slots=True)
class OutboxRunSummary:
    claimed: int
    succeeded: int
    retried: int
    failed: int
    ambiguous: int = 0


class OrderOutboxWorker:
    RETRY_DELAYS_SECONDS = (
        5,
        15,
        30,
        60,
        300,
    )
    STALE_PROCESSING_AFTER = timedelta(minutes=5)

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        dispatcher: OrderOutboxDispatcher,
        worker_id: str,
        batch_size: int = 20,
        paper_only: bool = False,
        stale_processing_after: timedelta | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._paper_only = paper_only
        self._stale_after = (
            stale_processing_after
            if stale_processing_after is not None
            else self.STALE_PROCESSING_AFTER
        )

    def run_once(self) -> OutboxRunSummary:
        with self._session_factory() as session:
            repository = OrderOutboxRepository(session)
            repository.reclaim_stale_processing(
                stale_after=self._stale_after,
            )
            rows = repository.claim_batch(
                worker_id=self._worker_id,
                batch_size=self._batch_size,
                paper_only=self._paper_only,
            )
            claims = [
                (int(r.outbox_id), int(r.fencing_token))
                for r in rows
            ]
            session.commit()

        return self._run_claimed(claims)

    def dispatch_one(self, outbox_id: int) -> OutboxRunSummary:
        """정확히 지정 outbox 1건만 claim+dispatch (batch worker 아님)."""

        with self._session_factory() as session:
            repository = OrderOutboxRepository(session)
            row = repository.claim_one(
                outbox_id=int(outbox_id),
                worker_id=self._worker_id,
            )
            if row is None:
                session.commit()
                return OutboxRunSummary(
                    claimed=0,
                    succeeded=0,
                    retried=0,
                    failed=0,
                    ambiguous=0,
                )
            claims = [(int(row.outbox_id), int(row.fencing_token))]
            session.commit()

        return self._run_claimed(claims)

    def _run_claimed(
        self, claims: list[tuple[int, int]]
    ) -> OutboxRunSummary:
        claimed = len(claims)
        succeeded = 0
        retried = 0
        failed = 0
        ambiguous = 0

        for outbox_id, fencing_token in claims:
            with self._session_factory() as session:
                repository = OrderOutboxRepository(session)
                idempotency = PostgreSqlIdempotencyRepository(session)
                entity = repository.get(outbox_id)
                if entity is None:
                    continue

                mock_fill_order_id: int | None = None
                mock_fill_payload: dict[str, Any] | None = None
                try:
                    payload = dict(entity.payload_json or {})
                    # 레거시 payload에 order_id 누락 시 보강
                    payload.setdefault("order_id", int(entity.order_id))
                    # 주문에 이미 broker_order_id 있으면 재전송 금지
                    if self._order_already_has_broker_id(
                        session, entity.order_id
                    ):
                        record_outbox_audit(
                            session,
                            event_type="OUTBOX_DUPLICATE_DISPATCH_BLOCKED",
                            detail={
                                "outbox_id": outbox_id,
                                "order_id": entity.order_id,
                            },
                            actor=self._worker_id,
                        )
                        repository.mark_done(
                            entity=entity,
                            fencing_token=fencing_token,
                            worker_id=self._worker_id,
                        )
                        self._finalize_smoke_one_shot_if_needed(
                            session,
                            order_id=int(entity.order_id),
                            outbox_id=int(outbox_id),
                            outcome="DUPLICATE_BLOCKED",
                            worker_id=self._worker_id,
                        )
                        succeeded += 1
                        session.commit()
                        continue

                    request_hash = stable_request_hash(payload)
                    # Dispatch Intent 영속화 → Commit 후에만 Broker
                    repository.create_dispatch_intent(
                        entity=entity,
                        fencing_token=fencing_token,
                        worker_id=self._worker_id,
                        request_hash=request_hash,
                    )
                    session.commit()
                    entity = repository.get(outbox_id)
                    if entity is None:
                        continue

                    # LIVE safety: intent 후에도 재확인 (전송 직전)
                    self._assert_live_dispatch_allowed(
                        session,
                        payload,
                        outbox_id=int(outbox_id),
                        outbox_idempotency_key=getattr(
                            entity, "idempotency_key", None
                        ),
                    )

                    from stock_platform.order.live_dry_run import (
                        dry_run_block_dispatch_result,
                        should_block_live_dry_run,
                    )
                    from stock_platform.order.live_shadow import (
                        should_block_live_broker_call,
                        shadow_block_dispatch_result,
                    )

                    if should_block_live_dry_run(payload):
                        blocked = dry_run_block_dispatch_result(
                            event_type=entity.event_type,
                            payload=payload,
                        )
                        repository.mark_done(
                            entity=entity,
                            fencing_token=fencing_token,
                            worker_id=self._worker_id,
                        )
                        entity.last_error = blocked.get(
                            "reject_message"
                        )
                        self._finalize_smoke_one_shot_if_needed(
                            session,
                            order_id=int(entity.order_id),
                            outbox_id=int(outbox_id),
                            outcome="DRY_RUN_BLOCKED",
                            worker_id=self._worker_id,
                        )
                        succeeded += 1
                        session.commit()
                        continue

                    if should_block_live_broker_call(payload):
                        # Shadow — Broker API 0, Outbox DONE 처리
                        blocked = shadow_block_dispatch_result(
                            event_type=entity.event_type
                        )
                        repository.mark_done(
                            entity=entity,
                            fencing_token=fencing_token,
                            worker_id=self._worker_id,
                        )
                        entity.last_error = blocked.get(
                            "reject_message"
                        )
                        self._finalize_smoke_one_shot_if_needed(
                            session,
                            order_id=int(entity.order_id),
                            outbox_id=int(outbox_id),
                            outcome="SHADOW_BLOCKED",
                            worker_id=self._worker_id,
                        )
                        succeeded += 1
                        session.commit()
                        continue

                    record = idempotency.begin(
                        idempotency_key=entity.idempotency_key,
                        request_hash=request_hash,
                    )
                    if record.status_code == "COMPLETED":
                        result = record.result_json or {}
                        if result.get("accepted"):
                            self._apply_order_broker_result(
                                session=session,
                                order_id=entity.order_id,
                                result=result,
                                event_type=entity.event_type,
                            )
                        repository.mark_done(
                            entity=entity,
                            fencing_token=fencing_token,
                            worker_id=self._worker_id,
                        )
                        self._finalize_smoke_one_shot_if_needed(
                            session,
                            order_id=int(entity.order_id),
                            outbox_id=int(outbox_id),
                            outcome="IDEMPOTENT_REPLAY",
                            worker_id=self._worker_id,
                        )
                        succeeded += 1
                        session.commit()
                        if result.get("accepted"):
                            self._maybe_mock_auto_fill(
                                order_id=int(entity.order_id),
                                payload=payload,
                            )
                        continue

                    try:
                        result = self._dispatcher.dispatch(
                            event_type=entity.event_type,
                            payload=payload,
                            idempotency_key=entity.idempotency_key,
                            session=session,
                        )
                    except TimeoutError as exc:
                        raise OutboxAmbiguousError(
                            f"BROKER_TIMEOUT:{exc}"
                        ) from exc

                    if (
                        not result.get("accepted")
                        and (
                            result.get("status") == "AMBIGUOUS"
                            or str(
                                result.get("reject_code") or ""
                            ).startswith("AMBIGUOUS")
                        )
                    ):
                        self._mark_ambiguous_order(
                            session=session,
                            order_id=entity.order_id,
                            result=result,
                        )
                        repository.mark_ambiguous(
                            entity=entity,
                            reason=str(
                                result.get("reject_message")
                                or result.get("reject_code")
                                or "AMBIGUOUS"
                            ),
                            fencing_token=fencing_token,
                            worker_id=self._worker_id,
                        )
                        self._finalize_smoke_one_shot_if_needed(
                            session,
                            order_id=int(entity.order_id),
                            outbox_id=int(outbox_id),
                            outcome="AMBIGUOUS",
                            worker_id=self._worker_id,
                        )
                        ambiguous += 1
                        session.commit()
                        continue

                    if not result.get("accepted"):
                        raise RuntimeError(
                            result.get("reject_message")
                            or "Broker rejected order"
                        )

                    self._apply_order_broker_result(
                        session=session,
                        order_id=entity.order_id,
                        result=result,
                        event_type=entity.event_type,
                    )
                    # payload에도 broker_order_id 반영 (재전송 억제)
                    if result.get("broker_order_id"):
                        payload["broker_order_id"] = str(
                            result["broker_order_id"]
                        )
                        entity.payload_json = payload

                    idempotency.complete(
                        idempotency_key=entity.idempotency_key,
                        result_json=result,
                    )
                    repository.mark_done(
                        entity=entity,
                        fencing_token=fencing_token,
                        worker_id=self._worker_id,
                    )
                    self._finalize_smoke_one_shot_if_needed(
                        session,
                        order_id=int(entity.order_id),
                        outbox_id=int(outbox_id),
                        outcome="SUBMITTED",
                        worker_id=self._worker_id,
                    )
                    succeeded += 1
                    session.commit()
                    mock_fill_order_id = int(entity.order_id)
                    mock_fill_payload = dict(payload)
                except OutboxFencingError as exc:
                    mock_fill_order_id = None
                    mock_fill_payload = None
                    session.rollback()
                    record_outbox_audit(
                        session,
                        event_type="OUTBOX_FENCING_REJECTED",
                        detail={
                            "outbox_id": outbox_id,
                            "fencing_token": fencing_token,
                            "error": str(exc)[:200],
                        },
                        actor=self._worker_id,
                    )
                    session.commit()
                except OutboxAmbiguousError as exc:
                    mock_fill_order_id = None
                    mock_fill_payload = None
                    session.rollback()
                    with self._session_factory() as amb_session:
                        amb_repo = OrderOutboxRepository(amb_session)
                        amb_entity = amb_repo.get(outbox_id)
                        if amb_entity is not None:
                            amb_repo.mark_ambiguous(
                                entity=amb_entity,
                                reason=str(exc),
                                fencing_token=fencing_token,
                                worker_id=self._worker_id,
                            )
                            self._finalize_smoke_one_shot_if_needed(
                                amb_session,
                                order_id=int(amb_entity.order_id),
                                outbox_id=int(outbox_id),
                                outcome="AMBIGUOUS",
                                worker_id=self._worker_id,
                            )
                            amb_session.commit()
                            ambiguous += 1
                except Exception as exc:
                    mock_fill_order_id = None
                    mock_fill_payload = None
                    session.rollback()
                    with self._session_factory() as retry_session:
                        retry_repository = OrderOutboxRepository(
                            retry_session
                        )
                        retry_entity = retry_repository.get(outbox_id)
                        if retry_entity is None:
                            continue

                        # intent 이후 불명 오류 → Ambiguous (MOCK은 재시도)
                        msg = str(exc)
                        env = str(
                            (retry_entity.payload_json or {}).get(
                                "environment"
                            )
                            or "PAPER"
                        ).upper()
                        uncertain = env != "MOCK" and any(
                            x in msg.upper()
                            for x in (
                                "TIMEOUT",
                                "5XX",
                                "CONNECTION",
                                "AMBIGUOUS",
                                "UNAVAILABLE",
                            )
                        )
                        if (
                            retry_entity.dispatch_intent_at is not None
                            and uncertain
                        ):
                            retry_repository.mark_ambiguous(
                                entity=retry_entity,
                                reason=msg,
                                fencing_token=fencing_token,
                                worker_id=self._worker_id,
                            )
                            self._finalize_smoke_one_shot_if_needed(
                                retry_session,
                                order_id=int(retry_entity.order_id),
                                outbox_id=int(outbox_id),
                                outcome="AMBIGUOUS",
                                worker_id=self._worker_id,
                            )
                            ambiguous += 1
                            retry_session.commit()
                            continue

                        if (
                            retry_entity.retry_count + 1
                            >= retry_entity.max_retry_count
                        ):
                            retry_repository.mark_failed(
                                entity=retry_entity,
                                error_message=msg,
                                fencing_token=fencing_token,
                                worker_id=self._worker_id,
                            )
                            self._fail_open_order(
                                session=retry_session,
                                order_id=retry_entity.order_id,
                                error_message=msg,
                                event_type=retry_entity.event_type,
                            )
                            self._finalize_smoke_one_shot_if_needed(
                                retry_session,
                                order_id=int(retry_entity.order_id),
                                outbox_id=int(outbox_id),
                                outcome="FAILED",
                                worker_id=self._worker_id,
                            )
                            failed += 1
                        else:
                            retry_repository.mark_retry(
                                entity=retry_entity,
                                next_retry_at=(
                                    datetime.now(timezone.utc)
                                    + timedelta(
                                        seconds=self._retry_delay(
                                            retry_entity.retry_count
                                        )
                                    )
                                ),
                                error_message=msg,
                                fencing_token=fencing_token,
                                worker_id=self._worker_id,
                            )
                            if (
                                retry_entity.status_code
                                == OutboxStatus.AMBIGUOUS.value
                            ):
                                ambiguous += 1
                            else:
                                retried += 1
                        retry_session.commit()
                    continue
                else:
                    # try 성공 시에만 MOCK fill (예외 핸들러와 분리)
                    if mock_fill_order_id is not None and mock_fill_payload:
                        self._maybe_mock_auto_fill(
                            order_id=mock_fill_order_id,
                            payload=mock_fill_payload,
                        )

        return OutboxRunSummary(
            claimed=claimed,
            succeeded=succeeded,
            retried=retried,
            failed=failed,
            ambiguous=ambiguous,
        )

    @staticmethod
    def _maybe_mock_auto_fill(
        *,
        order_id: int,
        payload: dict[str, Any],
    ) -> None:
        """Outbox DONE 이후 Kiwoom MOCK 체결 (전용 세션)."""

        try:
            from stock_platform.common.settings import get_settings
            from stock_platform.broker.kiwoom.mock_outbox_fill import (
                fill_mock_accepted_order,
            )

            env = str(payload.get("environment") or "PAPER").upper()
            if env != "MOCK":
                return
            if not bool(
                getattr(get_settings(), "kiwoom_mock_outbox_auto_fill", False)
            ):
                return
            fill_mock_accepted_order(
                None,  # type: ignore[arg-type]
                int(order_id),
                actor="OUTBOX_KIWOOM_MOCK_AUTO_FILL",
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _order_already_has_broker_id(
        session: Session, order_id: int
    ) -> bool:
        from stock_platform.order.repository import TradingOrderRepository

        order = TradingOrderRepository(session).get(order_id)
        return bool(order and order.broker_order_id)

    @staticmethod
    def _finalize_smoke_one_shot_if_needed(
        session: Session,
        *,
        order_id: int,
        outbox_id: int,
        outcome: str,
        worker_id: str,
    ) -> None:
        """Smoke terminal dispatch 후 grant 소비 + LIVE OFF/DISARM."""

        try:
            from stock_platform.trading.upbit_live_smoke_service import (
                UpbitLiveSmokeService,
            )

            UpbitLiveSmokeService.finalize_after_smoke_dispatch(
                session,
                order_id=int(order_id),
                outbox_id=int(outbox_id),
                actor=str(worker_id),
                outcome=str(outcome),
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _assert_live_dispatch_allowed(
        session: Session,
        payload: dict[str, Any],
        *,
        outbox_id: int | None = None,
        outbox_idempotency_key: str | None = None,
    ) -> None:
        env = str(payload.get("environment") or "PAPER").upper()
        if env != "LIVE":
            return
        from stock_platform.broker.live_config_gate import (
            evaluate_live_flag_consistency,
        )
        from stock_platform.broker.live_transition_guard import (
            LiveTradingTransitionGuard,
        )
        from stock_platform.operation.live_health_gate import (
            assert_live_orders_allowed,
        )

        cfg = evaluate_live_flag_consistency()
        if cfg.code in {
            "LIVE_MOCK_CONFLICT",
            "LIVE_FLAG_MISMATCH_KIWOOM",
        }:
            raise PermissionError(cfg.code)
        assert_live_orders_allowed(session)

        # STEP 8-7 — UBA/broker 먼저 확정 후 Activation scope 검사
        uba_raw = payload.get("user_broker_account_id")
        if uba_raw is None:
            raise PermissionError("UBA_REQUIRED")
        from stock_platform.trading.account_models import UserBrokerAccount

        uba = session.get(UserBrokerAccount, int(uba_raw))
        if uba is None or not bool(uba.is_active):
            raise PermissionError("ACCOUNT_INACTIVE")
        expected_broker = str(payload.get("broker_code") or "").upper()
        uba_broker = str(uba.broker_code).upper()
        if expected_broker and uba_broker != expected_broker:
            raise PermissionError("UBA_BROKER_MISMATCH")
        dispatch_broker = expected_broker or uba_broker
        LiveTradingTransitionGuard(session).require_active(
            broker_code=dispatch_broker,
            user_broker_account_id=int(uba_raw),
        )
        owner_raw = payload.get("owner_user_id")
        if owner_raw not in (None, "") and int(uba.user_id) != int(owner_raw):
            raise PermissionError("UBA_OWNERSHIP_MISMATCH")

        live_on = bool(getattr(uba, "live_order_enabled", False))
        from stock_platform.trading.live_arm_service import LiveArmService

        # ARM 만료 시 LIVE OFF — 일반 경로 차단 (one-shot은 grant deadline 사용)
        expired = LiveArmService(session).expire_if_needed(int(uba_raw))
        uba = session.get(UserBrokerAccount, int(uba_raw))
        if uba is None:
            raise PermissionError("ACCOUNT_INACTIVE")
        # expire 후 플래그 재평가 (DISARM 반영)
        live_on = bool(getattr(uba, "live_order_enabled", False))
        armed = bool(getattr(uba, "live_armed", False))

        if live_on and armed and not expired:
            return

        # 설계 B — Smoke one-shot: LIVE/ARM OFF 여도 해당 outbox 1건만 허용
        if outbox_id is None:
            if not live_on:
                raise PermissionError("LIVE_ORDER_DISABLED")
            if expired or not armed:
                raise PermissionError(
                    "LIVE_ARM_EXPIRED" if expired else "LIVE_NOT_ARMED"
                )
            return

        from stock_platform.order.live_safety_audit import (
            emit_live_safety_audit,
        )
        from stock_platform.trading.smoke_one_shot_dispatch_grant import (
            SmokeOneShotGrantError,
            assert_smoke_one_shot_dispatch_allowed,
        )
        from stock_platform.trading.upbit_live_smoke_constants import (
            UPBIT_LIVE_SMOKE_ONE_SHOT_DISPATCH_ALLOWED,
        )

        try:
            grant = assert_smoke_one_shot_dispatch_allowed(
                session,
                payload,
                outbox_id=int(outbox_id),
                outbox_idempotency_key=outbox_idempotency_key,
            )
        except SmokeOneShotGrantError as exc:
            if not live_on:
                raise PermissionError(
                    f"LIVE_ORDER_DISABLED:{exc}"
                ) from exc
            raise PermissionError(
                f"{'LIVE_ARM_EXPIRED' if expired else 'LIVE_NOT_ARMED'}:{exc}"
            ) from exc

        try:
            emit_live_safety_audit(
                session,
                event_type=UPBIT_LIVE_SMOKE_ONE_SHOT_DISPATCH_ALLOWED,
                actor="OUTBOX_WORKER",
                run_id=str(grant.get("run_id") or ""),
                user_id=int(grant.get("owner_user_id") or 0) or None,
                account_id=int(uba_raw),
                strategy_id=None,
                order_id=int(payload.get("order_id") or 0) or None,
                detail={
                    "outbox_id": int(outbox_id),
                    "order_id": grant.get("order_id"),
                    "run_id": grant.get("run_id"),
                    "arm_deadline_at": grant.get("arm_deadline_at"),
                    "dispatch_expires_at": grant.get("dispatch_expires_at"),
                    "live_on": live_on,
                    "armed": armed,
                    "activation_broker": dispatch_broker,
                    "activation_uba": int(uba_raw),
                },
                commit=False,
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _apply_order_broker_result(
        *,
        session: Session,
        order_id: int,
        result: dict[str, Any],
        event_type: str,
    ) -> None:
        from stock_platform.order.models import OrderStatus
        from stock_platform.order.outbox_models import OutboxEventType
        from stock_platform.order.repository import TradingOrderRepository
        from stock_platform.order.state_machine import OrderStateMachine

        if event_type == OutboxEventType.SUBMIT_ORDER.value:
            repository = TradingOrderRepository(session)
            order = repository.get(order_id)
            if order is None:
                return
            broker_order_id = result.get("broker_order_id")
            if broker_order_id:
                order.broker_order_id = str(broker_order_id)
            status = OrderStatus(order.status_code)
            if status in {
                OrderStatus.ACCEPTED,
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
                OrderStatus.CANCEL_REQUESTED,
                OrderStatus.CANCELLED,
                OrderStatus.REPLACE_REQUESTED,
                OrderStatus.REPLACED,
                OrderStatus.REJECTED,
                OrderStatus.FAILED,
            }:
                return
            if status == OrderStatus.PENDING:
                order = repository.change_status(
                    entity=order,
                    new_status=OrderStatus.SENT,
                    actor="OUTBOX_WORKER",
                    reason_code="BROKER_REQUEST_SENT",
                    commit=False,
                )
                status = OrderStatus.SENT
            if status == OrderStatus.SUBMITTING:
                # claim_submitting 이후 ACCEPTED로 승격
                order = repository.change_status(
                    entity=order,
                    new_status=OrderStatus.ACCEPTED,
                    actor="OUTBOX_WORKER",
                    reason_code="BROKER_ACCEPTED",
                    commit=False,
                )
                status = OrderStatus.ACCEPTED
            if status == OrderStatus.SENT:
                repository.change_status(
                    entity=order,
                    new_status=OrderStatus.ACCEPTED,
                    actor="OUTBOX_WORKER",
                    reason_code="BROKER_ACCEPTED",
                    commit=False,
                )
                status = OrderStatus.ACCEPTED
            # STEP 10-1 — Upbit는 접수 직후 체결 동기화(시장가 즉시 체결 포함)
            if (
                status == OrderStatus.ACCEPTED
                and str(getattr(order, "broker_code", "") or "").upper()
                == "UPBIT"
                and order.broker_order_id
            ):
                try:
                    from stock_platform.broker.upbit.fill_sync_service import (
                        UpbitFillSyncService,
                    )

                    UpbitFillSyncService(session).sync_by_order_id(
                        int(order.order_id),
                        actor="OUTBOX_UPBIT_FILL_SYNC",
                    )
                except Exception:  # noqa: BLE001
                    # 체결 동기화 실패가 submit 성공을 롤백하지 않음
                    # Reconcile/Tracker가 후속 처리
                    pass

            # P0-5 — Paper Outbox ACCEPTED → Paper 원장 auto-fill (LIVE 혼입 금지)
            # Kiwoom MOCK fill은 Outbox DONE commit 이후에 별도 세션으로 수행
            if status == OrderStatus.ACCEPTED:
                try:
                    from stock_platform.common.settings import get_settings
                    from stock_platform.order.paper_outbox_fill_service import (
                        PaperOutboxFillService,
                    )

                    settings = get_settings()
                    meta_env = str(
                        (order.metadata_payload or {}).get("environment")
                        or "PAPER"
                    ).upper()
                    if meta_env == "MOCK":
                        pass  # commit 후 처리
                    elif bool(
                        getattr(settings, "paper_outbox_auto_fill", True)
                    ):
                        fill_result = PaperOutboxFillService(
                            session
                        ).fill_accepted_order(
                            int(order.order_id),
                            actor="OUTBOX_PAPER_AUTO_FILL",
                        )
                        if (
                            fill_result.skipped
                            and fill_result.reason_code
                            not in {
                                "ALREADY_TERMINAL",
                                "LIVE_ENVIRONMENT_BLOCKED",
                                "USER_BROKER_ACCOUNT_BLOCKED",
                                "NOT_ACCEPTED",
                                "IDEMPOTENT_REPLAY",
                            }
                        ):
                            meta = dict(order.metadata_payload or {})
                            meta["paper_auto_fill_last_error"] = (
                                fill_result.reason_code
                            )
                            order.metadata_payload = meta
                except Exception as exc:  # noqa: BLE001
                    meta = dict(getattr(order, "metadata_payload", None) or {})
                    meta["paper_auto_fill_last_error"] = type(exc).__name__
                    try:
                        order.metadata_payload = meta
                    except Exception:  # noqa: BLE001
                        pass
            return

        if event_type == OutboxEventType.CANCEL_ORDER.value:
            repository = TradingOrderRepository(session)
            order = repository.get(order_id)
            if order is None:
                return
            accepted = bool(result.get("accepted"))
            if accepted:
                status = OrderStatus(order.status_code)
                if OrderStateMachine.can_transition(
                    status, OrderStatus.CANCELLED
                ):
                    repository.change_status(
                        entity=order,
                        new_status=OrderStatus.CANCELLED,
                        actor="OUTBOX_WORKER",
                        reason_code="BROKER_CANCEL_ACCEPTED",
                        commit=False,
                    )
            # 미확정은 Tracking이 Broker 조회로 확정 — 여기서 COMPLETED 금지
            return

    @staticmethod
    def _mark_ambiguous_order(
        *,
        session: Session,
        order_id: int,
        result: dict[str, Any],
    ) -> None:
        from stock_platform.broker.upbit.ambiguous_constants import (
            SubmissionAttemptResult,
        )
        from stock_platform.broker.upbit.ambiguous_resolver import (
            UpbitAmbiguousOrderResolver,
        )
        from stock_platform.order.repository import TradingOrderRepository

        order = TradingOrderRepository(session).get(order_id)
        if order is None:
            return
        code = str(result.get("reject_code") or "")
        if "RATE_LIMIT" in code:
            attempt = SubmissionAttemptResult.AMBIGUOUS_429.value
        elif "5" in code:
            attempt = SubmissionAttemptResult.AMBIGUOUS_5XX.value
        else:
            attempt = SubmissionAttemptResult.AMBIGUOUS_TIMEOUT.value
        UpbitAmbiguousOrderResolver(session).mark_ambiguous(
            order,
            reason=str(result.get("reject_message") or code)[:200],
            attempt_result=attempt,
            actor="OUTBOX_WORKER",
        )

    @staticmethod
    def _fail_open_order(
        *,
        session: Session,
        order_id: int,
        error_message: str,
        event_type: str,
    ) -> None:
        from stock_platform.order.models import OrderStatus
        from stock_platform.order.outbox_models import OutboxEventType
        from stock_platform.order.repository import TradingOrderRepository
        from stock_platform.order.state_machine import OrderStateMachine

        if event_type != OutboxEventType.SUBMIT_ORDER.value:
            return
        repository = TradingOrderRepository(session)
        order = repository.get(order_id)
        if order is None:
            return
        status = OrderStatus(order.status_code)
        if not OrderStateMachine.can_transition(status, OrderStatus.FAILED):
            return
        order.reject_message = error_message[:500]
        repository.change_status(
            entity=order,
            new_status=OrderStatus.FAILED,
            actor="OUTBOX_WORKER",
            reason_code="OUTBOX_EXHAUSTED",
            message=error_message[:500],
            commit=False,
        )

    @classmethod
    def _retry_delay(cls, retry_count: int) -> int:
        index = min(retry_count, len(cls.RETRY_DELAYS_SECONDS) - 1)
        return cls.RETRY_DELAYS_SECONDS[index]
