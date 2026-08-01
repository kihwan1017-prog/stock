"""LIVE Shadow Mode — Broker 주문 전송 0 검증."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.models import BrokerOrderSide, BrokerOrderType
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.live_shadow import (
    is_live_shadow_mode,
    reset_shadow_counters,
    shadow_block_dispatch_result,
    shadow_counters,
    should_block_live_broker_call,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_models import OutboxEventType
from stock_platform.realtime.execution_models import RealtimeExecutionMode
from stock_platform.realtime.live_runtime_control import (
    live_auto_start_allowed,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


def test_shadow_flag_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache, get_settings

    clear_settings_cache()
    assert get_settings().live_shadow_mode_enabled is False
    assert is_live_shadow_mode() is False


def test_should_block_live_broker_call() -> None:
    assert should_block_live_broker_call({"environment": "PAPER"}) is False
    assert (
        should_block_live_broker_call(
            {"environment": "LIVE", "shadow": True}
        )
        is True
    )


def test_dispatcher_blocks_submit_without_adapter_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    reset_shadow_counters()

    adapter = MagicMock()
    adapter.submit_order.side_effect = AssertionError("must not submit")
    adapter.cancel_order.side_effect = AssertionError("must not cancel")
    adapter.replace_order.side_effect = AssertionError("must not replace")

    dispatcher = OrderOutboxDispatcher(adapter=adapter, session=MagicMock())
    payload = {
        "environment": "LIVE",
        "shadow": True,
        "client_order_id": "SH1",
        "account_id": 1,
        "broker_code": "KIWOOM",
        "exchange_code": "KRX",
        "symbol": "005930",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "1",
        "price": "70000",
        "user_broker_account_id": 10,
    }
    for event in (
        OutboxEventType.SUBMIT_ORDER.value,
        OutboxEventType.CANCEL_ORDER.value,
        OutboxEventType.REPLACE_ORDER.value,
    ):
        if event != OutboxEventType.SUBMIT_ORDER.value:
            payload["broker_order_id"] = "SHOULD-NOT-USE"
            payload["cancel_quantity"] = "1"
        result = dispatcher.dispatch(
            event_type=event,
            payload=payload,
            idempotency_key=f"IDEM-{event}",
            session=MagicMock(),
        )
        assert result["shadow_blocked"] is True
        assert result["broker_order_id"] is None
        assert result["reject_code"] == "LIVE_SHADOW_MODE"

    assert adapter.submit_order.call_count == 0
    assert adapter.cancel_order.call_count == 0
    assert adapter.replace_order.call_count == 0
    assert shadow_counters()["broker_mutate_attempts"] >= 3
    clear_settings_cache()


def test_execution_service_shadow_intent_no_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()

    session = MagicMock()
    svc = OrderExecutionService.__new__(OrderExecutionService)
    svc._session = session
    created = SimpleNamespace(
        order_id=99,
        client_order_id="C-SHADOW",
        account_id=1,
        user_broker_account_id=7,
        broker_code="KIWOOM",
        exchange_code="KRX",
        symbol="005930",
        side_code="BUY",
        order_type_code="LIMIT",
        order_quantity=Decimal("1"),
        order_price=Decimal("70000"),
        time_in_force_code="DAY",
        status_code="CREATED",
        broker_order_id=None,
        metadata_payload={},
        reject_code=None,
        reject_message=None,
    )
    svc._order_service = SimpleNamespace(
        create=lambda *a, **k: created
    )
    svc._order_repository = SimpleNamespace(
        change_status=lambda **kw: setattr(
            created, "status_code", kw["new_status"].value
        )
        or created,
        get=lambda oid: created,
    )
    svc._outbox_repository = SimpleNamespace(
        get_by_idempotency_key=lambda k: None,
        enqueue=MagicMock(side_effect=AssertionError("no outbox")),
    )
    svc._sizing_engine = SimpleNamespace()

    with patch.object(
        OrderExecutionService,
        "_resolve_size",
        return_value=(Decimal("1"), Decimal("70000"), None),
    ):
        result = svc.submit(
            OrderExecutionCommand(
                account_id=1,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=Decimal("70000"),
                environment="LIVE",
                user_broker_account_id=7,
                skip_risk_checks=True,
                actor="TEST",
                idempotency_key="SHADOW-IDEM-1",
                client_order_id="C-SHADOW",
            )
        )

    assert result.allowed is True
    assert result.reason_code == "LIVE_SHADOW_INTENT"
    assert result.outbox_id is None
    assert result.order_id == 99
    assert created.broker_order_id is None
    assert created.reject_code == "LIVE_SHADOW_MODE"
    assert created.status_code == "REJECTED"
    clear_settings_cache()


def test_shadow_idempotent_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    session = MagicMock()
    svc = OrderExecutionService.__new__(OrderExecutionService)
    svc._session = session
    existing_order = SimpleNamespace(
        status_code="REJECTED",
        client_order_id="C1",
        order_quantity=Decimal("1"),
        order_price=Decimal("100"),
    )
    existing_outbox = SimpleNamespace(order_id=1, outbox_id=2)
    svc._outbox_repository = SimpleNamespace(
        get_by_idempotency_key=lambda k: existing_outbox
    )
    svc._order_repository = SimpleNamespace(get=lambda oid: existing_order)
    svc._order_service = SimpleNamespace()
    svc._sizing_engine = SimpleNamespace()

    with patch.object(
        OrderExecutionService,
        "_resolve_size",
        return_value=(Decimal("1"), Decimal("100"), None),
    ):
        result = svc.submit(
            OrderExecutionCommand(
                account_id=1,
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=Decimal("100"),
                environment="LIVE",
                user_broker_account_id=3,
                skip_risk_checks=True,
                idempotency_key="DUP-KEY",
            )
        )
    assert result.reason_code == "IDEMPOTENT_REPLAY"
    clear_settings_cache()


def test_kill_switch_still_blocks_before_shadow() -> None:
    from stock_platform.realtime.risk_integrated_order_executor import (
        RiskIntegratedRealtimeOrderExecutor,
    )
    from stock_platform.realtime.execution_models import RealtimeExecutionConfig
    from stock_platform.realtime.safety_guard import RealtimeOrderSafetyGuard
    from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig

    session = MagicMock()
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_order_amount=Decimal("1000000"),
            max_daily_loss=Decimal("1000000"),
            max_open_positions=10,
            live_trading_enabled=True,
            live_unlock_token="TOK",
            enforce_market_hours_for_krx=False,
        )
    )
    cfg = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=1,
        order_amount=Decimal("10000"),
        auto_fill=False,
        user_broker_account_id=5,
    )
    executor = RiskIntegratedRealtimeOrderExecutor(
        session=session,
        execution_config=cfg,
        safety_guard=guard,
    )
    signal = RealtimeSignal(
        exchange_code="KRX",
        symbol="005930",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("70000"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="TEST",
        generated_at=datetime.now(timezone.utc),
        account_kind="USER_BROKER",
        account_id=5,
        user_id=1,
        scope_key="u1|UBA|5|s",
        broker_code="KIWOOM",
    )

    with patch(
        "stock_platform.realtime.risk_integrated_order_executor.PersistentKillSwitchGuard"
    ) as ks:
        ks.return_value.require_order_allowed.side_effect = PermissionError(
            "KILL"
        )
        result = executor.execute(signal)
    assert result.reason_code == "GLOBAL_KILL_SWITCH_ACTIVE"
    assert result.order_id is None


def test_live_gate_fail_closed_without_unlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "false")
    monkeypatch.setenv("REALTIME_LIVE_UNLOCK_TOKEN", "")
    monkeypatch.setenv("REALTIME_LIVE_USER_BROKER_ACCOUNT_ID", "1")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    gate = live_auto_start_allowed(allow_live=True)
    assert gate["allowed"] is False
    assert gate["reason"] == "LIVE_UNLOCK_TOKEN_MISSING"
    clear_settings_cache()


def test_shadow_block_result_has_no_broker_id() -> None:
    reset_shadow_counters()
    result = shadow_block_dispatch_result(event_type="SUBMIT_ORDER")
    assert result["broker_order_id"] is None
    assert result["accepted"] is False
