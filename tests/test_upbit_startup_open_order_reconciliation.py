"""Upbit startup open-order reconciliation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.upbit.startup_open_order_reconciliation import (
    UpbitStartupOpenOrderReconciliationService,
    _is_stale_auto_wait,
)
from stock_platform.order.models import OrderStatus
from stock_platform.trading.symbol_ownership.constants import OWNER_AUTO


def _auto_order(
    *,
    order_id: int = 1896,
    side: str = "BUY",
    status: str = OrderStatus.ACCEPTED.value,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        broker_code="UPBIT",
        broker_order_id="uuid-1896",
        status_code=status,
        symbol="KRW-XRP",
        side_code=side,
        strategy_id=17483,
        strategy_deployment_id=868,
        metadata_payload={"order_source": "AUTO", "environment": "LIVE"},
        created_at=created_at
        or datetime.now(timezone.utc) - timedelta(minutes=30),
    )


def _manual_order(order_id: int = 2000) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        broker_code="UPBIT",
        broker_order_id="uuid-manual",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-BTC",
        side_code="BUY",
        strategy_id=None,
        strategy_deployment_id=None,
        metadata_payload={"order_source": "MANUAL", "environment": "LIVE"},
        created_at=datetime.now(timezone.utc),
    )


def test_manual_open_untouched() -> None:
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    manual = _manual_order()

    with patch.object(svc, "_list_local_open_orders", return_value=[manual]), patch.object(
        svc, "_count_auto_db_open", return_value=0
    ), patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation.emit_live_safety_audit"
    ), patch(
        "stock_platform.operation.autotrading_process_version.service.capture_operational_recovery_trace"
    ):
        result = svc.reconcile_for_uba(1380, capture_trace=False)

    assert result.manual_open_skipped == 1
    assert result.ok is True
    assert any(a.action == "SKIPPED_MANUAL" for a in result.actions)


def test_stale_wait_triggers_safe_cancel_path() -> None:
    order = _auto_order()
    assert _is_stale_auto_wait(order) is True
    fresh = _auto_order(
        created_at=datetime.now(timezone.utc) - timedelta(seconds=30)
    )
    assert _is_stale_auto_wait(fresh) is False


def test_auto_sell_fresh_wait_not_cancelled() -> None:
    """A: NORMAL_WAIT SELL — cancel 안 함."""
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    sell = _auto_order(
        side="SELL",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    client = MagicMock()
    client.get_order.return_value = {
        "state": "wait",
        "executed_volume": "0",
    }

    action = svc._reconcile_auto_order(
        order=sell,
        uba_id=1380,
        client=client,
        actor="TEST",
    )
    assert action.action == "BLOCKED_AUTO_SELL_WAIT"
    client.cancel_order.assert_not_called()


def test_auto_sell_stale_wait_safe_cancel() -> None:
    """B/H: stale zero-fill AUTO SELL → SAFE_CANCEL (idempotent path)."""
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    sell = _auto_order(side="SELL")  # 30분 전 → stale
    client = MagicMock()
    client.get_order.return_value = {
        "state": "wait",
        "executed_volume": "0",
    }
    cancel_result = SimpleNamespace(
        action="SAFE_CANCEL",
        remote_status_before="wait",
        remote_status_after="cancel",
        local_status_after="CANCELLED",
    )

    with patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation."
        "UpbitRecoveryOrderCancelService"
    ) as cancel_cls:
        cancel_cls.return_value.cancel_existing_order_for_recovery.return_value = (
            cancel_result
        )
        action = svc._reconcile_auto_order(
            order=sell,
            uba_id=1380,
            client=client,
            actor="TEST",
        )

    assert action.action == "SAFE_CANCEL"
    cancel_cls.return_value.cancel_existing_order_for_recovery.assert_called_once()


def test_remote_done_reconcile_no_cancel() -> None:
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    order = _auto_order()
    client = MagicMock()
    client.get_order.return_value = {
        "state": "done",
        "executed_volume": "1",
        "trades": [{"price": "100", "volume": "1"}],
    }
    sync_result = SimpleNamespace(
        detail={},
        order_status=OrderStatus.FILLED.value,
    )

    with patch(
        "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService.sync_by_order_id",
        return_value=sync_result,
    ):
        session.get.return_value = SimpleNamespace(status_code=OrderStatus.FILLED.value)
        action = svc._reconcile_auto_order(
            order=order,
            uba_id=1380,
            client=client,
            actor="TEST",
        )

    assert action.action == "RECONCILE_DONE"
    client.cancel_order.assert_not_called()


def test_no_auto_open_passes() -> None:
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)

    with patch.object(svc, "_list_local_open_orders", return_value=[]), patch.object(
        svc, "_count_auto_db_open", return_value=0
    ), patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation.emit_live_safety_audit"
    ), patch(
        "stock_platform.operation.autotrading_process_version.service.capture_operational_recovery_trace"
    ):
        result = svc.reconcile_for_uba(1380, capture_trace=False)

    assert result.ok is True
    assert result.auto_open_before == 0


def test_missing_uuid_resolves_confirmed_not_submitted() -> None:
    """MISSING UUID + resolvable AMBIGUOUS → CONFIRMED_NOT_SUBMITTED (신규 SELL 없음)."""

    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    order = _auto_order(order_id=1947)
    order.broker_order_id = None
    order.status_code = OrderStatus.PENDING.value

    preview = MagicMock(resolvable=True)
    resolve_result = {
        "resolution": "CONFIRMED_NOT_SUBMITTED",
        "reason_code": "BROKER_NOT_REACHED_LOCAL_VALIDATION_FAILURE",
        "outbox_id": 1384,
        "identifier": "spu-test",
        "idempotent": False,
        "create_order_calls": 0,
        "order_status": OrderStatus.CANCELLED.value,
    }

    with patch.object(svc, "_list_local_open_orders", return_value=[order]), patch.object(
        svc, "_count_auto_db_open", side_effect=[1, 0]
    ), patch(
        "stock_platform.order.ambiguous_not_submitted_resolution_service."
        "AmbiguousNotSubmittedResolutionService"
    ) as amb_cls, patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation.emit_live_safety_audit"
    ), patch(
        "stock_platform.operation.autotrading_process_version.service.capture_operational_recovery_trace"
    ):
        amb = amb_cls.return_value
        amb.preview.return_value = preview
        amb.resolve_and_retire.return_value = resolve_result
        session.get.return_value = SimpleNamespace(
            status_code=OrderStatus.CANCELLED.value
        )
        result = svc.reconcile_for_uba(1380, capture_trace=False)

    assert result.ok is True
    assert result.blockers == []
    assert any(
        a.action == "RESOLVED_CONFIRMED_NOT_SUBMITTED" for a in result.actions
    )
    amb.resolve_and_retire.assert_called_once()
    assert amb.resolve_and_retire.call_args.kwargs.get("skip_broker_lookup") is False


def test_missing_uuid_still_blocks_when_not_resolvable() -> None:
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    order = _auto_order(order_id=1947)
    order.broker_order_id = None
    order.status_code = OrderStatus.PENDING.value

    with patch.object(svc, "_list_local_open_orders", return_value=[order]), patch.object(
        svc, "_count_auto_db_open", side_effect=[1, 1]
    ), patch(
        "stock_platform.order.ambiguous_not_submitted_resolution_service."
        "AmbiguousNotSubmittedResolutionService"
    ) as amb_cls, patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation.emit_live_safety_audit"
    ), patch(
        "stock_platform.operation.autotrading_process_version.service.capture_operational_recovery_trace"
    ), patch.object(svc, "_maybe_alert_restore_blocked"):
        amb_cls.return_value.preview.return_value = MagicMock(
            resolvable=False, blockers=["local_pre_send_failure_not_proven"]
        )
        result = svc.reconcile_for_uba(1380, capture_trace=False)

    assert result.ok is False
    assert "MISSING_BROKER_UUID:1947" in result.blockers
    amb_cls.return_value.resolve_and_retire.assert_not_called()


def test_unresolved_auto_blocks_ok() -> None:
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    order = _auto_order()

    with patch.object(svc, "_list_local_open_orders", return_value=[order]), patch.object(
        svc, "_count_auto_db_open", side_effect=[1, 1]
    ), patch.object(
        svc,
        "_reconcile_auto_order",
        return_value=MagicMock(
            order_id=1896,
            owner=OWNER_AUTO,
            side="BUY",
            action="BLOCKED_FRESH_AUTO_WAIT",
            remote_state_before="wait",
            remote_state_after=None,
            local_status_after=OrderStatus.ACCEPTED.value,
            detail={},
        ),
    ), patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation.build_upbit_adapter_for_uba",
        return_value=MagicMock(_client=MagicMock()),
    ), patch(
        "stock_platform.broker.upbit.startup_open_order_reconciliation.emit_live_safety_audit"
    ), patch(
        "stock_platform.operation.autotrading_process_version.service.capture_operational_recovery_trace"
    ), patch.object(svc, "_maybe_alert_restore_blocked"):
        result = svc.reconcile_for_uba(1380, capture_trace=False)

    assert result.ok is False
    assert result.auto_open_after == 1
