"""STARTUP_OPEN_ORDER_RECONCILIATION — ACTIVE lease restore 전 AUTO open order 정리.

정책:
- AUTO-owned local open orders만 처리 (MANUAL/UNKNOWN 자동 cancel 금지)
- remote exchange가 SoT (fill-sync / recovery cancel 재사용)
- 신규 BUY/SELL 생성 금지
- idempotent (이미 terminal이면 no-op)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.broker.upbit.exceptions import UpbitError
from stock_platform.broker.upbit.recovery_order_cancel_service import (
    UpbitRecoveryOrderCancelError,
    UpbitRecoveryOrderCancelService,
)
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.order.models import OrderStatus
from stock_platform.order.order_ownership import (
    ORDER_OWNERSHIP_UNKNOWN,
    classify_local_open_order,
)
from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
)

logger = structlog.get_logger(__name__)

# db_open 과 동일 (cancel_pending 제외 — reconcile 대상)
_LOCAL_OPEN_STATUSES = frozenset(
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

_REMOTE_DONE = frozenset({"done"})
_REMOTE_CANCEL = frozenset({"cancel", "cancelled"})
_REMOTE_WAIT = frozenset({"wait", "watch"})


@dataclass(slots=True)
class StartupOrderReconcileAction:
    order_id: int
    owner: str
    side: str
    action: str
    remote_state_before: str | None = None
    remote_state_after: str | None = None
    local_status_after: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StartupOpenOrderReconciliationResult:
    user_broker_account_id: int
    ok: bool
    auto_open_before: int
    auto_open_after: int
    manual_open_skipped: int
    unknown_open_skipped: int
    actions: list[StartupOrderReconcileAction] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


class UpbitStartupOpenOrderReconciliationService:
    """UBA scoped startup AUTO open order reconcile — lease restore 선행."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._recovery_conflicts = BrokerRecoveryConflictService(session)

    def reconcile_for_uba(
        self,
        user_broker_account_id: int,
        *,
        actor: str = "STARTUP_OPEN_ORDER_RECONCILIATION",
        capture_trace: bool = True,
    ) -> StartupOpenOrderReconciliationResult:
        uba_id = int(user_broker_account_id)
        auto_before = self._count_auto_db_open(uba_id)
        actions: list[StartupOrderReconcileAction] = []
        blockers: list[str] = []
        manual_skipped = 0
        unknown_skipped = 0

        open_rows = self._list_local_open_orders(uba_id)
        client = None

        for order in open_rows:
            meta = order.metadata_payload if isinstance(
                order.metadata_payload, dict
            ) else {}
            decision = classify_local_open_order(
                broker=str(order.broker_code or "UPBIT"),
                uba_id=uba_id,
                symbol=order.symbol,
                local_order_id=int(order.order_id),
                broker_order_id=order.broker_order_id,
                strategy_id=getattr(order, "strategy_id", None),
                strategy_deployment_id=getattr(
                    order, "strategy_deployment_id", None
                ),
                metadata_payload=meta,
                order_source=str(meta.get("order_source") or ""),
            )
            owner = str(decision.owner or OWNER_UNKNOWN).upper()

            if owner == OWNER_MANUAL:
                manual_skipped += 1
                actions.append(
                    StartupOrderReconcileAction(
                        order_id=int(order.order_id),
                        owner=OWNER_MANUAL,
                        side=str(order.side_code or ""),
                        action="SKIPPED_MANUAL",
                    )
                )
                continue

            if owner not in {OWNER_AUTO}:
                unknown_skipped += 1
                actions.append(
                    StartupOrderReconcileAction(
                        order_id=int(order.order_id),
                        owner=OWNER_UNKNOWN,
                        side=str(order.side_code or ""),
                        action="SKIPPED_UNKNOWN",
                        detail={"reasons": list(decision.reasons or [])},
                    )
                )
                blockers.append(ORDER_OWNERSHIP_UNKNOWN)
                continue

            if not str(order.broker_order_id or "").strip():
                # MISSING UUID: AMBIGUOUS + deterministic reject 증명 시
                # CONFIRMED_NOT_SUBMITTED 경로만 허용 (신규 SELL/cancel 금지)
                resolved = self._try_resolve_missing_uuid_not_submitted(
                    order=order,
                    actor=actor,
                )
                if resolved is not None:
                    actions.append(resolved)
                    continue
                blockers.append(f"MISSING_BROKER_UUID:{order.order_id}")
                actions.append(
                    StartupOrderReconcileAction(
                        order_id=int(order.order_id),
                        owner=OWNER_AUTO,
                        side=str(order.side_code or ""),
                        action="BLOCKED_NO_BROKER_UUID",
                    )
                )
                continue

            if client is None:
                client = build_upbit_adapter_for_uba(
                    self._session, uba_id
                )._client  # noqa: SLF001

            action = self._reconcile_auto_order(
                order=order,
                uba_id=uba_id,
                client=client,
                actor=actor,
            )
            actions.append(action)
            if action.action.startswith("BLOCKED"):
                blockers.append(
                    f"{action.action}:{action.order_id}"
                )

        self._session.flush()
        auto_after = self._count_auto_db_open(uba_id)
        ok = auto_after == 0 and ORDER_OWNERSHIP_UNKNOWN not in blockers

        result = StartupOpenOrderReconciliationResult(
            user_broker_account_id=uba_id,
            ok=ok,
            auto_open_before=auto_before,
            auto_open_after=auto_after,
            manual_open_skipped=manual_skipped,
            unknown_open_skipped=unknown_skipped,
            actions=actions,
            blockers=sorted(set(blockers)),
            detail={
                "local_open_scanned": len(open_rows),
                "actor": actor,
            },
        )

        emit_live_safety_audit(
            self._session,
            event_type="UPBIT_STARTUP_OPEN_ORDER_RECONCILIATION",
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=uba_id,
            strategy_id=None,
            detail={
                "ok": ok,
                "auto_open_before": auto_before,
                "auto_open_after": auto_after,
                "manual_open_skipped": manual_skipped,
                "unknown_open_skipped": unknown_skipped,
                "blockers": result.blockers,
                "actions": [
                    {
                        "order_id": a.order_id,
                        "owner": a.owner,
                        "side": a.side,
                        "action": a.action,
                        "remote_state_before": a.remote_state_before,
                        "remote_state_after": a.remote_state_after,
                        "local_status_after": a.local_status_after,
                    }
                    for a in actions
                ],
            },
            commit=False,
        )

        if not ok:
            self._maybe_alert_restore_blocked(uba_id, result)

        if capture_trace:
            try:
                from stock_platform.operation.autotrading_process_version import (
                    service as pvs,
                )

                pvs.capture_operational_recovery_trace(
                    self._session,
                    uba_id=uba_id,
                    result=result,
                    actor=actor,
                )
            except Exception:  # noqa: BLE001
                logger.exception("operational_recovery_trace_failed", uba_id=uba_id)

        logger.info(
            "upbit_startup_open_order_reconciliation",
            uba_id=uba_id,
            ok=ok,
            auto_open_before=auto_before,
            auto_open_after=auto_after,
            manual_skipped=manual_skipped,
        )
        return result

    def _try_resolve_missing_uuid_not_submitted(
        self,
        *,
        order: TradingOrderEntity,
        actor: str,
    ) -> StartupOrderReconcileAction | None:
        """broker_uuid 없는 AUTO open → CONFIRMED_NOT_SUBMITTED 가능하면 종결.

        신규 SELL/CREATE/CANCEL 금지. AmbiguousNotSubmittedResolutionService만 재사용.
        preview 불가·lookup 실패 시 None → 기존 MISSING_BROKER_UUID blocker 유지.
        """

        from stock_platform.order.ambiguous_not_submitted_resolution_service import (
            AmbiguousNotSubmittedResolutionError,
            AmbiguousNotSubmittedResolutionService,
        )

        order_id = int(order.order_id)
        side = str(order.side_code or "").upper()
        service = AmbiguousNotSubmittedResolutionService(self._session)
        preview = service.preview(order_id)
        if not preview.resolvable:
            return None
        try:
            result = service.resolve_and_retire(
                order_id,
                reason=(
                    "STARTUP_OPEN_ORDER_RECONCILIATION:"
                    "MISSING_BROKER_UUID deterministic not-submitted"
                ),
                actor=actor,
                skip_broker_lookup=False,
            )
        except AmbiguousNotSubmittedResolutionError as exc:
            logger.warning(
                "startup_missing_uuid_not_submitted_blocked",
                order_id=order_id,
                code=exc.code,
                blockers=list(exc.blockers),
            )
            return None
        self._session.flush()
        refreshed = self._session.get(TradingOrderEntity, order_id)
        return StartupOrderReconcileAction(
            order_id=order_id,
            owner=OWNER_AUTO,
            side=side,
            action="RESOLVED_CONFIRMED_NOT_SUBMITTED",
            local_status_after=(
                str(refreshed.status_code)
                if refreshed is not None
                else str(result.get("order_status") or "")
            ),
            detail={
                "resolution": result.get("resolution"),
                "reason_code": result.get("reason_code"),
                "outbox_id": result.get("outbox_id"),
                "identifier": result.get("identifier"),
                "idempotent": result.get("idempotent"),
                "create_order_calls": result.get("create_order_calls"),
            },
        )

    def _reconcile_auto_order(
        self,
        *,
        order: TradingOrderEntity,
        uba_id: int,
        client: Any,
        actor: str,
    ) -> StartupOrderReconcileAction:
        order_id = int(order.order_id)
        side = str(order.side_code or "").upper()
        broker_uuid = str(order.broker_order_id or "").strip()
        local_before = str(order.status_code or "")

        try:
            remote = client.get_order(uuid=broker_uuid)
        except UpbitError as exc:
            return StartupOrderReconcileAction(
                order_id=order_id,
                owner=OWNER_AUTO,
                side=side,
                action="BLOCKED_REMOTE_QUERY_FAILED",
                detail={"error": str(exc)[:200]},
            )

        remote_state = str(remote.get("state") or "").lower()
        executed = _dec(remote.get("executed_volume"))

        # partial fill 먼저 반영
        if executed > Decimal("0") or remote_state in _REMOTE_DONE:
            from stock_platform.broker.upbit.fill_sync_service import (
                UpbitFillSyncService,
            )

            sync = UpbitFillSyncService(
                self._session, order_client=client
            ).sync_by_order_id(
                order_id,
                actor=actor,
                remote=remote,
            )
            self._session.flush()
            order = self._session.get(TradingOrderEntity, order_id)
            local_after = str(order.status_code or "") if order else None
            if local_after not in _LOCAL_OPEN_STATUSES:
                return StartupOrderReconcileAction(
                    order_id=order_id,
                    owner=OWNER_AUTO,
                    side=side,
                    action="RECONCILE_DONE",
                    remote_state_before=remote_state,
                    remote_state_after=remote_state,
                    local_status_after=local_after,
                    detail={"fill_sync": sync.detail},
                )
            # partial 후 잔량 WAIT — remote 재조회
            try:
                remote = client.get_order(uuid=broker_uuid)
                remote_state = str(remote.get("state") or "").lower()
            except UpbitError as exc:
                return StartupOrderReconcileAction(
                    order_id=order_id,
                    owner=OWNER_AUTO,
                    side=side,
                    action="BLOCKED_REMOTE_QUERY_FAILED",
                    detail={"error": str(exc)[:200]},
                )

        if remote_state in _REMOTE_CANCEL:
            from stock_platform.broker.upbit.fill_sync_service import (
                UpbitFillSyncService,
            )

            sync = UpbitFillSyncService(
                self._session, order_client=client
            ).sync_by_order_id(
                order_id,
                actor=actor,
                remote=remote,
            )
            self._session.flush()
            order = self._session.get(TradingOrderEntity, order_id)
            return StartupOrderReconcileAction(
                order_id=order_id,
                owner=OWNER_AUTO,
                side=side,
                action="RECONCILE_CANCELLED",
                remote_state_before=remote_state,
                remote_state_after=remote_state,
                local_status_after=(
                    str(order.status_code or "") if order else None
                ),
                detail={"fill_sync": sync.detail},
            )

        if remote_state in _REMOTE_WAIT:
            # NORMAL WAIT(신선) — BUY/SELL 모두 cancel 금지 (stale 만 SAFE_CANCEL)
            if not _is_stale_auto_wait(order):
                # 하위 호환: fresh protective SELL 은 명시 액션 유지
                action_code = (
                    "BLOCKED_AUTO_SELL_WAIT"
                    if side == "SELL"
                    else "BLOCKED_FRESH_AUTO_WAIT"
                )
                return StartupOrderReconcileAction(
                    order_id=order_id,
                    owner=OWNER_AUTO,
                    side=side,
                    action=action_code,
                    remote_state_before=remote_state,
                    detail={
                        "note": (
                            "protective SELL WAIT not auto-cancelled (fresh)"
                            if side == "SELL"
                            else "WAIT not stale — startup restore blocked"
                        ),
                        "wait_class": "NORMAL_WAIT",
                    },
                )
            # STALE zero/partial WAIT — 기존 recovery-cancel canonical (신규 주문 없음)
            try:
                cancel_result = UpbitRecoveryOrderCancelService(
                    self._session,
                    order_client=client,
                ).cancel_existing_order_for_recovery(
                    order_id,
                    user_broker_account_id=uba_id,
                    expected_broker_order_id=broker_uuid,
                    actor=f"{actor}_SAFE_CANCEL",
                )
                return StartupOrderReconcileAction(
                    order_id=order_id,
                    owner=OWNER_AUTO,
                    side=side,
                    action="SAFE_CANCEL",
                    remote_state_before=cancel_result.remote_status_before,
                    remote_state_after=cancel_result.remote_status_after,
                    local_status_after=cancel_result.local_status_after,
                    detail={
                        "cancel": cancel_result.action,
                        "wait_class": "STALE_WAIT",
                        "side": side,
                    },
                )
            except UpbitRecoveryOrderCancelError as exc:
                return StartupOrderReconcileAction(
                    order_id=order_id,
                    owner=OWNER_AUTO,
                    side=side,
                    action="BLOCKED_CANCEL_FAILED",
                    remote_state_before=remote_state,
                    detail={"code": exc.code, "message": exc.message},
                )

        return StartupOrderReconcileAction(
            order_id=order_id,
            owner=OWNER_AUTO,
            side=side,
            action="BLOCKED_REMOTE_OTHER",
            remote_state_before=remote_state,
        )

    def _list_local_open_orders(
        self, uba_id: int
    ) -> list[TradingOrderEntity]:
        return list(
            self._session.scalars(
                select(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id == int(uba_id),
                    TradingOrderEntity.broker_code == "UPBIT",
                    TradingOrderEntity.status_code.in_(
                        list(_LOCAL_OPEN_STATUSES)
                    ),
                )
                .order_by(TradingOrderEntity.order_id.asc())
            )
        )

    def _count_auto_db_open(self, uba_id: int) -> int:
        """Restore gate와 동일 — AUTO protective SELL open 제외."""

        blocking = self._recovery_conflicts.count_blocking_orders_for_uba(
            int(uba_id),
            exclude_auto_protective_exits=True,
        )
        return int(blocking.get("db_open") or 0)

    def _maybe_alert_restore_blocked(
        self,
        uba_id: int,
        result: StartupOpenOrderReconciliationResult,
    ) -> None:
        try:
            from stock_platform.order.live_safety_audit import (
                emit_live_order_telegram,
            )

            emit_live_order_telegram(
                event_type="UPBIT_STARTUP_RESTORE_BLOCKED",
                title="🔴 [업비트] 자동매매 재시작 복구 차단",
                message=(
                    f"UBA {uba_id}: 미해결 AUTO 주문 "
                    f"{result.auto_open_after}건. "
                    "LIVE unattended restore 보류."
                ),
                detail={
                    "user_broker_account_id": uba_id,
                    "auto_open_after": result.auto_open_after,
                    "blockers": result.blockers,
                },
            )
        except Exception:  # noqa: BLE001
            pass


