"""기존 Upbit OPEN 주문 전용 recovery cancel — 신규 REAL 주문 gate 와 분리.

정책:
- remote exchange 가 최종 SoT
- cancel only (submit/replace/amend 금지)
- LIVE transition / ARM 승인 없이 기존 remote WAIT 주문만 취소
- 취소 후 fill-sync 로 terminal 상태 확정 (fill race 대응)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
)
from stock_platform.broker.upbit.exceptions import UpbitError
from stock_platform.broker.upbit.order_status import normalize_upbit_order_status
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository

BROKER_CODE = "UPBIT"

# db_open 과 동일한 local open 집합 (cancel 대상)
_RECOVERABLE_LOCAL_STATUSES = frozenset(
    {
        OrderStatus.CREATED.value,
        OrderStatus.PENDING.value,
        OrderStatus.SUBMITTING.value,
        OrderStatus.SENT.value,
        OrderStatus.ACCEPTED.value,
        OrderStatus.PARTIALLY_FILLED.value,
        OrderStatus.REMOTE_LOOKUP_PENDING.value,
    }
)

# remote pre-check: 취소 요청 가능 상태
_REMOTE_CANCELABLE = frozenset({"wait", "watch"})

# remote terminal (취소 API 불필요)
_REMOTE_ALREADY_DONE = frozenset({"done"})
_REMOTE_ALREADY_CANCEL = frozenset({"cancel", "cancelled"})


class UpbitRecoveryOrderCancelError(ValueError):
    """Recovery cancel 사전조건/브로커 거절."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass(frozen=True, slots=True)
class UpbitRecoveryOrderCancelResult:
    order_id: int
    user_broker_account_id: int
    broker_order_id: str
    action: str  # NONE | SAFE_CANCEL | RECONCILE_DONE | RECONCILE_CANCELLED
    cancel_requested: bool
    cancel_accepted: bool
    remote_status_before: str | None
    remote_status_after: str | None
    local_status_before: str | None
    local_status_after: str | None
    executed_volume: str
    remaining_volume: str
    idempotent: bool
    detail: dict[str, Any]


