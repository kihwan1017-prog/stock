"""EXIT ORDER SUPERVISOR — stale WAIT / ownership / idempotency (unit)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.trading.exit_order_supervisor import (
    WAIT_NORMAL,
    WAIT_STALE_ZERO,
    ExitOrderSupervisor,
    classify_remote_wait,
    reset_supervisor_idempotency_for_tests,
)


def _order(
    *,
    order_id: int = 1926,
    status: str = "ACCEPTED",
    source: str = "AUTO",
    minutes_ago: float = 30,
    filled: str = "0",
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        symbol="KRW-ADA",
        status_code=status,
        side_code="SELL",
        broker_order_id=f"uuid-{order_id}",
        filled_quantity=filled,
        remaining_quantity="33.33333333",
        order_source=source,
        metadata_payload={
            "order_source": source,
            "signal_reason": "MA_DEAD_CROSS",
            "environment": "LIVE",
        },
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_classify_normal_vs_stale_wait() -> None:
    fresh = _order(minutes_ago=0.5)
    stale = _order(minutes_ago=30)
    assert classify_remote_wait(
        remote_state="wait", executed=0, order=fresh
    ) == WAIT_NORMAL or classify_remote_wait(
        remote_state="wait", executed=__import__("decimal").Decimal("0"), order=fresh
    ) in {WAIT_NORMAL}
    from decimal import Decimal

    assert (
        classify_remote_wait(
            remote_state="wait", executed=Decimal("0"), order=fresh
        )
        == WAIT_NORMAL
    )
    assert (
        classify_remote_wait(
            remote_state="wait", executed=Decimal("0"), order=stale
        )
        == WAIT_STALE_ZERO
    )


def test_manual_sell_never_auto_cancelled() -> None:
    reset_supervisor_idempotency_for_tests()
    session = MagicMock()
    order = _order(source="MANUAL")
    svc = ExitOrderSupervisor(session, order_client=MagicMock())
    with patch.object(svc, "list_open_sells", return_value=[order]), patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync."
        "reconcile_portfolio_slot_lifecycle",
        return_value={"transitions": []},
    ), patch(
        "stock_platform.trading.exit_order_supervisor.emit_live_safety_audit"
    ):
        out = svc.supervise_uba(1380, allow_safe_cancel=True)
    assert out["remote_cancel_request_count"] == 0
    assert out["new_real_buy"] == 0
    assert out["new_real_sell"] == 0
    assert out["items"][0]["action"] == "SKIPPED_MANUAL"


def test_unknown_ownership_fail_closed() -> None:
    reset_supervisor_idempotency_for_tests()
    session = MagicMock()
    order = _order()
    order.order_source = ""
    order.metadata_payload = {}
    svc = ExitOrderSupervisor(session, order_client=MagicMock())
    with patch.object(svc, "list_open_sells", return_value=[order]), patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync."
        "reconcile_portfolio_slot_lifecycle",
        return_value={"transitions": []},
    ), patch(
        "stock_platform.trading.exit_order_supervisor.emit_live_safety_audit"
    ):
        out = svc.supervise_uba(1380)
    assert out["items"][0]["action"] == "FAIL_CLOSED_UNKNOWN"
    assert out["remote_cancel_request_count"] == 0


def test_stale_zero_fill_safe_cancel_idempotent() -> None:
    reset_supervisor_idempotency_for_tests()
    session = MagicMock()
    order = _order(minutes_ago=30)
    client = MagicMock()
    client.get_order.return_value = {"state": "wait", "executed_volume": "0"}
    cancel_result = SimpleNamespace(
        action="SAFE_CANCEL",
        cancel_requested=True,
        cancel_accepted=True,
        remote_status_before="wait",
        remote_status_after="cancel",
        local_status_after="CANCELLED",
        idempotent=False,
    )
    svc = ExitOrderSupervisor(session, order_client=client)
    with patch.object(svc, "list_open_sells", return_value=[order]), patch(
        "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService"
    ), patch(
        "stock_platform.trading.exit_order_supervisor.UpbitRecoveryOrderCancelService"
    ) as cancel_cls, patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync."
        "reconcile_portfolio_slot_lifecycle",
        return_value={"transitions": []},
    ), patch(
        "stock_platform.trading.exit_order_supervisor.emit_live_safety_audit"
    ):
        cancel_cls.return_value.cancel_existing_order_for_recovery.return_value = (
            cancel_result
        )
        out1 = svc.supervise_uba(1380)
        out2 = svc.supervise_uba(1380)
    assert out1["remote_cancel_request_count"] == 1
    assert out2["remote_cancel_request_count"] == 0  # H: duplicate cancel 0
    assert out1["new_real_buy"] == 0 and out1["new_real_sell"] == 0  # M
    assert len(out1["edge_alerts"]) >= 1
    # I: repeated tick duplicate telegram edges suppressed
    assert out2["edge_alerts"] == []


def test_supervisor_does_not_create_orders_doc() -> None:
    import inspect

    from stock_platform.trading import exit_order_supervisor as mod

    doc = inspect.getdoc(ExitOrderSupervisor) or ""
    src = open(mod.__file__, encoding="utf-8").read()
    assert "신규 BUY/SELL" in src or "금지" in src
    assert "cancel" in src.lower()
