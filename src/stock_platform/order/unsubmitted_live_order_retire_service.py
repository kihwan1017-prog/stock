"""미전송 LIVE/PAPER 주문 내부 폐기 — 브로커 API 0회.

PAPER: broker_code=PAPER + environment=PAPER + PENDING Outbox만.
LIVE: UPBIT/KIWOOM + environment=LIVE (기존 게이트 유지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import (
    OrderSubmissionAttemptEntity,
    TradingOrderEntity,
)
from stock_platform.order.models import (
    TERMINAL_ORDER_STATUSES,
    OrderStatus,
)
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import (
    OutboxEventType,
    OutboxStatus,
)
from stock_platform.order.repository import TradingOrderRepository

# Audit — 브로커 실전송 흔적으로 취급
_BROKER_SUBMIT_AUDIT_TYPES = frozenset(
    {
        "BROKER_ORDER_SUBMITTED",
        "UPBIT_ORDER_CREATED",
        "OUTBOX_DISPATCHED",
        "UPBIT_LIVE_SMOKE_OUTBOX_DISPATCHED",
    }
)

_PENDING_OUTBOX = frozenset(
    {
        OutboxStatus.PENDING.value,
        OutboxStatus.RETRY.value,
    }
)

REASON_CODE = "UNSUBMITTED_LIVE_RETIRED"
AUDIT_EVENT = "UNSUBMITTED_LIVE_ORDER_RETIRED"
OUTBOX_ERROR = "UNSUBMITTED_LIVE_ORDER_RETIRED"


class UnsubmittedLiveOrderRetireError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        blockers: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = list(blockers or [code])


@dataclass
class RetirePreview:
    retirable: bool
    blockers: list[str] = field(default_factory=list)
    order_id: int | None = None
    outbox_id: int | None = None
    user_broker_account_id: int | None = None
    broker_order_id: str | None = None
    submission_attempt_count: int = 0
    order_status: str | None = None
    outbox_status: str | None = None
    environment: str | None = None
    broker_code: str | None = None
    symbol: str | None = None
    side: str | None = None
    estimated_amount: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "retirable": self.retirable,
            "blockers": list(self.blockers),
            "order_id": self.order_id,
            "outbox_id": self.outbox_id,
            "user_broker_account_id": self.user_broker_account_id,
            "broker_order_id": self.broker_order_id,
            "submission_attempt_count": int(
                self.submission_attempt_count or 0
            ),
            "order_status": self.order_status,
            "outbox_status": self.outbox_status,
            "environment": self.environment,
            "broker_code": self.broker_code,
            "symbol": self.symbol,
            "side": self.side,
            "estimated_amount": self.estimated_amount,
        }


class UnsubmittedLiveOrderRetireService:
    """브로커 미전송 LIVE PENDING + SUBMIT Outbox만 내부 종결."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)

    def preview(self, order_id: int) -> RetirePreview:
        order, outbox, blockers = self._evaluate(int(order_id))
        preview = self._build_preview(order, outbox, blockers)
        return preview

    def retire(
        self,
        order_id: int,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        reason_clean = (reason or "").strip()
        if not reason_clean:
            raise UnsubmittedLiveOrderRetireError(
                "reason_required",
                "reason is required",
            )
        if len(reason_clean) > 2000:
            raise UnsubmittedLiveOrderRetireError(
                "reason_too_long",
                "reason must be <= 2000 characters",
            )

        order, outbox, blockers = self._evaluate(int(order_id))
        if blockers:
            # 이미 동일 사유로 폐기된 terminal → idempotent + Run 동기화
            if self._is_already_retired(order, outbox):
                synced = self._sync_linked_validation_runs(
                    order_id=int(order.order_id),
                    actor=actor,
                    reason=reason_clean,
                )
                return {
                    "ok": True,
                    "idempotent": True,
                    "order_id": int(order.order_id),
                    "outbox_id": int(outbox.outbox_id),
                    "order_status": order.status_code,
                    "outbox_status": outbox.status_code,
                    "synced_run_ids": synced,
                    "broker_api_calls": 0,
                }
            raise UnsubmittedLiveOrderRetireError(
                blockers[0],
                f"retire blocked: {','.join(blockers)}",
                blockers=blockers,
            )

        assert order is not None and outbox is not None
        prev_order = order.status_code
        prev_outbox = outbox.status_code
        uba_id = (
            int(order.user_broker_account_id)
            if order.user_broker_account_id is not None
            else None
        )

        # 어댑터/dispatcher 절대 미사용 — DB 상태만 전이
        self._orders.change_status(
            entity=order,
            new_status=OrderStatus.CANCELLED,
            actor=actor,
            reason_code=REASON_CODE,
            message=reason_clean[:500],
            detail_payload={
                "retire": True,
                "outbox_id": int(outbox.outbox_id),
                "broker_order_id": None,
                "submission_attempt_count": int(
                    order.submission_attempt_count or 0
                ),
            },
            commit=False,
        )
        outbox.status_code = OutboxStatus.FAILED.value
        outbox.last_error = f"{OUTBOX_ERROR}:{reason_clean[:400]}"
        outbox.next_retry_at = None
        outbox.locked_at = None
        outbox.locked_by = None
        outbox.lease_expires_at = None
        from datetime import datetime, timezone

        outbox.processed_at = datetime.now(timezone.utc)
        self._session.flush()

        synced = self._sync_linked_validation_runs(
            order_id=int(order.order_id),
            actor=actor,
            reason=reason_clean,
        )

        from stock_platform.order.live_safety_audit import (
            emit_live_safety_audit,
        )

        emit_live_safety_audit(
            self._session,
            event_type=AUDIT_EVENT,
            actor=actor,
            run_id=(synced[0] if synced else None),
            user_id=None,
            account_id=uba_id,
            strategy_id=None,
            symbol=str(order.symbol),
            order_id=int(order.order_id),
            client_order_id=str(order.client_order_id),
            detail={
                "order_id": int(order.order_id),
                "outbox_id": int(outbox.outbox_id),
                "user_broker_account_id": uba_id,
                "reason": reason_clean[:2000],
                "previous_order_status": prev_order,
                "previous_outbox_status": prev_outbox,
                "broker_order_id": None,
                "submission_attempt_count": 0,
                "broker_api_calls": 0,
                "synced_run_ids": synced,
                "validation_run_status": "CANCELED",
            },
            commit=False,
        )
        self._session.flush()

        return {
            "ok": True,
            "idempotent": False,
            "order_id": int(order.order_id),
            "outbox_id": int(outbox.outbox_id),
            "user_broker_account_id": uba_id,
            "order_status": OrderStatus.CANCELLED.value,
            "outbox_status": OutboxStatus.FAILED.value,
            "previous_order_status": prev_order,
            "previous_outbox_status": prev_outbox,
            "broker_order_id": None,
            "submission_attempt_count": 0,
            "broker_api_calls": 0,
            "synced_run_ids": synced,
        }

    @staticmethod
    def _is_already_retired(
        order: TradingOrderEntity | None,
        outbox: OrderOutbox | None,
    ) -> bool:
        if order is None or outbox is None:
            return False
        return (
            order.status_code == OrderStatus.CANCELLED.value
            and outbox.status_code == OutboxStatus.FAILED.value
            and str(outbox.last_error or "").startswith(OUTBOX_ERROR)
        )

    def _sync_linked_validation_runs(
        self,
        *,
        order_id: int,
        actor: str,
        reason: str,
    ) -> list[str]:
        """연결된 LiveValidationRun을 CANCELED(미전송 폐기)로 동기화.

        브로커 API / adapter 호출 없음.
        """

        from datetime import datetime, timezone

        from stock_platform.trading.live_validation_entities import (
            LiveValidationRunEntity,
        )
        from stock_platform.trading.upbit_live_smoke_constants import (
            BrokerOrderStatus,
            InternalStatus,
            TERMINAL_INTERNAL_STATUSES,
        )
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeService,
        )

        rows = list(
            self._session.scalars(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.order_id == int(order_id)
                )
            )
        )
        if not rows:
            return []

        smoke = UpbitLiveSmokeService(self._session)
        synced: list[str] = []
        now = datetime.now(timezone.utc)
        for run in rows:
            current = str(run.internal_status or run.status_code or "")
            if current in TERMINAL_INTERNAL_STATUSES:
                # 이미 terminal — broker_status/order_status만 보강
                if not run.broker_order_status:
                    run.broker_order_status = (
                        BrokerOrderStatus.NOT_SUBMITTED.value
                    )
                if run.order_status != OrderStatus.CANCELLED.value:
                    run.order_status = OrderStatus.CANCELLED.value
                if run.completed_at is None and current == (
                    InternalStatus.CANCELED.value
                ):
                    run.completed_at = now
                run.next_track_at = None
                continue

            # OUTBOX_PENDING / QUEUED 등 → CANCELED
            smoke._transition(
                run,
                InternalStatus.CANCELED.value,
                actor=actor,
            )
            run.broker_order_status = BrokerOrderStatus.NOT_SUBMITTED.value
            run.order_status = OrderStatus.CANCELLED.value
            run.completed_at = now
            run.next_track_at = None
            run.failure_code = REASON_CODE
            run.failure_summary = (
                f"unsubmitted order retired (no broker submit): {reason[:200]}"
            )
            detail = dict(run.detail or {})
            detail["unsubmitted_retire"] = {
                "order_id": int(order_id),
                "actor": actor,
                "reason": reason[:500],
                "at": now.isoformat(),
                "broker_api_calls": 0,
            }
            run.detail = detail
            synced.append(str(run.run_id))

        self._session.flush()
        return synced

    def _evaluate(
        self, order_id: int
    ) -> tuple[
        TradingOrderEntity | None,
        OrderOutbox | None,
        list[str],
    ]:
        blockers: list[str] = []
        order = self._orders.get(order_id)
        if order is None:
            return None, None, ["order_not_found"]

        outbox = self._find_submit_outbox(int(order.order_id))
        env = self._resolve_environment(order, outbox)
        broker = str(order.broker_code or "").upper()

        try:
            status = OrderStatus(str(order.status_code))
        except ValueError:
            status = None
            blockers.append("invalid_order_status")

        if status in TERMINAL_ORDER_STATUSES:
            blockers.append("order_already_terminal")

        if status is not None and status != OrderStatus.PENDING:
            if "order_already_terminal" not in blockers:
                blockers.append("order_not_pending")

        # PAPER 미전송(실 adapter 없음)도 동일 내부 폐기 허용
        if env == "PAPER":
            if broker != "PAPER":
                blockers.append("paper_broker_mismatch")
        elif env == "LIVE":
            if broker not in {"UPBIT", "KIWOOM"}:
                blockers.append("broker_not_live")
        else:
            blockers.append("environment_not_supported")

        if order.broker_order_id not in (None, ""):
            blockers.append("broker_order_id_present")

        attempt = int(order.submission_attempt_count or 0)
        if attempt != 0:
            blockers.append("submission_attempt_not_zero")

        has_attempt = (
            self._session.scalar(
                select(OrderSubmissionAttemptEntity.attempt_id)
                .where(
                    OrderSubmissionAttemptEntity.order_id
                    == int(order.order_id)
                )
                .limit(1)
            )
            is not None
        )
        if has_attempt:
            blockers.append("submission_attempt_row_exists")

        if outbox is None:
            blockers.append("submit_outbox_missing")
        else:
            if outbox.status_code not in _PENDING_OUTBOX:
                blockers.append("outbox_not_pending")
            if outbox.dispatch_intent_at is not None:
                blockers.append("dispatch_intent_present")
            if outbox.locked_at is not None or outbox.locked_by:
                blockers.append("outbox_claimed")
            if outbox.processed_at is not None:
                blockers.append("outbox_processed")
            payload = dict(outbox.payload_json or {})
            if str(payload.get("broker_order_id") or "").strip():
                blockers.append("outbox_payload_broker_id")

        if self._has_broker_submit_audit(int(order.order_id)):
            blockers.append("broker_submit_audit_present")

        # ambiguous 신호 → 수동 검토
        if status == OrderStatus.AMBIGUOUS_SUBMISSION:
            blockers.append("ambiguous_manual_review")
        if outbox is not None and outbox.status_code in {
            OutboxStatus.AMBIGUOUS.value,
            OutboxStatus.MANUAL_REVIEW.value,
        }:
            blockers.append("outbox_ambiguous_or_review")

        # 중복 제거 순서 유지
        seen: set[str] = set()
        uniq: list[str] = []
        for b in blockers:
            if b not in seen:
                seen.add(b)
                uniq.append(b)
        return order, outbox, uniq

    def _build_preview(
        self,
        order: TradingOrderEntity | None,
        outbox: OrderOutbox | None,
        blockers: list[str],
    ) -> RetirePreview:
        if order is None:
            return RetirePreview(
                retirable=False,
                blockers=blockers or ["order_not_found"],
            )
        qty = order.order_quantity
        price = order.order_price
        estimated = None
        if qty is not None and price is not None:
            estimated = str(qty * price)
        return RetirePreview(
            retirable=len(blockers) == 0,
            blockers=blockers,
            order_id=int(order.order_id),
            outbox_id=(
                int(outbox.outbox_id) if outbox is not None else None
            ),
            user_broker_account_id=(
                int(order.user_broker_account_id)
                if order.user_broker_account_id is not None
                else None
            ),
            broker_order_id=(
                str(order.broker_order_id)
                if order.broker_order_id
                else None
            ),
            submission_attempt_count=int(
                order.submission_attempt_count or 0
            ),
            order_status=str(order.status_code),
            outbox_status=(
                str(outbox.status_code) if outbox is not None else None
            ),
            environment=self._resolve_environment(order, outbox),
            broker_code=str(order.broker_code),
            symbol=str(order.symbol),
            side=str(order.side_code),
            estimated_amount=estimated,
        )

    def _find_submit_outbox(self, order_id: int) -> OrderOutbox | None:
        rows = list(
            self._session.scalars(
                select(OrderOutbox)
                .where(
                    OrderOutbox.order_id == int(order_id),
                    OrderOutbox.event_type
                    == OutboxEventType.SUBMIT_ORDER.value,
                )
                .order_by(OrderOutbox.outbox_id.desc())
            )
        )
        if not rows:
            return None
        # PENDING 계열 우선, 없으면 최신 1건(평가용)
        for row in rows:
            if row.status_code in _PENDING_OUTBOX:
                return row
        return rows[0]

    @staticmethod
    def _resolve_environment(
        order: TradingOrderEntity,
        outbox: OrderOutbox | None,
    ) -> str:
        meta = dict(order.metadata_payload or {})
        env = str(meta.get("environment") or "").upper()
        if env:
            return env
        if outbox is not None:
            payload = dict(outbox.payload_json or {})
            env = str(payload.get("environment") or "").upper()
            if env:
                return env
            if payload.get("account_type"):
                return str(payload.get("account_type")).upper()
        if order.user_broker_account_id is not None and order.account_id is None:
            return "LIVE"
        return "PAPER"

    def _has_broker_submit_audit(self, order_id: int) -> bool:
        try:
            from stock_platform.operation.audit_models import AuditEvent
        except Exception:  # noqa: BLE001
            return False
        row = self._session.scalar(
            select(AuditEvent.audit_event_id)
            .where(
                AuditEvent.event_type.in_(list(_BROKER_SUBMIT_AUDIT_TYPES)),
                AuditEvent.order_id == int(order_id),
            )
            .limit(1)
        )
        return row is not None
