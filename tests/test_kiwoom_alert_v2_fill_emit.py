"""Kiwoom fill → Alert V2 emit wiring (notification only)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.kiwoom.fill_position_write import _emit_kiwoom_fill_alert_v2
from stock_platform.broker.kiwoom.execution_models import KiwoomExecutionEvent


def _order(**kwargs):
    base = {
        "order_id": 9001,
        "symbol": "005930",
        "side_code": "BUY",
        "status_code": "FILLED",
        "strategy_id": 42,
        "strategy_deployment_id": 7,
        "order_source": "AUTO",
        "average_fill_price": 70000,
        "filled_quantity": 1,
        "broker_order_id": "K-1",
        "metadata_payload": {"symbol_name": "삼성전자"},
        "user_broker_account_id": 1381,
        "broker_code": "KIWOOM",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_kiwoom_buy_fill_emits_order_filled() -> None:
    order = _order()
    event = MagicMock(spec=KiwoomExecutionEvent)
    event.side = "BUY"
    event.filled_quantity = 1
    event.fill_price = 70000
    event.price = 70000
    event.broker_order_id = "K-1"
    event.fee = 15
    event.status = "FILLED"

    with patch(
        "stock_platform.order.live_safety_audit.emit_live_order_telegram"
    ) as emit:
        _emit_kiwoom_fill_alert_v2(order=order, event=event)
        assert emit.called
        kwargs = emit.call_args.kwargs
        assert kwargs["event_type"] == "ORDER_FILLED"
        assert kwargs["detail"]["market"] == "KIWOOM"
        assert kwargs["detail"]["side"] == "BUY"
        assert kwargs["detail"]["symbol"] == "005930"
        assert kwargs["detail"]["strategy_id"] == 42


def test_kiwoom_sell_fill_emits() -> None:
    order = _order(side_code="SELL", metadata_payload={"symbol_name": "삼성전자"})
    event = MagicMock(spec=KiwoomExecutionEvent)
    event.side = "SELL"
    event.filled_quantity = 1
    event.fill_price = 71000
    event.price = 71000
    event.broker_order_id = "K-2"
    event.fee = 15
    event.status = "FILLED"

    with patch(
        "stock_platform.order.live_safety_audit.emit_live_order_telegram"
    ) as emit:
        _emit_kiwoom_fill_alert_v2(order=order, event=event)
        assert emit.called
        assert emit.call_args.kwargs["detail"]["side"] == "SELL"
        assert emit.call_args.kwargs["event_type"] == "ORDER_FILLED"


def test_kiwoom_emit_fail_open_does_not_raise() -> None:
    order = _order()
    event = MagicMock(spec=KiwoomExecutionEvent)
    event.side = "BUY"
    event.filled_quantity = 1
    event.fill_price = 1
    event.price = 1
    event.broker_order_id = "K-3"
    event.fee = None
    event.status = "FILLED"

    with patch(
        "stock_platform.order.live_safety_audit.emit_live_order_telegram",
        side_effect=RuntimeError("tg down"),
    ):
        _emit_kiwoom_fill_alert_v2(order=order, event=event)  # must not raise