def reconcile_active_upbit_leases_before_restore(
    session: Session,
    *,
    uba_ids: list[int],
    actor: str = "STARTUP_OPEN_ORDER_RECONCILIATION",
) -> dict[str, Any]:
    """ACTIVE UPBIT lease UBA 목록에 대해 pre-restore reconciliation."""

    svc = UpbitStartupOpenOrderReconciliationService(session)
    results: list[dict[str, Any]] = []
    all_ok = True
    for uba_id in uba_ids:
        row = svc.reconcile_for_uba(int(uba_id), actor=actor)
        results.append(
            {
                "user_broker_account_id": row.user_broker_account_id,
                "ok": row.ok,
                "auto_open_before": row.auto_open_before,
                "auto_open_after": row.auto_open_after,
                "manual_open_skipped": row.manual_open_skipped,
                "unknown_open_skipped": row.unknown_open_skipped,
                "blockers": row.blockers,
            }
        )
        if not row.ok:
            all_ok = False
    return {"ok": all_ok, "results": results}


def _is_stale_auto_wait(order: TradingOrderEntity) -> bool:
    """기존 SoT: upbit_portfolio_entry_pending_timeout_seconds."""

    settings = get_settings()
    timeout = float(
        getattr(
            settings,
            "upbit_portfolio_entry_pending_timeout_seconds",
            120.0,
        )
        or 120.0
    )
    created = getattr(order, "created_at", None)
    if created is None:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    return age >= timeout


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal("0")
