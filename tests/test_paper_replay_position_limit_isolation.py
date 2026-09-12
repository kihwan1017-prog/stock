"""PAPER replay 심볼 포지션 한도 — 0 포지션 + 과대 명목 BUY 재현 및 격리.

실 DB/Broker/LIVE 경로 없음. fixture + 규칙 단위만.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.risk_engine.account_state_service import RiskAccountStateService
from stock_platform.risk_engine.engine import RealtimeRiskEngine
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)
from stock_platform.risk_engine.position_limit_models import PositionLimitPolicy
from stock_platform.risk_engine.position_limit_rule import DatabasePositionLimitRule
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver
from stock_platform.risk_engine.rules import (
    AvailableCashRule,
    DuplicateBuyRule,
    MaximumOrderAmountRule,
    SellQuantityRule,
)
from stock_platform.trading.failure_code_normalize import classify_risk_blocked_reason
from stock_platform.trading.paper_historical_replay import (
    _paper_replay_buy_budget_cap,
    _size_buy_quantity,
)


ZERO = Decimal("0")
SYSTEM_MAX_ORDER = Decimal("100000")
SYSTEM_MAX_SYMBOL_AMOUNT = Decimal("1000000")
PAPER_CASH = Decimal("10000000")
SOL_PRICE = Decimal("32880")


def _buy_order(
    *,
    quantity: Decimal,
    price: Decimal = SOL_PRICE,
    account_id: int = 5252,
) -> RiskOrderRequest:
    return RiskOrderRequest(
        exchange_code="PAPER",
        symbol="KRW-SOL",
        side=RiskOrderSide.BUY,
        quantity=quantity,
        price=price,
        requested_at=datetime.now(timezone.utc),
        account_id=account_id,
        environment="PAPER",
    )


def _sell_order(
    *,
    quantity: Decimal,
    price: Decimal = SOL_PRICE,
    account_id: int = 5252,
) -> RiskOrderRequest:
    return RiskOrderRequest(
        exchange_code="PAPER",
        symbol="KRW-SOL",
        side=RiskOrderSide.SELL,
        quantity=quantity,
        price=price,
        requested_at=datetime.now(timezone.utc),
        account_id=account_id,
        environment="PAPER",
    )


def _paper_account(
    *,
    cash: Decimal = PAPER_CASH,
    open_count: int = 0,
    symbol_qty: Decimal = ZERO,
    invested: Decimal = ZERO,
    pending_sell: Decimal = ZERO,
) -> RiskAccountState:
    return RiskAccountState(
        cash_balance=cash,
        total_asset_value=cash + invested,
        invested_amount=invested,
        daily_realized_profit_loss=ZERO,
        daily_unrealized_profit_loss=ZERO,
        open_position_count=open_count,
        symbol_position_quantity=symbol_qty,
        symbol_pending_sell_quantity=pending_sell,
    )


def _position_rule() -> DatabasePositionLimitRule:
    rule = DatabasePositionLimitRule(
        MagicMock(),
        broker_code="PAPER",
        paper_account_id=5252,
        default_policy=PositionLimitPolicy(
            max_symbol_quantity=Decimal("100"),
            max_symbol_amount=SYSTEM_MAX_SYMBOL_AMOUNT,
            max_symbol_weight=Decimal("0.20"),
        ),
    )
    rule._repository.get_by_paper = lambda **_kwargs: None  # noqa: ARG005
    rule._repository.get_by_uba = lambda **_kwargs: None  # noqa: ARG005
    return rule


def test_zero_position_oversized_buy_is_symbol_amount_limit() -> None:
    """재현: 포지션 0인데 cash*0.20=2M BUY → RISK_SYMBOL_POSITION_LIMIT_EXCEEDED."""

    qty, gross = _size_buy_quantity(
        available_cash=PAPER_CASH,
        price=SOL_PRICE,
        position_ratio=Decimal("0.20"),
        max_order_amount=None,
        exchange_code="UPBIT",
    )
    assert gross > SYSTEM_MAX_SYMBOL_AMOUNT
    result = _position_rule().evaluate(
        order=_buy_order(quantity=qty, price=SOL_PRICE),
        account=_paper_account(),
    )
    assert result.level == RiskDecisionLevel.BLOCK
    assert "amount" in result.message.lower()
    assert result.detail["projected_quantity"] == str(qty)
    assert Decimal(result.detail["projected_amount"]) > SYSTEM_MAX_SYMBOL_AMOUNT
    code, _details, _summary = classify_risk_blocked_reason(result.message)
    assert code == "RISK_SYMBOL_POSITION_LIMIT_EXCEEDED"


def test_capped_buy_with_zero_position_is_not_symbol_limit() -> None:
    qty, gross = _size_buy_quantity(
        available_cash=PAPER_CASH,
        price=SOL_PRICE,
        position_ratio=Decimal("0.20"),
        max_order_amount=SYSTEM_MAX_ORDER,
        exchange_code="UPBIT",
    )
    assert gross <= SYSTEM_MAX_ORDER
    result = _position_rule().evaluate(
        order=_buy_order(quantity=qty, price=SOL_PRICE),
        account=_paper_account(),
    )
    assert result.level == RiskDecisionLevel.PASS
    code, _details, _summary = classify_risk_blocked_reason(result.message)
    assert code != "RISK_SYMBOL_POSITION_LIMIT_EXCEEDED"


def test_symbol_amount_limit_still_blocks_after_fill() -> None:
    """한도에 도달한 뒤 추가 BUY는 계속 BLOCK."""

    held_qty = Decimal("30")
    held_amount = held_qty * SOL_PRICE  # ≈ 986,400
    extra_qty = Decimal("1")
    result = _position_rule().evaluate(
        order=_buy_order(quantity=extra_qty, price=SOL_PRICE),
        account=_paper_account(
            open_count=1,
            symbol_qty=held_qty,
            invested=held_amount,
            cash=PAPER_CASH - held_amount,
        ),
    )
    assert held_amount + extra_qty * SOL_PRICE > SYSTEM_MAX_SYMBOL_AMOUNT
    assert result.level == RiskDecisionLevel.BLOCK
    code, _details, _summary = classify_risk_blocked_reason(result.message)
    assert code == "RISK_SYMBOL_POSITION_LIMIT_EXCEEDED"


def test_paper_buy_cap_resolves_without_uba(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_resolve(self, *, user_id=None, user_broker_account_id=None):
        captured["user_id"] = user_id
        captured["uba"] = user_broker_account_id
        return SimpleNamespace(
            max_order_amount=SYSTEM_MAX_ORDER,
            max_position_amount=SYSTEM_MAX_SYMBOL_AMOUNT,
            max_total_investment_amount=SYSTEM_MAX_SYMBOL_AMOUNT,
            daily_max_order_amount=Decimal("1000000"),
        )

    monkeypatch.setattr(ResolvedRiskPolicyResolver, "resolve", fake_resolve)
    cap = _paper_replay_buy_budget_cap(
        MagicMock(),
        owner_user_id=61,
        strategy_max_order_amount=None,
    )
    assert captured["user_id"] == 61
    assert captured["uba"] is None
    assert cap == SYSTEM_MAX_ORDER
    tighter = _paper_replay_buy_budget_cap(
        MagicMock(),
        owner_user_id=61,
        strategy_max_order_amount=Decimal("50000"),
    )
    assert tighter == Decimal("50000")


def test_paper_loader_does_not_read_live_uba_positions(monkeypatch) -> None:
    uba_calls: list[int] = []

    class FakeBrokerRepo:
        def __init__(self, session) -> None:
            _ = session

        def get_active_by_uba(self, uba_id):
            uba_calls.append(int(uba_id))
            raise AssertionError("PAPER must not load UBA1380 positions")

    paper = SimpleNamespace(
        available_cash=PAPER_CASH,
        realized_profit_loss=ZERO,
    )
    session = MagicMock()
    session.get.return_value = paper
    session.scalars.return_value = []
    monkeypatch.setattr(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository",
        FakeBrokerRepo,
    )
    state = RiskAccountStateService(session).load_by_paper_account(
        paper_account_id=5252,
        exchange_code="PAPER",
        symbol="KRW-SOL",
    )
    assert uba_calls == []
    assert state.open_position_count == 0
    assert state.symbol_position_quantity == ZERO
    assert state.cash_balance == PAPER_CASH


def test_live_uba_loader_does_not_read_paper_positions(monkeypatch) -> None:
    paper_gets: list[object] = []

    class FakeRepo:
        def __init__(self, session) -> None:
            _ = session

        def get_active_by_uba(self, uba_id):
            assert uba_id == 1380
            account = SimpleNamespace(
                deposit_amount=Decimal("1000000"),
                available_order_amount=Decimal("164127"),
                total_profit_loss=ZERO,
                user_broker_account_id=1380,
            )
            positions = [
                SimpleNamespace(
                    exchange_code="UPBIT",
                    symbol=symbol,
                    quantity=Decimal("1"),
                    evaluation_amount=Decimal("10000"),
                    profit_loss=ZERO,
                )
                for symbol in ("KRW-BTC", "KRW-ETH", "KRW-DOGE", "KRW-SKY", "KRW-XRP")
            ]
            return account, positions

    class FakeDaily:
        def __init__(self, session) -> None:
            _ = session

        def diagnose(self, *, user_broker_account_id, loss_limit):
            _ = user_broker_account_id, loss_limit
            return SimpleNamespace(
                current_daily_pnl=ZERO,
                realized_pnl=ZERO,
                unrealized_pnl=ZERO,
            )

    session = MagicMock()

    def _get(model, _pk):
        paper_gets.append(model)
        raise AssertionError("LIVE UBA must not load PaperAccount")

    session.get.side_effect = _get
    monkeypatch.setattr(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository",
        FakeRepo,
    )
    monkeypatch.setattr(
        "stock_platform.risk_engine.uba_daily_loss_service.UbaDailyLossService",
        FakeDaily,
    )
    state = RiskAccountStateService(session).load_by_uba(
        user_broker_account_id=1380,
        exchange_code="UPBIT",
        symbol="KRW-SOL",
    )
    assert paper_gets == []
    assert state.open_position_count == 5
    assert state.symbol_position_quantity == ZERO


def test_cash_insufficient_still_blocks() -> None:
    result = AvailableCashRule().evaluate(
        order=_buy_order(quantity=Decimal("1"), price=Decimal("200000")),
        account=_paper_account(cash=Decimal("100000")),
        policy=RiskPolicy(),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_max_order_amount_still_blocks() -> None:
    result = MaximumOrderAmountRule().evaluate(
        order=_buy_order(quantity=Decimal("10"), price=Decimal("20000")),
        account=_paper_account(),
        policy=RiskPolicy(max_order_amount=SYSTEM_MAX_ORDER),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_oversell_still_blocks() -> None:
    result = SellQuantityRule().evaluate(
        order=_sell_order(quantity=Decimal("2")),
        account=_paper_account(symbol_qty=Decimal("1"), open_count=1),
        policy=RiskPolicy(),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_duplicate_buy_still_blocks_when_disallowed() -> None:
    result = DuplicateBuyRule().evaluate(
        order=_buy_order(quantity=Decimal("1")),
        account=_paper_account(symbol_qty=Decimal("1"), open_count=1),
        policy=RiskPolicy(allow_duplicate_buy=False),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_pending_sell_reduces_sellable() -> None:
    result = SellQuantityRule().evaluate(
        order=_sell_order(quantity=Decimal("1")),
        account=_paper_account(
            symbol_qty=Decimal("1"),
            pending_sell=Decimal("1"),
            open_count=1,
        ),
        policy=RiskPolicy(),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_negative_quantity_rejected() -> None:
    engine = RealtimeRiskEngine()
    with pytest.raises(ValueError, match="quantity"):
        engine.evaluate(
            order=_buy_order(quantity=Decimal("-1")),
            account=_paper_account(),
            policy=RiskPolicy(),
        )
