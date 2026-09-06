from __future__ import annotations

import logging
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
from stock_platform.order.outbox_dispatch_safety import (
    OutboxDispatchSafetyError,
    assert_live_outbox_dispatch_safety,
    emit_outbox_dispatch_safety_rejection,
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

logger = logging.getLogger(__name__)


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
        live_only: bool = False,
        stale_processing_after: timedelta | None = None,
    ) -> None:
        if paper_only and live_only:
            raise ValueError("paper_only and live_only are mutually exclusive")
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._paper_only = paper_only
        self._live_only = live_only
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
                live_only=self._live_only,
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
        """Claimed 건 처리. LIVE BUY submit은 최대 2 parallel (V1)."""

        if not claims:
            return OutboxRunSummary(
                claimed=0, succeeded=0, retried=0, failed=0, ambiguous=0
            )

        workers = 1
        if self._live_only:
            try:
                from stock_platform.operation.upbit_full_market.buy_concurrency import (
                    resolve_order_submit_concurrency,
                )

                workers = resolve_order_submit_concurrency()
            except Exception:  # noqa: BLE001
                workers = 1

        if workers <= 1 or len(claims) <= 1:
            return self._run_claimed_serial(claims)

        from concurrent.futures import ThreadPoolExecutor, as_completed

        summaries: list[OutboxRunSummary] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(self._run_claimed_serial, [claim])
                for claim in claims
            ]
            for fut in as_completed(futures):
                try:
                    summaries.append(fut.result())
                except Exception:  # noqa: BLE001
                    logger.exception("outbox_parallel_claim_failed")
                    summaries.append(
                        OutboxRunSummary(
                            claimed=1,
                            succeeded=0,
                            retried=0,
                            failed=1,
                            ambiguous=0,
                        )
                    )

        return OutboxRunSummary(
            claimed=sum(s.claimed for s in summaries),
            succeeded=sum(s.succeeded for s in summaries),
            retried=sum(s.retried for s in summaries),
            failed=sum(s.failed for s in summaries),
            ambiguous=sum(s.ambiguous for s in summaries),
        )

    def _run_claimed_serial(
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

                    # LIVE safety: intent 전에 차단 (자동 RETRY/AMBIGUOUS 방지)
                    self._assert_live_dispatch_allowed(
                        session,
                        payload,
                        outbox_id=int(outbox_id),
                        outbox_idempotency_key=getattr(
                            entity, "idempotency_key", None
                        ),
                    )

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
                            outbox_id=int(outbox_id),
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
                except OutboxDispatchSafetyError as exc:
                    mock_fill_order_id = None
                    mock_fill_payload = None
                    session.rollback()
                    with self._session_factory() as fail_session:
                        fail_repository = OrderOutboxRepository(
                            fail_session
                        )
                        fail_entity = fail_repository.get(outbox_id)
                        if fail_entity is None:
                            continue
                        fail_payload = dict(
                            fail_entity.payload_json or {}
                        )
                        fail_payload.setdefault(
                            "order_id", int(fail_entity.order_id)
                        )
                        emit_outbox_dispatch_safety_rejection(
                            fail_session,
                            reason_code=exc.reason_code,
                            payload=fail_payload,
                            outbox_id=int(outbox_id),
                            worker_id=self._worker_id,
                            trading_order_id=int(fail_entity.order_id),
                        )
                        fail_repository.mark_failed(
                            entity=fail_entity,
                            error_message=str(exc.reason_code),
                            fencing_token=fencing_token,
                            worker_id=self._worker_id,
                        )
                        self._fail_open_order(
                            session=fail_session,
                            order_id=fail_entity.order_id,
                            error_message=str(exc.reason_code),
                            event_type=fail_entity.event_type,
                            reason_code=exc.reason_code,
                        )
                        self._finalize_smoke_one_shot_if_needed(
                            fail_session,
                            order_id=int(fail_entity.order_id),
                            outbox_id=int(outbox_id),
                            outcome="SAFETY_REJECTED",
                            worker_id=self._worker_id,
                        )
                        failed += 1
                        fail_session.commit()
                    continue
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
                            # outbox만 AMBIGUOUS로 두면 EXIT stuck가 영구화됨
                            self._mark_ambiguous_order(
                                session=amb_session,
                                order_id=int(amb_entity.order_id),
                                result={
                                    "reject_code": "AMBIGUOUS",
                                    "reject_message": str(exc)[:200],
                                },
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
                        msg_u = msg.upper()
                        uncertain = env != "MOCK" and any(
                            x in msg_u
                            for x in (
                                "TIMEOUT",
                                "5XX",
                                "CONNECTION",
                                "AMBIGUOUS",
                                "UNAVAILABLE",
                                "DEADLOCK",
                                "ROLLBACK",
                            )
                        )
                        if (
                            retry_entity.dispatch_intent_at is not None
                            and (
                                uncertain
                                or env in {"LIVE", "PAPER"}
                            )
                        ):
                            # intent 이후 예외는 재전송 금지 — outbox+order 동시 AMBIGUOUS
                            retry_repository.mark_ambiguous(
                                entity=retry_entity,
                                reason=msg,
                                fencing_token=fencing_token,
                                worker_id=self._worker_id,
                            )
                            self._mark_ambiguous_order(
                                session=retry_session,
                                order_id=int(retry_entity.order_id),
                                result={
                                    "reject_code": "AMBIGUOUS",
                                    "reject_message": msg[:200],
                                },
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
                                # mark_retry → RETRY_BLOCKED_AFTER_INTENT → AMBIGUOUS
                                self._mark_ambiguous_order(
                                    session=retry_session,
                                    order_id=int(retry_entity.order_id),
                                    result={
                                        "reject_code": "AMBIGUOUS",
                                        "reject_message": msg[:200],
                                    },
                                )
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
        assert_live_outbox_dispatch_safety(
            session,
            payload,
            outbox_id=outbox_id,
            outbox_idempotency_key=outbox_idempotency_key,
        )

    @staticmethod
    def _record_submission_attempt(
        *,
        session: Session,
        order: Any,
        result_type: str,
        external_uuid: str | None = None,
        ambiguous: bool = False,
        http_status: int | None = None,
        upbit_error_code: str | None = None,
    ) -> None:
        """order_submission_attempt + submission_attempt_count 갱신."""

        from datetime import datetime, timezone

        from stock_platform.order.entities import (
            OrderSubmissionAttemptEntity,
        )

        next_num = int(getattr(order, "submission_attempt_count", 0) or 0) + 1
        order.submission_attempt_count = next_num
        if hasattr(order, "last_submission_attempt_at"):
            order.last_submission_attempt_at = datetime.now(timezone.utc)
        row = OrderSubmissionAttemptEntity(
            order_id=int(order.order_id),
            client_order_identifier=getattr(
                order, "client_order_identifier", None
            ),
            attempt_number=next_num,
            completed_at=datetime.now(timezone.utc),
            result_type=str(result_type)[:40],
            http_status=http_status,
            upbit_error_code=upbit_error_code,
            external_order_uuid=external_uuid,
            ambiguous=bool(ambiguous),
            correlation_id=f"outbox-worker:{order.order_id}",
        )
        session.add(row)

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
            # LIVE 성공 제출 Attempt 기록 (ambiguous_resolver 외 경로 누락 보완)
            try:
                OrderOutboxWorker._record_submission_attempt(
                    session=session,
                    order=order,
                    result_type="ACCEPTED",
                    external_uuid=(
                        str(broker_order_id) if broker_order_id else None
                    ),
                    ambiguous=False,
                    http_status=None,
                )
            except Exception:  # noqa: BLE001
                pass
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
                try:
                    from stock_platform.operation.upbit_entry_execution_trace.order_hooks import (
                        trace_broker_submit,
                    )

                    trace_broker_submit(session, order)
                except Exception:  # noqa: BLE001
                    pass
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
            try:
                from stock_platform.operation.upbit_entry_execution_trace.order_hooks import (
                    trace_broker_accept,
                    trace_buy_fill,
                )

                refreshed = repository.get(order_id)
                if refreshed is not None:
                    trace_broker_accept(session, refreshed)
                    filled_qty = float(refreshed.filled_quantity or 0)
                    order_qty = float(refreshed.order_quantity or 0)
                    if filled_qty > 0:
                        trace_buy_fill(
                            session,
                            refreshed,
                            partial=(
                                order_qty > 0 and filled_qty < order_qty
                            ),
                        )
            except Exception:  # noqa: BLE001
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
        resolver = UpbitAmbiguousOrderResolver(session)
        # 결정적 identifier 없으면 원격 조회 자체가 불가
        try:
            if str(order.broker_code or "").upper() == "UPBIT":
                resolver.ensure_identifier(order)
        except Exception:  # noqa: BLE001
            pass
        code = str(result.get("reject_code") or "")
        if "RATE_LIMIT" in code:
            attempt = SubmissionAttemptResult.AMBIGUOUS_429.value
        elif "5" in code:
            attempt = SubmissionAttemptResult.AMBIGUOUS_5XX.value
        else:
            attempt = SubmissionAttemptResult.AMBIGUOUS_TIMEOUT.value
        resolver.mark_ambiguous(
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
        reason_code: str = "OUTBOX_EXHAUSTED",
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
            reason_code=str(reason_code or "OUTBOX_EXHAUSTED")[:80],
            message=error_message[:500],
            commit=False,
        )

    @classmethod
    def _retry_delay(cls, retry_count: int) -> int:
        index = min(retry_count, len(cls.RETRY_DELAYS_SECONDS) - 1)
        return cls.RETRY_DELAYS_SECONDS[index]