class UpbitRecoveryOrderCancelService:
    """LIVE OFF 상태에서도 기존 remote WAIT 주문만 안전 취소."""

    def __init__(
        self,
        session: Session,
        *,
        order_client: Any | None = None,
    ) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        self._order_client = order_client

    def cancel_existing_order_for_recovery(
        self,
        order_id: int,
        *,
        user_broker_account_id: int,
        expected_broker_order_id: str | None = None,
        actor: str = "UPBIT_RECOVERY_ORDER_CANCEL",
    ) -> UpbitRecoveryOrderCancelResult:
        """기존 OPEN 주문 1건 cancel only — 신규 주문 gate 미사용."""

        order = self._orders.get(int(order_id))
        if order is None:
            raise UpbitRecoveryOrderCancelError(
                "ORDER_NOT_FOUND",
                f"Order not found: {order_id}",
            )

        uba_id = int(user_broker_account_id)
        order_uba = getattr(order, "user_broker_account_id", None)
        if order_uba is None or int(order_uba) != uba_id:
            raise UpbitRecoveryOrderCancelError(
                "UBA_MISMATCH",
                "Order UBA ownership mismatch",
                detail={
                    "expected_uba": uba_id,
                    "order_uba": order_uba,
                },
            )

        if str(order.broker_code or "").upper() != BROKER_CODE:
            raise UpbitRecoveryOrderCancelError(
                "NOT_UPBIT",
                "Recovery cancel supports UPBIT orders only",
            )

        meta = order.metadata_payload or {}
        environment = str(meta.get("environment") or "PAPER").upper()
        if environment != "LIVE":
            raise UpbitRecoveryOrderCancelError(
                "NOT_LIVE_ORDER",
                "Recovery cancel supports LIVE environment orders only",
            )

        local_before = str(order.status_code or "")
        if local_before not in _RECOVERABLE_LOCAL_STATUSES:
            raise UpbitRecoveryOrderCancelError(
                "LOCAL_NOT_OPEN",
                f"Local order status is not recoverable-open: {local_before}",
            )

        broker_uuid = str(order.broker_order_id or "").strip()
        if not broker_uuid:
            raise UpbitRecoveryOrderCancelError(
                "BROKER_ORDER_ID_MISSING",
                "broker_order_id is required for recovery cancel",
            )

        if expected_broker_order_id is not None:
            expected = str(expected_broker_order_id).strip()
            if expected != broker_uuid:
                raise UpbitRecoveryOrderCancelError(
                    "BROKER_UUID_MISMATCH",
                    "expected_broker_order_id does not match local order",
                    detail={
                        "expected": expected,
                        "actual": broker_uuid,
                    },
                )

        client = self._resolve_client(uba_id)
        remote_before = client.get_order(uuid=broker_uuid)
        remote_state_before = str(remote_before.get("state") or "").lower()

        executed_before = _dec_str(remote_before.get("executed_volume"))
        remaining_before = _dec_str(remote_before.get("remaining_volume"))

        # 이미 terminal — cancel API 호출 금지, reconcile only
        if remote_state_before in _REMOTE_ALREADY_DONE:
            return self._reconcile_only(
                order_id=int(order_id),
                uba_id=uba_id,
                broker_uuid=broker_uuid,
                remote=remote_before,
                local_before=local_before,
                action="RECONCILE_DONE",
                actor=actor,
            )

        if remote_state_before in _REMOTE_ALREADY_CANCEL:
            return self._reconcile_only(
                order_id=int(order_id),
                uba_id=uba_id,
                broker_uuid=broker_uuid,
                remote=remote_before,
                local_before=local_before,
                action="RECONCILE_CANCELLED",
                actor=actor,
                idempotent=True,
            )

        if remote_state_before not in _REMOTE_CANCELABLE:
            raise UpbitRecoveryOrderCancelError(
                "REMOTE_NOT_CANCELABLE",
                f"Remote order state is not cancelable: {remote_state_before}",
                detail={"remote": _remote_summary(remote_before)},
            )

        # cancel 요청 — CANCEL_REQUESTED 기록 후 broker cancel (UBA vault client)
        self._orders.change_status(
            entity=order,
            new_status=OrderStatus.CANCEL_REQUESTED,
            actor=actor,
            reason_code="RECOVERY_CANCEL_REQUESTED",
        )
        self._session.flush()

        cancel_error: str | None = None
        cancel_payload: dict[str, Any] | None = None
        try:
            cancel_payload = client.cancel_order(uuid=broker_uuid)
        except UpbitError as exc:
            cancel_error = str(exc)[:500]

        # broker 응답만 믿지 않음 — remote 재조회 (짧은 전파 지연 대비 1회 재시도)
        remote_after = client.get_order(uuid=broker_uuid)
        remote_state_after = str(remote_after.get("state") or "").lower()
        if remote_state_after in _REMOTE_CANCELABLE:
            cancel_state = str(
                (cancel_payload or {}).get("state") or ""
            ).lower()
            if cancel_state in _REMOTE_ALREADY_CANCEL | _REMOTE_ALREADY_DONE:
                remote_after = cancel_payload or remote_after
                remote_state_after = cancel_state
            else:
                import time

                time.sleep(0.5)
                remote_after = client.get_order(uuid=broker_uuid)
                remote_state_after = str(remote_after.get("state") or "").lower()
        executed_after = _dec_str(remote_after.get("executed_volume"))
        remaining_after = _dec_str(remote_after.get("remaining_volume"))

        terminal = remote_state_after in (
            _REMOTE_ALREADY_DONE | _REMOTE_ALREADY_CANCEL
        )
        if not terminal:
            raise UpbitRecoveryOrderCancelError(
                "REMOTE_STILL_OPEN",
                "Remote order still non-terminal after cancel request",
                detail={
                    "remote_before": _remote_summary(remote_before),
                    "remote_after": _remote_summary(remote_after),
                    "cancel_error": cancel_error,
                },
            )

        # canonical reconcile (fill race 포함)
        from stock_platform.broker.upbit.fill_sync_service import (
            UpbitFillSyncService,
        )

        sync = UpbitFillSyncService(
            self._session,
            order_client=client,
        ).sync_by_order_id(
            int(order_id),
            actor=actor,
            remote=remote_after,
        )
        self._session.flush()

        order_after = self._orders.get(int(order_id))
        local_after = str(order_after.status_code or "") if order_after else None

        normalized = normalize_upbit_order_status(remote_after)
        cancel_accepted = remote_state_after in _REMOTE_ALREADY_CANCEL or (
            normalized == OrderStatus.CANCELLED
        )

        emit_live_safety_audit(
            self._session,
            event_type="UPBIT_RECOVERY_ORDER_CANCEL",
            actor=actor,
            run_id=None,
            user_id=getattr(order, "user_id", None),
            account_id=uba_id,
            strategy_id=str(getattr(order, "strategy_id", "") or "") or None,
            symbol=str(order.symbol or ""),
            order_id=int(order_id),
            client_order_id=str(order.client_order_id or ""),
            detail={
                "broker_order_id": broker_uuid,
                "remote_status_before": remote_state_before,
                "remote_status_after": remote_state_after,
                "local_status_before": local_before,
                "local_status_after": local_after,
                "cancel_error": cancel_error,
                "cancel_payload_state": (
                    str(cancel_payload.get("state") or "")
                    if isinstance(cancel_payload, dict)
                    else None
                ),
                "fill_sync": {
                    "order_status": sync.order_status,
                    "new_executions": sync.new_executions,
                    "already_processed": sync.already_processed,
                },
            },
            commit=False,
        )

        return UpbitRecoveryOrderCancelResult(
            order_id=int(order_id),
            user_broker_account_id=uba_id,
            broker_order_id=broker_uuid,
            action="SAFE_CANCEL",
            cancel_requested=True,
            cancel_accepted=bool(cancel_accepted),
            remote_status_before=remote_state_before,
            remote_status_after=remote_state_after,
            local_status_before=local_before,
            local_status_after=local_after,
            executed_volume=executed_after or executed_before,
            remaining_volume=remaining_after or remaining_before,
            idempotent=False,
            detail={
                "cancel_error": cancel_error,
                "fill_sync": sync.detail,
            },
        )

    def _reconcile_only(
        self,
        *,
        order_id: int,
        uba_id: int,
        broker_uuid: str,
        remote: dict[str, Any],
        local_before: str,
        action: str,
        actor: str,
        idempotent: bool = False,
    ) -> UpbitRecoveryOrderCancelResult:
        from stock_platform.broker.upbit.fill_sync_service import (
            UpbitFillSyncService,
        )

        client = self._resolve_client(uba_id)
        sync = UpbitFillSyncService(
            self._session,
            order_client=client,
        ).sync_by_order_id(
            int(order_id),
            actor=actor,
            remote=remote,
        )
        self._session.flush()
        order_after = self._orders.get(int(order_id))
        local_after = str(order_after.status_code or "") if order_after else None
        remote_state = str(remote.get("state") or "").lower()

        emit_live_safety_audit(
            self._session,
            event_type="UPBIT_RECOVERY_ORDER_RECONCILE",
            actor=actor,
            run_id=None,
            user_id=getattr(order_after, "user_id", None) if order_after else None,
            account_id=uba_id,
            strategy_id=(
                str(getattr(order_after, "strategy_id", "") or "") or None
                if order_after
                else None
            ),
            symbol=str(getattr(order_after, "symbol", "") or ""),
            order_id=int(order_id),
            detail={
                "broker_order_id": broker_uuid,
                "action": action,
                "remote_status": remote_state,
                "idempotent": idempotent,
                "fill_sync": {
                    "order_status": sync.order_status,
                    "new_executions": sync.new_executions,
                },
            },
            commit=False,
        )

        return UpbitRecoveryOrderCancelResult(
            order_id=int(order_id),
            user_broker_account_id=uba_id,
            broker_order_id=broker_uuid,
            action=action,
            cancel_requested=False,
            cancel_accepted=False,
            remote_status_before=remote_state,
            remote_status_after=remote_state,
            local_status_before=local_before,
            local_status_after=local_after,
            executed_volume=_dec_str(remote.get("executed_volume")),
            remaining_volume=_dec_str(remote.get("remaining_volume")),
            idempotent=idempotent,
            detail={"fill_sync": sync.detail},
        )

    def _resolve_client(self, uba_id: int) -> Any:
        if self._order_client is not None:
            return self._order_client
        return build_upbit_adapter_for_uba(
            self._session, int(uba_id)
        )._client  # noqa: SLF001


def _dec_str(value: Any) -> str:
    if value in (None, ""):
        return "0"
    try:
        text = format(Decimal(str(value)), "f")
    except Exception:  # noqa: BLE001
        return str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _remote_summary(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": remote.get("state"),
        "executed_volume": remote.get("executed_volume"),
        "remaining_volume": remote.get("remaining_volume"),
        "trades_count": remote.get("trades_count"),
        "paid_fee": remote.get("paid_fee"),
    }
