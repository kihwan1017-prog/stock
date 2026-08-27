"""Upbit startup open-order reconciliation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.upbit.startup_open_order_reconciliation import (
    UpbitStartupOpenOrderReconciliationService,
    _is_stale_auto_wait,
)
from stock_platform.order.models import OrderStatus
from stock_platform.trading.symbol_ownership.constants import OWNER_AUTO, OWNER_MANUAL


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


def test_auto_sell_wait_not_cancelled() -> None:
    session = MagicMock()
    svc = UpbitStartupOpenOrderReconciliationService(session)
    sell = _auto_order(side="SELL")
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
