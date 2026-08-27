"""EXIT ORDER SUPERVISOR — ACCEPTED protective SELL 독립 감시/복구.

책임 (허용):
- ACCEPTED/open SELL 조회
- remote status polling + fill-sync
- partial/terminal reconcile
- stale WAIT 판정 + safe recovery-cancel (canonical)
- incident / recovery edge alert payload

책임 (금지):
- 신규 BUY/SELL 생성
- entry/exit signal 생성
- threshold 변경
- MANUAL / UNKNOWN ownership cancel
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.recovery_order_cancel_service import (
    UpbitRecoveryOrderCancelError,
    UpbitRecoveryOrderCancelService,
)
from stock_platform.broker.upbit.startup_open_order_reconciliation import (
    _is_stale_auto_wait,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_safety_audit import emit_live_safety_audit

# Wait classification (cancel 정책용)
WAIT_NORMAL = "NORMAL_WAIT"
WAIT_PARTIAL = "PARTIAL_FILL_WAIT"
WAIT_STALE_ZERO = "STALE_ZERO_FILL_WAIT"
WAIT_STALE_PARTIAL = "STALE_PARTIAL_FILL_WAIT"
TERMINAL_DONE = "TERMINAL_DONE"
TERMINAL_CANCEL = "TERMINAL_CANCEL"
UNKNOWN_REMOTE = "UNKNOWN_REMOTE"

_OPEN_LOCAL = frozenset(
    {
        "CREATED",
        "PENDING",
        "SUBMITTING",
        "SENT",
        "ACCEPTED",
        "PARTIALLY_FILLED",
        "PARTIAL",
        "OPEN",
        "SUBMITTED",
        "REMOTE_LOOKUP_PENDING",
    }
)

# 동일 주문에 대한 cancel 중복 방지 (프로세스 내)
_cancel_once: set[int] = set()
_alert_edges: dict[str, str] = {}


@dataclass
class ExitOrderSupervisionItem:
    order_id: int
    symbol: str
    local_status: str
    remote_status: str | None
    filled: str
    remaining: str
    wait_age_seconds: float | None
    wait_class: str
    ownership: str
    self_heal_status: str
    action: str
    detail: dict[str, Any] = field(default_factory=dict)


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _order_meta(order: TradingOrderEntity) -> dict[str, Any]:
    raw = getattr(order, "metadata_payload", None) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _ownership(order: TradingOrderEntity) -> str:
    meta = _order_meta(order)
    src = str(
        getattr(order, "order_source", None) or meta.get("order_source") or ""
    ).upper()
    if src in {"MANUAL", "USER", "OPERATOR"}:
        return "MANUAL"
    if src in {"AUTO", "EXIT", "REALTIME_SIGNAL"} or str(
        meta.get("source") or ""
    ).upper() in {"REALTIME_SIGNAL", "POSITION_EXIT_MONITOR"}:
        return "AUTO"
    if not src and not meta:
        return "UNKNOWN"
    # 메타만 있는 AUTO 신호
    reason = str(meta.get("signal_reason") or "").upper()
    if reason:
        return "AUTO"
    return "UNKNOWN"


def _age_seconds(order: TradingOrderEntity, now: datetime) -> float | None:
    created = getattr(order, "created_at", None)
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created.astimezone(timezone.utc)).total_seconds()


def classify_remote_wait(
    *,
    remote_state: str | None,
    executed: Decimal,
    order: TradingOrderEntity,
) -> str:
    state = str(remote_state or "").lower()
    if state in {"done"}:
        return TERMINAL_DONE
    if state in {"cancel", "cancelled"}:
        return TERMINAL_CANCEL
    if state not in {"wait", "watch"}:
        return UNKNOWN_REMOTE
    stale = _is_stale_auto_wait(order)
    if executed > 0:
        return WAIT_STALE_PARTIAL if stale else WAIT_PARTIAL
    return WAIT_STALE_ZERO if stale else WAIT_NORMAL


class ExitOrderSupervisor:
    """스택 RUNNING 여부와 무관하게 protective SELL 복구를 시도."""

    def __init__(self, session: Session, *, order_client: Any | None = None) -> None:
        self._session = session
        self._order_client = order_client

    def list_open_sells(self, uba_id: int) -> list[TradingOrderEntity]:
        rows = self._session.execute(
            text(
                """
                SELECT order_id
                FROM trading.trading_order
                WHERE user_broker_account_id = :uba
                  AND broker_code = 'UPBIT'
                  AND UPPER(side_code) = 'SELL'
                  AND UPPER(status_code) = ANY(:st)
                ORDER BY order_id ASC
                """
            ),
            {"uba": int(uba_id), "st": list(_OPEN_LOCAL)},
        ).scalars().all()
        out: list[TradingOrderEntity] = []
        for oid in rows:
            ent = self._session.get(TradingOrderEntity, int(oid))
            if ent is not None:
                out.append(ent)
        return out

    def supervise_uba(
        self,
        uba_id: int,
        *,
        actor: str = "EXIT_ORDER_SUPERVISOR",
        allow_safe_cancel: bool = True,
    ) -> dict[str, Any]:
        """UBA 단위 1 tick — 신규 주문 생성 없음."""

        from stock_platform.broker.credential_adapter_factory import (
            build_upbit_adapter_for_uba,
        )
        from stock_platform.broker.upbit.fill_sync_service import UpbitFillSyncService
        from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
            reconcile_portfolio_slot_lifecycle,
        )

        now = datetime.now(timezone.utc)
        items: list[ExitOrderSupervisionItem] = []
        cancel_count = 0
        new_buy = 0
        new_sell = 0
        alerts: list[dict[str, Any]] = []

        client = self._order_client
        if client is None:
            client = build_upbit_adapter_for_uba(self._session, int(uba_id))._client

        sync = UpbitFillSyncService(self._session)
        for order in self.list_open_sells(int(uba_id)):
            oid = int(order.order_id)
            owner = _ownership(order)
            filled = _dec(getattr(order, "filled_quantity", 0))
            remaining = _dec(getattr(order, "remaining_quantity", 0))
            broker_uuid = str(getattr(order, "broker_order_id", "") or "")
            age = _age_seconds(order, now)
            remote_state: str | None = None
            executed = filled
            action = "OBSERVE"
            heal = "IDLE"
            detail: dict[str, Any] = {}

            if owner == "MANUAL":
                wait_class = WAIT_NORMAL
                action = "SKIPPED_MANUAL"
                heal = "MANUAL_PROTECTED"
            elif owner == "UNKNOWN":
                wait_class = UNKNOWN_REMOTE
                action = "FAIL_CLOSED_UNKNOWN"
                heal = "UNKNOWN_PROTECTED"
            elif not broker_uuid:
                wait_class = UNKNOWN_REMOTE
                action = "FAIL_CLOSED_NO_BROKER_UUID"
                heal = "FAIL_CLOSED"
            else:
                try:
                    remote = client.get_order(uuid=broker_uuid)
                    remote_state = str(remote.get("state") or "").lower()
                    executed = _dec(remote.get("executed_volume"))
                except Exception as exc:  # noqa: BLE001
                    remote_state = None
                    wait_class = UNKNOWN_REMOTE
                    action = "REMOTE_QUERY_FAILED"
                    heal = "ERROR"
                    detail = {"error": type(exc).__name__}
                    items.append(
                        ExitOrderSupervisionItem(
                            order_id=oid,
                            symbol=str(order.symbol or ""),
                            local_status=str(order.status_code or ""),
                            remote_status=remote_state,
                            filled=str(filled),
                            remaining=str(remaining),
                            wait_age_seconds=age,
                            wait_class=wait_class,
                            ownership=owner,
                            self_heal_status=heal,
                            action=action,
                            detail=detail,
                        )
                    )
                    continue

                wait_class = classify_remote_wait(
                    remote_state=remote_state,
                    executed=executed,
                    order=order,
                )

                if wait_class == TERMINAL_DONE:
                    sync.sync_by_order_id(oid, actor=f"{actor}:DONE")
                    action = "FILL_SYNC_DONE"
                    heal = "RECONCILED"
                elif wait_class == TERMINAL_CANCEL:
                    sync.sync_by_order_id(oid, actor=f"{actor}:CANCEL")
                    action = "RECONCILE_CANCELLED"
                    heal = "RECONCILED"
                elif wait_class == WAIT_NORMAL:
                    action = "HOLD_NORMAL_WAIT"
                    heal = "MONITORING"
                elif wait_class == WAIT_PARTIAL:
                    sync.sync_by_order_id(oid, actor=f"{actor}:PARTIAL")
                    action = "PARTIAL_FILL_SYNC"
                    heal = "MONITORING"
                elif wait_class in {WAIT_STALE_ZERO, WAIT_STALE_PARTIAL}:
                    alerts.append(
                        {
                            "edge": "STUCK",
                            "order_id": oid,
                            "symbol": str(order.symbol or ""),
                            "wait_class": wait_class,
                        }
                    )
                    if wait_class == WAIT_STALE_PARTIAL:
                        # partial 먼저 보존 동기화 — remaining 만 cancel 대상
                        sync.sync_by_order_id(oid, actor=f"{actor}:STALE_PARTIAL")
                    if allow_safe_cancel and oid not in _cancel_once:
                        try:
                            alerts.append(
                                {
                                    "edge": "AUTO_RECOVERY",
                                    "order_id": oid,
                                    "symbol": str(order.symbol or ""),
                                }
                            )
                            result = UpbitRecoveryOrderCancelService(
                                self._session,
                                order_client=client,
                            ).cancel_existing_order_for_recovery(
                                oid,
                                user_broker_account_id=int(uba_id),
                                expected_broker_order_id=broker_uuid,
                                actor=actor,
                            )
                            _cancel_once.add(oid)
                            if result.cancel_requested:
                                cancel_count += 1
                            action = "SAFE_CANCEL"
                            heal = "RECOVERING"
                            detail = {
                                "cancel_action": result.action,
                                "remote_before": result.remote_status_before,
                                "remote_after": result.remote_status_after,
                                "local_after": result.local_status_after,
                                "idempotent": result.idempotent,
                            }
                            if str(result.remote_status_after or "").lower() in {
                                "cancel",
                                "cancelled",
                            }:
                                heal = "RECOVERED"
                                alerts.append(
                                    {
                                        "edge": "RECOVERED",
                                        "order_id": oid,
                                        "symbol": str(order.symbol or ""),
                                    }
                                )
                        except UpbitRecoveryOrderCancelError as exc:
                            action = "CANCEL_BLOCKED"
                            heal = "FAIL_CLOSED"
                            detail = {"code": exc.code, "message": exc.message}
                    elif oid in _cancel_once:
                        action = "CANCEL_IDEMPOTENT_SKIP"
                        heal = "IDEMPOTENT"
                    else:
                        action = "STALE_DETECTED_NO_CANCEL"
                        heal = "INCIDENT"
                else:
                    action = "OBSERVE_UNKNOWN_REMOTE"
                    heal = "FAIL_CLOSED"

            items.append(
                ExitOrderSupervisionItem(
                    order_id=oid,
                    symbol=str(order.symbol or ""),
                    local_status=str(order.status_code or ""),
                    remote_status=remote_state,
                    filled=str(executed if executed else filled),
                    remaining=str(remaining),
                    wait_age_seconds=round(age, 1) if age is not None else None,
                    wait_class=wait_class,
                    ownership=owner,
                    self_heal_status=heal,
                    action=action,
                    detail=detail,
                )
            )

        life = reconcile_portfolio_slot_lifecycle(
            self._session,
            user_broker_account_id=int(uba_id),
            actor=f"{actor}:LIFECYCLE",
        )

        edge_alerts = _dedupe_edge_alerts(int(uba_id), alerts)
        if edge_alerts:
            emit_live_safety_audit(
                self._session,
                event_type="EXIT_ORDER_SUPERVISOR_TICK",
                actor=actor,
                run_id=None,
                user_id=None,
                account_id=int(uba_id),
                strategy_id=None,
                detail={
                    "items": [i.__dict__ for i in items],
                    "edge_alerts": edge_alerts,
                    "cancel_count": cancel_count,
                },
                commit=False,
            )

        return {
            "ok": True,
            "uba_id": int(uba_id),
            "items": [i.__dict__ for i in items],
            "remote_cancel_request_count": cancel_count,
            "new_real_buy": new_buy,
            "new_real_sell": new_sell,
            "lifecycle_transitions": len(list(life.get("transitions") or [])),
            "lifecycle": life,
            "edge_alerts": edge_alerts,
            "supervisor": "EXIT_ORDER_SUPERVISOR",
        }


def _dedupe_edge_alerts(
    uba_id: int, alerts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """동일 edge+order 반복 tick 전송 방지."""

    out: list[dict[str, Any]] = []
    for a in alerts:
        key = f"{uba_id}:{a.get('edge')}:{a.get('order_id')}"
        if _alert_edges.get(key) == "sent":
            continue
        _alert_edges[key] = "sent"
        out.append(a)
    return out


def reset_supervisor_idempotency_for_tests() -> None:
    """테스트 전용 — 프로세스 내 cancel/alert edge 초기화."""

    _cancel_once.clear()
    _alert_edges.clear()
