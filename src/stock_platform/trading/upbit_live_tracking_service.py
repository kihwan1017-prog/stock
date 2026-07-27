"""STEP 8-9A — Upbit LIVE Smoke Broker 추적·취소·Timeout 확정."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.live_safety_audit import (
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.order.outbox_models import OutboxEventType
from stock_platform.order.outbox_repository import OrderOutboxRepository
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.live_arm_service import LiveArmService
from stock_platform.trading.live_validation_entities import (
    LiveValidationRunEntity,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    ALLOWED_TRANSITIONS,
    TRACKABLE_BROKER_STATUSES,
    TERMINAL_BROKER_STATUSES,
    BrokerOrderStatus,
    InternalStatus,
    UPBIT_LIVE_SMOKE_BROKER_ACCEPTED,
    UPBIT_LIVE_SMOKE_BROKER_FILLED,
    UPBIT_LIVE_SMOKE_BROKER_OPEN,
    UPBIT_LIVE_SMOKE_BROKER_ORDER_FOUND_BY_IDENTIFIER,
    UPBIT_LIVE_SMOKE_BROKER_PARTIAL,
    UPBIT_LIVE_SMOKE_BROKER_SUBMISSION_TIMEOUT,
    UPBIT_LIVE_SMOKE_CANCEL_CONFIRMED,
    UPBIT_LIVE_SMOKE_CANCEL_FAILED,
    UPBIT_LIVE_SMOKE_CANCEL_REQUESTED,
    UPBIT_LIVE_SMOKE_CANCEL_SENT,
    UPBIT_LIVE_SMOKE_FAILED_CLOSED,
    UPBIT_LIVE_SMOKE_MANUAL_REVIEW_REQUIRED,
    UPBIT_LIVE_SMOKE_OUTBOX_CREATED,
    UPBIT_LIVE_SMOKE_STATUS_UNKNOWN,
    mask_broker_uuid,
    smoke_broker_identifier,
)


class BrokerOrderProbe(Protocol):
    def get_order(self, broker_order_id: str, **kwargs: Any) -> Any: ...

    def cancel_order(self, broker_order_id: str, **kwargs: Any) -> Any: ...


def parse_track_delays(raw: str | None) -> list[int]:
    text = (raw or "1,2,5,10,20").strip()
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(max(1, int(part)))
        except ValueError:
            continue
    return out or [1, 2, 5, 10, 20]


def map_broker_raw_status(
    raw: str | None,
    *,
    executed_volume: object | None = None,
) -> str:
    s = str(raw or "").upper()
    if s in {"WAIT", "OPEN", "LIVE"}:
        return BrokerOrderStatus.OPEN.value
    if s in {"NEW", "ACCEPTED"}:
        return BrokerOrderStatus.ACCEPTED.value
    if s in {"DONE", "FILLED", "CLOSED"}:
        return BrokerOrderStatus.FILLED.value
    if s in {"CANCEL", "CANCELED", "CANCELLED"}:
        # 시장가 잔여 취소 + 체결량 → FILLED 계열 (후속 Post-fill 유지)
        try:
            executed = Decimal(str(executed_volume or "0"))
        except Exception:  # noqa: BLE001
            executed = Decimal("0")
        if executed > 0:
            return BrokerOrderStatus.FILLED.value
        return BrokerOrderStatus.CANCELED.value
    if s in {"PARTIAL", "PARTIALLY_FILLED"}:
        return BrokerOrderStatus.PARTIALLY_FILLED.value
    if s in {"REJECT", "REJECTED"}:
        return BrokerOrderStatus.REJECTED.value
    return BrokerOrderStatus.UNKNOWN.value


def _executed_volume_from_raw(raw_result: Any) -> object | None:
    if isinstance(raw_result, dict):
        return raw_result.get("executed_volume")
    direct = getattr(raw_result, "executed_volume", None)
    if direct is not None:
        return direct
    raw = getattr(raw_result, "raw", None) or getattr(
        raw_result, "raw_payload", None
    )
    if isinstance(raw, dict):
        return raw.get("executed_volume")
    return None


class UpbitLiveTrackingService:
    """Broker 상태 확정 전 COMPLETED 금지. 재주문 금지."""

    def __init__(
        self,
        session: Session,
        *,
        probe: BrokerOrderProbe | None = None,
    ) -> None:
        self._session = session
        self._probe = probe

    def attach_after_execution(
        self,
        run: LiveValidationRunEntity,
        *,
        order_id: int | None,
        actor: str,
        outbox_pending: bool = True,
    ) -> None:
        run.broker_identifier = smoke_broker_identifier(run.run_id)
        run.correlation_id = run.correlation_id or run.run_id
        settings = get_settings()
        watch = int(
            getattr(settings, "upbit_live_smoke_order_watch_seconds", 60)
        )
        now = datetime.now(timezone.utc)
        run.watch_deadline_at = now + timedelta(seconds=watch)
        run.next_track_at = now + timedelta(seconds=1)
        if order_id:
            run.order_id = int(order_id)
        self._set_internal(
            run,
            (
                InternalStatus.OUTBOX_PENDING.value
                if outbox_pending
                else InternalStatus.BROKER_SUBMISSION_PENDING.value
            ),
            actor=actor,
        )
        run.broker_order_status = BrokerOrderStatus.NOT_SUBMITTED.value
        self._audit(
            UPBIT_LIVE_SMOKE_OUTBOX_CREATED,
            run,
            actor=actor,
            reason_code="OUTBOX_PENDING",
        )
        self._session.flush()

    def mark_submission_timeout(
        self, run: LiveValidationRunEntity, *, actor: str
    ) -> dict[str, Any]:
        run.broker_order_status = BrokerOrderStatus.SUBMISSION_UNKNOWN.value
        self._set_internal(
            run, InternalStatus.BROKER_SUBMISSION_PENDING.value, actor=actor
        )
        self._audit(
            UPBIT_LIVE_SMOKE_BROKER_SUBMISSION_TIMEOUT,
            run,
            actor=actor,
            reason_code="SUBMISSION_TIMEOUT",
        )
        return self.resolve_by_identifier(run, actor=actor)

    def resolve_by_identifier(
        self, run: LiveValidationRunEntity, *, actor: str
    ) -> dict[str, Any]:
        probe = self._require_probe()
        identifier = run.broker_identifier or smoke_broker_identifier(
            run.run_id
        )
        run.last_broker_query_at = datetime.now(timezone.utc)
        try:
            result = probe.get_order(
                run.broker_order_uuid or "",
                identifier=identifier,
            )
        except Exception as exc:  # noqa: BLE001
            return self._mark_unknown(
                run, actor=actor, reason_code=type(exc).__name__
            )

        accepted = bool(getattr(result, "accepted", False))
        uuid = getattr(result, "broker_order_id", None)
        status_raw = getattr(
            getattr(result, "status", None), "value", None
        ) or getattr(result, "status", None)

        if accepted and uuid:
            run.broker_order_uuid = str(uuid)
            mapped = map_broker_raw_status(
                str(status_raw),
                executed_volume=_executed_volume_from_raw(result),
            )
            self._audit(
                UPBIT_LIVE_SMOKE_BROKER_ORDER_FOUND_BY_IDENTIFIER,
                run,
                actor=actor,
                reason_code="FOUND",
            )
            return self.apply_broker_status(
                run, mapped, actor=actor, raw_result=result
            )

        reject = str(getattr(result, "reject_code", "") or "")
        if "NOT_FOUND" in reject.upper() or "404" in reject:
            return self._fail_closed(
                run, actor=actor, reason_code="ORDER_NOT_FOUND"
            )
        return self._mark_unknown(
            run, actor=actor, reason_code="LOOKUP_INCONCLUSIVE"
        )

    def apply_broker_status(
        self,
        run: LiveValidationRunEntity,
        broker_status: str,
        *,
        actor: str,
        raw_result: Any = None,
    ) -> dict[str, Any]:
        mapped = str(broker_status).upper()
        run.broker_order_status = mapped
        run.last_broker_query_at = datetime.now(timezone.utc)
        run.track_attempt_count = int(run.track_attempt_count or 0) + 1

        if mapped in {
            BrokerOrderStatus.ACCEPTED.value,
            BrokerOrderStatus.OPEN.value,
        }:
            run.status_confirmed_at = datetime.now(timezone.utc)
            self._set_internal(
                run, InternalStatus.BROKER_TRACKING.value, actor=actor
            )
            evt = (
                UPBIT_LIVE_SMOKE_BROKER_OPEN
                if mapped == BrokerOrderStatus.OPEN.value
                else UPBIT_LIVE_SMOKE_BROKER_ACCEPTED
            )
            self._audit(evt, run, actor=actor, reason_code=mapped)
            self._telegram(
                run,
                title="Upbit LIVE Smoke Broker Accepted",
                message=f"run={run.run_id} broker={mapped}",
                event_type=evt,
            )
            self._schedule_next(run)
            if self._should_auto_cancel(run):
                return self.request_cancel(
                    run,
                    actor=actor,
                    reason="WATCH_EXPIRED",
                    skip_refresh=True,
                )
            return self._row_view(run)

        if mapped == BrokerOrderStatus.PARTIALLY_FILLED.value:
            self._capture_fills(run, raw_result)
            self._set_internal(
                run, InternalStatus.PARTIALLY_FILLED.value, actor=actor
            )
            self._audit(
                UPBIT_LIVE_SMOKE_BROKER_PARTIAL,
                run,
                actor=actor,
                reason_code=mapped,
            )
            self._telegram(
                run,
                title="Upbit LIVE Smoke Partial Fill",
                message=f"run={run.run_id} partial",
                event_type=UPBIT_LIVE_SMOKE_BROKER_PARTIAL,
            )
            self._schedule_next(run)
            if self._should_auto_cancel(run):
                return self.request_cancel(
                    run,
                    actor=actor,
                    reason="PARTIAL_WATCH_EXPIRED",
                    skip_refresh=True,
                )
            return self._row_view(run)

        if mapped == BrokerOrderStatus.FILLED.value:
            self._capture_fills(run, raw_result)
            run.status_confirmed_at = datetime.now(timezone.utc)
            self._set_internal(run, InternalStatus.FILLED.value, actor=actor)
            self._audit(
                UPBIT_LIVE_SMOKE_BROKER_FILLED,
                run,
                actor=actor,
                reason_code=mapped,
            )
            self._telegram(
                run,
                title="Upbit LIVE Smoke Filled",
                message=f"run={run.run_id} FILLED",
                event_type=UPBIT_LIVE_SMOKE_BROKER_FILLED,
            )
            self._sync_trading_order_fill(
                run, actor=actor, raw_result=raw_result
            )
            return self._start_post_fill(run, actor=actor)

        if mapped == BrokerOrderStatus.CANCELED.value:
            run.status_confirmed_at = datetime.now(timezone.utc)
            if run.filled_quantity and Decimal(str(run.filled_quantity)) > 0:
                run.broker_order_status = (
                    BrokerOrderStatus.PARTIALLY_FILLED_CANCELED.value
                )
                self._audit(
                    UPBIT_LIVE_SMOKE_CANCEL_CONFIRMED,
                    run,
                    actor=actor,
                    reason_code="PARTIAL_THEN_CANCELED",
                )
                return self._start_post_fill(run, actor=actor)
            self._set_internal(run, InternalStatus.CANCELED.value, actor=actor)
            self._audit(
                UPBIT_LIVE_SMOKE_CANCEL_CONFIRMED,
                run,
                actor=actor,
                reason_code="CANCELED",
            )
            self._telegram(
                run,
                title="Upbit LIVE Smoke Cancel Confirmed",
                message=f"run={run.run_id} CANCELED",
                event_type=UPBIT_LIVE_SMOKE_CANCEL_CONFIRMED,
            )
            run.completed_at = datetime.now(timezone.utc)
            self._set_internal(
                run, InternalStatus.COMPLETED.value, actor=actor
            )
            return self._row_view(run)

        if mapped == BrokerOrderStatus.REJECTED.value:
            self._set_internal(run, InternalStatus.REJECTED.value, actor=actor)
            return self._fail_closed(
                run, actor=actor, reason_code="BROKER_REJECTED"
            )

        return self._mark_unknown(run, actor=actor, reason_code=mapped)

    def refresh(
        self, run: LiveValidationRunEntity, *, actor: str
    ) -> dict[str, Any]:
        if run.broker_order_status in TERMINAL_BROKER_STATUSES:
            return self._row_view(run)
        probe = self._require_probe()
        run.last_broker_query_at = datetime.now(timezone.utc)
        try:
            if run.broker_order_uuid:
                result = probe.get_order(str(run.broker_order_uuid))
            else:
                return self.resolve_by_identifier(run, actor=actor)
        except Exception as exc:  # noqa: BLE001
            return self._mark_unknown(
                run, actor=actor, reason_code=type(exc).__name__
            )
        uuid = getattr(result, "broker_order_id", None)
        if uuid:
            run.broker_order_uuid = str(uuid)
        status_raw = getattr(
            getattr(result, "status", None), "value", None
        ) or getattr(result, "status", None)
        mapped = map_broker_raw_status(
            str(status_raw),
            executed_volume=_executed_volume_from_raw(result),
        )
        return self.apply_broker_status(
            run, mapped, actor=actor, raw_result=result
        )

    def request_cancel(
        self,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        reason: str = "MANUAL",
        skip_refresh: bool = False,
    ) -> dict[str, Any]:
        if not skip_refresh and (
            run.broker_order_uuid or run.broker_identifier
        ):
            view = self.refresh(run, actor=actor)
            if run.broker_order_status == BrokerOrderStatus.FILLED.value:
                return view
            if run.broker_order_status in TERMINAL_BROKER_STATUSES:
                return view

        if not run.broker_order_uuid and not run.order_id:
            return self._mark_unknown(
                run, actor=actor, reason_code="NO_BROKER_UUID"
            )

        self._set_internal(
            run, InternalStatus.CANCEL_REQUESTED.value, actor=actor
        )
        run.broker_order_status = BrokerOrderStatus.CANCEL_PENDING.value
        self._audit(
            UPBIT_LIVE_SMOKE_CANCEL_REQUESTED,
            run,
            actor=actor,
            reason_code=reason,
        )

        outbox_id = None
        if run.order_id:
            outbox_id = self._enqueue_cancel(run, actor=actor)

        self._set_internal(
            run, InternalStatus.CANCEL_TRACKING.value, actor=actor
        )
        self._audit(
            UPBIT_LIVE_SMOKE_CANCEL_SENT,
            run,
            actor=actor,
            reason_code=reason,
            extra={"outbox_enqueued": bool(outbox_id), "outbox_id": outbox_id},
        )
        self._schedule_next(run, force_delay=1)
        return {
            **self._row_view(run),
            "cancel_request_accepted": True,
            "cancel_completed": False,
            "status": BrokerOrderStatus.CANCEL_PENDING.value,
            "outbox_id": outbox_id,
        }

    def confirm_cancel_or_fail(
        self, run: LiveValidationRunEntity, *, actor: str
    ) -> dict[str, Any]:
        view = self.refresh(run, actor=actor)
        if run.broker_order_status in {
            BrokerOrderStatus.CANCELED.value,
            BrokerOrderStatus.FILLED.value,
            BrokerOrderStatus.PARTIALLY_FILLED_CANCELED.value,
        }:
            return view
        if run.broker_order_status == BrokerOrderStatus.CANCEL_PENDING.value:
            self._schedule_next(run)
            if self._tracking_exhausted(run):
                return self._cancel_failed_fail_closed(
                    run, actor=actor, reason_code="CANCEL_UNCONFIRMED"
                )
            return {
                **view,
                "cancel_request_accepted": True,
                "cancel_completed": False,
            }
        return self._cancel_failed_fail_closed(
            run, actor=actor, reason_code="CANCEL_FAILED"
        )

    def track_once(
        self, run: LiveValidationRunEntity, *, actor: str = "TRACKER"
    ) -> dict[str, Any]:
        if run.broker_order_status in TERMINAL_BROKER_STATUSES:
            return self._row_view(run)
        if run.broker_order_status == BrokerOrderStatus.CANCEL_PENDING.value:
            return self.confirm_cancel_or_fail(run, actor=actor)
        if run.broker_order_status == BrokerOrderStatus.SUBMISSION_UNKNOWN.value:
            return self.resolve_by_identifier(run, actor=actor)
        if not run.broker_order_uuid:
            return self.resolve_by_identifier(run, actor=actor)
        return self.refresh(run, actor=actor)

    def select_due_run_ids(self, *, limit: int = 20) -> list[int]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(LiveValidationRunEntity.live_validation_run_pk)
            .where(
                LiveValidationRunEntity.execute_live.is_(True),
                LiveValidationRunEntity.broker_order_status.in_(
                    list(TRACKABLE_BROKER_STATUSES)
                ),
                LiveValidationRunEntity.next_track_at.is_not(None),
                LiveValidationRunEntity.next_track_at <= now,
            )
            .order_by(LiveValidationRunEntity.next_track_at.asc())
            .limit(limit)
        )
        return [int(x) for x in self._session.scalars(stmt).all()]

    def blocks_new_order(self, uba_id: int) -> bool:
        stmt = select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.user_broker_account_id == int(uba_id),
            LiveValidationRunEntity.execute_live.is_(True),
            LiveValidationRunEntity.broker_order_status.in_(
                [
                    BrokerOrderStatus.UNKNOWN.value,
                    BrokerOrderStatus.SUBMISSION_UNKNOWN.value,
                    BrokerOrderStatus.CANCEL_PENDING.value,
                ]
            ),
        )
        if self._session.scalars(stmt).first() is not None:
            return True
        stmt2 = select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.user_broker_account_id == int(uba_id),
            LiveValidationRunEntity.manual_review_required.is_(True),
            LiveValidationRunEntity.completed_at.is_(None),
        )
        return self._session.scalars(stmt2).first() is not None

    def complete_manual_review(
        self,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        evidence: str,
        broker_status: str | None = None,
    ) -> dict[str, Any]:
        if broker_status:
            self.apply_broker_status(run, broker_status, actor=actor)
        run.manual_review_required = False
        detail = dict(run.detail or {})
        detail["manual_review"] = {
            "actor": actor,
            "evidence": str(evidence)[:500],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        run.detail = detail
        self._audit(
            UPBIT_LIVE_SMOKE_MANUAL_REVIEW_REQUIRED,
            run,
            actor=actor,
            reason_code="MANUAL_REVIEW_COMPLETED",
            extra={"evidence": str(evidence)[:200]},
        )
        self._session.flush()
        return self._row_view(run)

    def _enqueue_cancel(
        self, run: LiveValidationRunEntity, *, actor: str
    ) -> int | None:
        from stock_platform.order.repository import TradingOrderRepository

        order = TradingOrderRepository(self._session).get(int(run.order_id))
        if order is None and not run.broker_order_uuid:
            return None
        broker_id = str(
            (order.broker_order_id if order else None)
            or run.broker_order_uuid
            or ""
        )
        if not broker_id:
            return None
        qty = (
            order.remaining_quantity
            if order is not None and order.remaining_quantity is not None
            else (run.quantity or Decimal("0"))
        )
        order_pk = int(run.order_id or (order.order_id if order else 0))
        if order_pk <= 0:
            return None
        key = f"smoke-cancel:{run.run_id}:{broker_id}"
        row = OrderOutboxRepository(self._session).enqueue(
            order_id=order_pk,
            event_type=OutboxEventType.CANCEL_ORDER,
            idempotency_key=key,
            payload_json={
                "broker_order_id": broker_id,
                "exchange_code": "UPBIT",
                "symbol": run.market,
                "cancel_quantity": str(qty),
                "broker_code": "UPBIT",
                "environment": "LIVE",
                "user_broker_account_id": run.user_broker_account_id,
                "smoke_run_id": run.run_id,
                "client_order_id": f"cancel-{run.run_id}",
                "actor": actor,
            },
        )
        return int(row.outbox_id)

    def _start_post_fill(
        self, run: LiveValidationRunEntity, *, actor: str
    ) -> dict[str, Any]:
        self._set_internal(
            run, InternalStatus.POST_FILL_VERIFYING.value, actor=actor
        )
        detail = dict(run.detail or {})
        detail["post_fill_pending"] = True
        run.detail = detail
        self._session.flush()
        return self._row_view(run)

    def _sync_trading_order_fill(
        self,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        raw_result: Any,
    ) -> None:
        """Smoke run에 연결된 trading_order가 있으면 FillSync로 DB/Post-fill 반영."""

        order_id = getattr(run, "order_id", None)
        if order_id in (None, ""):
            return
        try:
            from stock_platform.broker.upbit.fill_sync_service import (
                UpbitFillSyncService,
            )

            remote = raw_result if isinstance(raw_result, dict) else None
            if remote is None and isinstance(
                getattr(raw_result, "raw", None), dict
            ):
                remote = getattr(raw_result, "raw")
            UpbitFillSyncService(self._session).sync_by_order_id(
                int(order_id),
                actor=actor,
                remote=remote,
            )
        except Exception:  # noqa: BLE001
            # Smoke 상태 확정을 롤백하지 않음
            return

    def _capture_fills(
        self, run: LiveValidationRunEntity, raw_result: Any
    ) -> None:
        if raw_result is None:
            return
        mapping = (
            ("filled_quantity", "filled_quantity"),
            ("executed_volume", "filled_quantity"),
            ("avg_price", "avg_fill_price"),
            ("avg_fill_price", "avg_fill_price"),
            ("paid_fee", "fee_amount"),
            ("fee", "fee_amount"),
        )
        for attr, field in mapping:
            val = getattr(raw_result, attr, None)
            if val is None and isinstance(raw_result, dict):
                val = raw_result.get(attr)
            if val is not None:
                setattr(run, field, Decimal(str(val)))
        if run.filled_quantity and run.avg_fill_price:
            run.filled_amount = Decimal(str(run.filled_quantity)) * Decimal(
                str(run.avg_fill_price)
            )

    def _should_auto_cancel(self, run: LiveValidationRunEntity) -> bool:
        settings = get_settings()
        if not bool(getattr(settings, "upbit_live_smoke_auto_cancel", True)):
            return False
        if run.watch_deadline_at is None:
            return False
        return datetime.now(timezone.utc) >= run.watch_deadline_at

    def _tracking_exhausted(self, run: LiveValidationRunEntity) -> bool:
        settings = get_settings()
        max_attempts = int(
            getattr(settings, "upbit_live_track_max_attempts", 8)
        )
        return int(run.track_attempt_count or 0) >= max_attempts

    def _schedule_next(
        self, run: LiveValidationRunEntity, *, force_delay: int | None = None
    ) -> None:
        settings = get_settings()
        delays = parse_track_delays(
            getattr(settings, "upbit_live_track_retry_delays_seconds", None)
        )
        idx = min(int(run.track_attempt_count or 0), len(delays) - 1)
        delay = force_delay if force_delay is not None else delays[idx]
        run.next_track_at = datetime.now(timezone.utc) + timedelta(
            seconds=delay
        )

    def _mark_unknown(
        self,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        reason_code: str,
    ) -> dict[str, Any]:
        run.broker_order_status = BrokerOrderStatus.UNKNOWN.value
        run.manual_review_required = True
        self._set_internal(
            run, InternalStatus.MANUAL_REVIEW_REQUIRED.value, actor=actor
        )
        run.failure_code = reason_code
        self._audit(
            UPBIT_LIVE_SMOKE_STATUS_UNKNOWN,
            run,
            actor=actor,
            reason_code=reason_code,
        )
        self._audit(
            UPBIT_LIVE_SMOKE_MANUAL_REVIEW_REQUIRED,
            run,
            actor=actor,
            reason_code=reason_code,
        )
        self._telegram(
            run,
            title="Upbit LIVE Smoke UNKNOWN — Manual Review",
            message=f"run={run.run_id} reason={reason_code}",
            event_type=UPBIT_LIVE_SMOKE_STATUS_UNKNOWN,
        )
        self._schedule_next(run)
        self._session.flush()
        return self._row_view(run)

    def _cancel_failed_fail_closed(
        self,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        reason_code: str,
    ) -> dict[str, Any]:
        self._audit(
            UPBIT_LIVE_SMOKE_CANCEL_FAILED,
            run,
            actor=actor,
            reason_code=reason_code,
        )
        self._telegram(
            run,
            title="Upbit LIVE Smoke Cancel Failed",
            message=f"run={run.run_id} {reason_code}",
            event_type=UPBIT_LIVE_SMOKE_CANCEL_FAILED,
        )
        return self._fail_closed(run, actor=actor, reason_code=reason_code)

    def _fail_closed(
        self,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        reason_code: str,
    ) -> dict[str, Any]:
        run.failure_code = reason_code
        run.manual_review_required = True
        try:
            KillSwitchService(self._session).activate(
                reason=f"UPBIT_LIVE_SMOKE:{reason_code}",
                actor=actor,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            LiveArmService(self._session).disarm(
                int(run.user_broker_account_id),
                actor=actor,
                reason=f"UPBIT_LIVE_SMOKE:{reason_code}",
                turn_live_off=True,
            )
        except Exception:  # noqa: BLE001
            pass
        self._set_internal(
            run, InternalStatus.FAILED_CLOSED.value, actor=actor
        )
        run.completed_at = datetime.now(timezone.utc)
        self._audit(
            UPBIT_LIVE_SMOKE_FAILED_CLOSED,
            run,
            actor=actor,
            reason_code=reason_code,
        )
        self._telegram(
            run,
            title="Upbit LIVE Smoke Fail Closed",
            message=f"run={run.run_id} Kill+LIVE OFF reason={reason_code}",
            event_type=UPBIT_LIVE_SMOKE_FAILED_CLOSED,
        )
        self._session.flush()
        return self._row_view(run)

    def _set_internal(
        self, run: LiveValidationRunEntity, new_status: str, *, actor: str
    ) -> None:
        current = run.internal_status or run.status_code
        _ = ALLOWED_TRANSITIONS.get(current, frozenset())
        run.internal_status = new_status
        run.status_code = new_status
        run.updated_at = datetime.now(timezone.utc)
        detail = dict(run.detail or {})
        hist = list(detail.get("transitions") or [])
        hist.append(
            {
                "from": current,
                "to": new_status,
                "actor": actor,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        detail["transitions"] = hist[-40:]
        run.detail = detail

    def _require_probe(self) -> BrokerOrderProbe:
        if self._probe is not None:
            return self._probe
        # 운영: UBA Vault 기반 Adapter. 테스트는 probe 주입.
        from stock_platform.broker.factory import BrokerAdapterFactory
        from stock_platform.broker.models import BrokerEnvironment

        return BrokerAdapterFactory.create(
            BrokerEnvironment.LIVE,
            "UPBIT",
            session=self._session,
            user_broker_account_id=None,
        )

    def _audit(
        self,
        event_type: str,
        run: LiveValidationRunEntity,
        *,
        actor: str,
        reason_code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        detail: dict[str, Any] = {
            "run_id": run.run_id,
            "uba_id": run.user_broker_account_id,
            "broker_identifier": run.broker_identifier,
            "broker_uuid_masked": mask_broker_uuid(run.broker_order_uuid),
            "internal_status": run.internal_status,
            "broker_status": run.broker_order_status,
            "retry_count": int(run.track_attempt_count or 0),
            "reason_code": reason_code,
            "correlation_id": run.correlation_id or run.run_id,
        }
        if extra:
            detail.update(extra)
        emit_live_safety_audit(
            self._session,
            event_type=event_type,
            actor=actor,
            run_id=run.run_id,
            user_id=run.user_id,
            account_id=run.user_broker_account_id,
            strategy_id=None,
            order_id=run.order_id,
            detail=detail,
            commit=False,
        )

    def _telegram(
        self,
        run: LiveValidationRunEntity,
        *,
        title: str,
        message: str,
        event_type: str,
    ) -> None:
        emit_live_order_telegram(
            event_type=event_type,
            title=title,
            message=message,
            detail={
                "run_id": run.run_id,
                "uba_id": run.user_broker_account_id,
                "broker_status": run.broker_order_status,
                "internal_status": run.internal_status,
                "broker_uuid_masked": mask_broker_uuid(run.broker_order_uuid),
            },
        )

    def _row_view(self, run: LiveValidationRunEntity) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "internal_status": run.internal_status or run.status_code,
            "broker_order_status": run.broker_order_status,
            "status": run.internal_status or run.status_code,
            "order_id": run.order_id,
            "broker_identifier": run.broker_identifier,
            "broker_uuid_masked": mask_broker_uuid(run.broker_order_uuid),
            "last_broker_query_at": (
                run.last_broker_query_at.isoformat()
                if run.last_broker_query_at
                else None
            ),
            "status_confirmed_at": (
                run.status_confirmed_at.isoformat()
                if run.status_confirmed_at
                else None
            ),
            "manual_review_required": bool(run.manual_review_required),
            "new_order_blocked": bool(run.manual_review_required)
            or run.broker_order_status
            in {
                BrokerOrderStatus.UNKNOWN.value,
                BrokerOrderStatus.SUBMISSION_UNKNOWN.value,
            },
            "filled_quantity": (
                str(run.filled_quantity)
                if run.filled_quantity is not None
                else None
            ),
            "avg_fill_price": (
                str(run.avg_fill_price)
                if run.avg_fill_price is not None
                else None
            ),
            "failure_code": run.failure_code,
            "cancel_completed": run.broker_order_status
            in {
                BrokerOrderStatus.CANCELED.value,
                BrokerOrderStatus.PARTIALLY_FILLED_CANCELED.value,
            },
        }
