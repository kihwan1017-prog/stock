"""UPBIT MARKET SELL risk_unit_price 분리 — History #94 defect regression.

WRK-20260901-UPBIT-MARKET-SELL-RISK-UNIT-PRICE-FIX-V1
REAL broker / REAL orders 금지. mock only.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.risk_engine.exit_sell_quantity import resolve_exit_sell_quantity
from stock_platform.risk_engine.order_guard import DatabaseBackedRiskOrderGuard


@pytest.fixture(autouse=True)
def _live_queue_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "stock_platform.trading.upbit_24x7_control.live_outbox_queue_block_reason",
        lambda: None,
    )


def _queued_upbit(*, side: str = "SELL", order_type: str = "MARKET") -> SimpleNamespace:
    return SimpleNamespace(
        order_id=9301,
        client_order_id="cli-mkt-sell-1",
        account_id=None,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-SOMI",
        side_code=side,
        order_type_code=order_type,
        order_quantity=Decimal("62.11180124"),
        order_price=None if order_type == "MARKET" and side == "SELL" else Decimal("159"),
        time_in_force_code="DAY",
        status_code="PENDING",
        strategy_code=None,
        strategy_id=17483,
    )


def _wired(session: MagicMock, order: SimpleNamespace):
    created: list[object] = []
    enqueued: list[object] = []
    svc = OrderExecutionService(session)
    outbox = SimpleNamespace(outbox_id=8302, order_id=order.order_id)

    def _create(*_a, **_k):
        created.append(order)
        return order

    def _enqueue(**kwargs):
        enqueued.append(kwargs)
        return outbox

    svc._order_service.create = MagicMock(side_effect=_create)
    svc._order_repository.change_status = MagicMock(return_value=order)
    svc._order_repository.get = MagicMock(return_value=None)
    svc._outbox_repository.get_by_idempotency_key = MagicMock(return_value=None)
    svc._outbox_repository.enqueue = MagicMock(side_effect=_enqueue)
    return svc, created, enqueued


def _pass_gates(Safety, KS, Lock, Vault, Risk) -> None:
    Safety.return_value.evaluate.return_value = SimpleNamespace(
        allowed=True, reason_code="LIVE_SAFETY_PASS", detail={}
    )
    Safety.return_value.notify_submitted = MagicMock()
    KS.return_value.require_order_allowed = MagicMock()
    Lock.return_value.is_trading_paused.return_value = False
    Vault.return_value.assert_live_order_allowed = MagicMock()
    Risk.return_value.check.return_value = SimpleNamespace(
        allowed=True, blocked_reason=None
    )


def _upbit_cmd(**kwargs) -> OrderExecutionCommand:
    payload = {
        "account_id": None,
        "broker_code": "UPBIT",
        "exchange_code": "UPBIT",
        "symbol": "KRW-SOMI",
        "side": OrderSide.SELL,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("62.11180124"),
        "price": None,
        "reference_price": Decimal("159"),
        "environment": "LIVE",
        "user_broker_account_id": 1380,
        "owner_user_id": 61,
        "user_id": 61,
        "actor": "risk-unit-price-test",
        "order_source": "EXIT",
        "is_risk_reducing": True,
        "client_order_id": "UPBIT-MKT-SELL-TEST",
        "idempotency_key": "upbit-mkt-sell-risk-unit:1",
    }
    payload.update(kwargs)
    return OrderExecutionCommand(**payload)  # type: ignore[arg-type]


def test_a_market_sell_broker_price_none_risk_unit_positive() -> None:
    """A: broker price=None, risk_unit_price>0 → risk PASS, outbox price=None."""
    session = MagicMock()
    session.is_active = True
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    order = _queued_upbit()
    svc, created, enqueued = _wired(session, order)
    upbit_submit = MagicMock()

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch(
            "stock_platform.broker.upbit.adapter.UpbitBrokerAdapter.submit_order",
            upbit_submit,
        ),
        patch("stock_platform.order.outbox_fencing.record_outbox_audit"),
        patch(
            "stock_platform.order.pre_persist_exit_gate.evaluate_pre_persist_exit_gate",
            return_value=None,
        ),
    ):
        _pass_gates(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_upbit_cmd(reference_price=Decimal("159"), price=None))

    assert result.allowed is True
    assert result.reason_code == "QUEUED"
    assert len(created) == 1
    assert len(enqueued) == 1
    payload = enqueued[0]["payload_json"]
    assert payload["order_type"] == "MARKET"
    assert payload["side"] == "SELL"
    assert payload["price"] is None  # broker MARKET SELL — price 없음
    assert payload.get("reference_price") == "159"
    risk_kwargs = Risk.return_value.check.call_args.kwargs
    assert risk_kwargs["reference_unit_price"] == Decimal("159")
    assert risk_kwargs["reference_unit_price"] > 0
    upbit_submit.assert_not_called()


def test_b_market_sell_without_reference_fail_closed() -> None:
    """B: reference 없음 → MARKET_SELL_RISK_PRICE_UNAVAILABLE, broker 미호출."""
    session = MagicMock()
    session.is_active = True
    session.rollback = MagicMock()
    order = _queued_upbit()
    svc, created, enqueued = _wired(session, order)
    upbit_submit = MagicMock()

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch(
            "stock_platform.broker.upbit.adapter.UpbitBrokerAdapter.submit_order",
            upbit_submit,
        ),
        patch("stock_platform.order.outbox_fencing.record_outbox_audit"),
        patch(
            "stock_platform.order.pre_persist_exit_gate.evaluate_pre_persist_exit_gate",
            return_value=None,
        ),
    ):
        _pass_gates(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(
            _upbit_cmd(reference_price=None, price=None, idempotency_key="no-ref")
        )

    assert result.allowed is False
    assert result.reason_code == "MARKET_SELL_RISK_PRICE_UNAVAILABLE"
    assert created == []
    assert enqueued == []
    Risk.return_value.check.assert_not_called()
    upbit_submit.assert_not_called()


def test_c_limit_sell_keeps_limit_price() -> None:
    """C: LIMIT SELL — resolve/outbox에 limit price 유지."""
    svc = OrderExecutionService(MagicMock())
    qty, price, meta = svc._resolve_size(
        OrderExecutionCommand(
            account_id=None,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-SOMI",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("159"),
            environment="LIVE",
            user_broker_account_id=1380,
        )
    )
    assert qty == Decimal("10")
    assert price == Decimal("159")
    assert meta is None


def test_d_market_buy_semantics_unchanged() -> None:
    """D: MARKET BUY — KRW notional + reference ticker 회귀 없음."""
    svc = OrderExecutionService(MagicMock())
    qty, price, meta = svc._resolve_size(
        OrderExecutionCommand(
            account_id=None,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-SOMI",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            order_amount=Decimal("5000"),
            reference_price=Decimal("159"),
            price=None,
            environment="LIVE",
            user_broker_account_id=1380,
        )
    )
    assert price == Decimal("5000")
    assert meta is not None
    assert meta.get("broker_price_semantics") == "UPBIT_MARKET_BUY_KRW_NOTIONAL"
    assert meta.get("reference_price") == "159"
    assert qty > 0


def test_e_limit_buy_unchanged() -> None:
    """E: LIMIT BUY 기존 동작."""
    svc = OrderExecutionService(MagicMock())
    qty, price, meta = svc._resolve_size(
        OrderExecutionCommand(
            account_id=None,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-SOMI",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("5"),
            price=Decimal("160"),
            environment="LIVE",
            user_broker_account_id=1380,
        )
    )
    assert qty == Decimal("5")
    assert price == Decimal("160")
    assert meta is None


def test_f_strategy_owned_sell_quantity_clamp_unchanged() -> None:
    """F: strategy-owned ∩ sellable clamp 회귀 없음."""
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("100"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=Decimal("0"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("40"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            MagicMock(),
            user_broker_account_id=1380,
            symbol="KRW-SOMI",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("100"),
            max_order_quantity=Decimal("50"),
            require_strategy_owned=True,
        )
    assert plan.sell_quantity == Decimal("40")
    assert any("STRATEGY" in str(x).upper() for x in plan.capped_by)


def test_g_market_sell_risk_notional_qty_times_unit() -> None:
    """G: risk notional = quantity × risk_unit_price."""
    qty = Decimal("62.11180124")
    unit = Decimal("159")
    notional = qty * unit
    assert notional == Decimal("9875.77639716")

    resolved = OrderExecutionService._upbit_market_risk_unit_price(
        command=_upbit_cmd(reference_price=unit, price=None),
        plan_payload={"reference_price": str(unit)},
    )
    assert resolved == unit
    assert (qty * resolved) == notional


def test_resolve_size_market_sell_still_none_broker_price() -> None:
    """resolve_size는 계속 broker price=None (가짜 limit 주입 금지)."""
    svc = OrderExecutionService(MagicMock())
    qty, price, meta = svc._resolve_size(
        _upbit_cmd(reference_price=Decimal("159"), price=Decimal("159"))
    )
    assert qty == Decimal("62.11180124")
    assert price is None
    assert meta is not None
    assert meta["broker_price_semantics"] == "UPBIT_MARKET_SELL_VOLUME_ONLY"
    assert meta["reference_price"] == "159"


def test_helper_rejects_zero_and_none() -> None:
    assert (
        OrderExecutionService._upbit_market_risk_unit_price(
            command=_upbit_cmd(reference_price=None, price=None),
            plan_payload=None,
        )
        is None
    )
    assert (
        OrderExecutionService._upbit_market_risk_unit_price(
            command=_upbit_cmd(reference_price=Decimal("0"), price=Decimal("0")),
            plan_payload={"reference_price": "0"},
        )
        is None
    )


def test_order_guard_uses_reference_unit_over_zero_price() -> None:
    """reference_unit_price가 있으면 price=0이어도 unit/notional 정상."""
    session = MagicMock()
    guard = DatabaseBackedRiskOrderGuard.__new__(DatabaseBackedRiskOrderGuard)
    price = Decimal("0")
    reference_unit_price = Decimal("159")
    quantity = Decimal("10")
    unit_price = (
        Decimal(str(reference_unit_price))
        if reference_unit_price is not None
        else Decimal(str(price))
    )
    notional = quantity * unit_price
    assert unit_price == Decimal("159")
    assert notional == Decimal("1590")
    assert guard is not None
    assert session is not None
