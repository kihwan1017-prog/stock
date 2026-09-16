"""Portfolio sizing ↔ ResolvedRiskPolicy max_order_amount 정렬 (REAL 주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.operation.upbit_full_market.capital_allocator import (
    AllocationInput,
    allocate_entry_amount,
)
from stock_platform.operation.upbit_full_market.constants import (
    SLOT_ENTRY_PENDING,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.portfolio_entry_sizing import (
    PortfolioEntryRiskLimits,
    allocate_portfolio_entry_amount,
    build_sizing_telemetry,
    effective_max_order_cap,
    portfolio_sizing_readiness_hint,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy


def _risk_limits(max_order: str, *, layers: tuple[str, ...] = ("uba",)) -> PortfolioEntryRiskLimits:
    return PortfolioEntryRiskLimits(
        max_order_amount=Decimal(max_order),
        max_position_amount=Decimal("1000000"),
        source_layers=layers,
    )


def _base_input(**overrides) -> AllocationInput:
    base = dict(
        portfolio_capital_limit_krw=Decimal("500000"),
        available_krw=Decimal("1000000"),
        min_cash_reserve_pct=0.10,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=1.0,
        max_total_exposure_pct=1.0,
        current_strategy_exposure_krw=Decimal("0"),
        pending_reserved_krw=Decimal("0"),
        current_symbol_exposure_krw=Decimal("0"),
        account_max_order_amount=Decimal("100000"),
        scanner_score=90.0,
        ai_confidence=0.9,
        volatility="LOW",
    )
    base.update(overrides)
    return AllocationInput(**base)


def test_portfolio_25k_risk_10k_clamps_to_10k() -> None:
    """portfolio desired ~25k, risk max 10k → executable 10k."""

    limits = _risk_limits("10000")
    alloc = allocate_portfolio_entry_amount(
        _base_input(per_position_target_pct=0.05),
        risk_limits=limits,
    )
    assert not alloc.skipped
    assert alloc.recommended_amount_krw > Decimal("10000")
    assert alloc.approved_amount_krw == Decimal("10000")
    assert "ACCOUNT_MAX_ORDER" in alloc.clamp_reasons
    telemetry = build_sizing_telemetry(
        alloc,
        risk_limits=limits,
        effective_cap=effective_max_order_cap(limits),
    )
    assert telemetry["final_order_amount_krw"] == 10000.0
    assert "MAX_ORDER_AMOUNT" in telemetry["clamped_by"]


def test_portfolio_8k_risk_10k_keeps_8k() -> None:
    limits = _risk_limits("10000")
    alloc = allocate_portfolio_entry_amount(
        _base_input(
            per_position_target_pct=0.016,
            scanner_score=50,
            ai_confidence=0.5,
            volatility="MEDIUM",
        ),
        risk_limits=limits,
    )
    assert not alloc.skipped
    assert alloc.approved_amount_krw <= Decimal("10000")
    assert alloc.approved_amount_krw >= Decimal("5000")
    assert alloc.approved_amount_krw == alloc.recommended_amount_krw


def test_portfolio_25k_risk_5k_broker_min_5k_pass() -> None:
    limits = _risk_limits("5000")
    alloc = allocate_portfolio_entry_amount(
        _base_input(per_position_target_pct=0.05),
        risk_limits=limits,
    )
    assert not alloc.skipped
    assert alloc.approved_amount_krw == Decimal("5000")


def test_effective_max_below_broker_min_blocks() -> None:
    limits = _risk_limits("3000")
    alloc = allocate_portfolio_entry_amount(
        _base_input(),
        risk_limits=limits,
    )
    assert alloc.skipped
    assert alloc.skip_reason == "BELOW_MIN_NOTIONAL"


def test_system_default_risk_cap_allows_large_desired() -> None:
    """Risk max가 system default(100k)면 portfolio desired 그대로."""

    limits = _risk_limits("100000", layers=("system",))
    alloc = allocate_portfolio_entry_amount(
        _base_input(per_position_target_pct=0.05),
        risk_limits=limits,
    )
    assert not alloc.skipped
    assert alloc.approved_amount_krw == alloc.recommended_amount_krw
    assert alloc.approved_amount_krw > Decimal("10000")


def test_cash_limit_below_risk_max() -> None:
    limits = _risk_limits("10000")
    alloc = allocate_portfolio_entry_amount(
        _base_input(
            available_krw=Decimal("15000"),
            min_cash_reserve_pct=0.60,
            per_position_target_pct=0.20,
        ),
        risk_limits=limits,
    )
    assert not alloc.skipped
    assert alloc.approved_amount_krw < Decimal("10000")
    assert alloc.approved_amount_krw >= UPBIT_MIN_NOTIONAL_KRW
    assert "CASH_RESERVE_OR_PENDING" in alloc.clamp_reasons


def test_exposure_limit_below_risk_max() -> None:
    limits = _risk_limits("10000")
    alloc = allocate_portfolio_entry_amount(
        _base_input(
            max_total_exposure_pct=0.01,
            portfolio_capital_limit_krw=Decimal("500000"),
        ),
        risk_limits=limits,
    )
    assert not alloc.skipped
    assert alloc.approved_amount_krw <= Decimal("5000")
    assert "TOTAL_EXPOSURE_LIMIT" in alloc.clamp_reasons


def test_effective_max_order_cap_activation_stricter() -> None:
    limits = _risk_limits("10000")
    cap = effective_max_order_cap(
        limits,
        activation_max_order_amount=Decimal("7500"),
    )
    assert cap == Decimal("7500")


def test_portfolio_sizing_readiness_warns_when_max_below_min() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_entry_sizing.resolve_portfolio_entry_risk_limits",
        return_value=_risk_limits("3000"),
    ):
        hint = portfolio_sizing_readiness_hint(session, user_broker_account_id=1380)
    assert hint["ok"] is False
    assert hint["warning"] == "SIZING_NO_EXECUTABLE_AMOUNT"
    assert Decimal(hint["broker_min_notional_krw"]) == UPBIT_MIN_NOTIONAL_KRW


def _slot(**kwargs) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    base = dict(
        slot_id=1,
        slot_no=1,
        status=SLOT_WAITING_SIGNAL,
        symbol="KRW-SUI",
        candidate_selection_id=11,
        scanner_run_id="run",
        reserved_amount_krw=None,
        allocated_amount_krw=None,
        recommended_amount_krw=None,
        clamp_reasons=[],
        entry_order_id=None,
        version=1,
        created_at=now - timedelta(seconds=10),
        updated_at=now - timedelta(seconds=10),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@patch("stock_platform.trading.symbol_ownership.SymbolOwnershipService")
@patch(
    "stock_platform.operation.upbit_full_market.portfolio_service.resolve_portfolio_entry_risk_limits"
)
def test_begin_entry_clamps_to_risk_max_and_reserves(
    mock_resolve_risk,
    mock_ownership_cls,
) -> None:
    mock_resolve_risk.return_value = _risk_limits("10000")
    ownership = MagicMock()
    ownership.entry_gate.return_value = (True, None, SimpleNamespace(owner="FREE", reasons=[]))
    mock_ownership_cls.return_value = ownership

    session = MagicMock()
    slot = _slot(candidate_selection_id=None)
    session.scalar = MagicMock(return_value=slot)
    session.get = MagicMock(return_value=SimpleNamespace(user_id=61))

    svc = UpbitPortfolioService(session)
    svc.pending_entry_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._assignment._has_preexisting_holding = MagicMock(return_value=False)  # type: ignore[method-assign]
    policy = SimpleNamespace(
        enabled=True,
        entry_state="RUNNING",
        portfolio_capital_limit_krw=300000,
        min_cash_reserve_pct=0.6,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=0.12,
        max_total_exposure_pct=0.3,
    )
    svc.get_or_create_policy = MagicMock(return_value=policy)  # type: ignore[method-assign]
    svc.strategy_exposure_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]
    svc.reserved_amount_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]

    out = svc.begin_entry_from_signal(
        1380,
        symbol="KRW-SUI",
        available_krw=Decimal("500000"),
    )
    assert out["ok"] is True
    assert out["status"] == SLOT_ENTRY_PENDING
    assert float(out["final_order_amount_krw"]) == 10000.0
    assert float(out["requested_amount_krw"]) > 10000.0
    assert "MAX_ORDER_AMOUNT" in (out.get("clamped_by") or [])
    assert float(slot.reserved_amount_krw or 0) == 10000.0


def test_begin_entry_max_pending_blocks_concurrent_second_symbol() -> None:
    session = MagicMock()
    svc = UpbitPortfolioService(session)
    svc.pending_entry_count = MagicMock(return_value=1)  # type: ignore[method-assign]
    session.scalar = MagicMock(return_value=None)
    out = svc.begin_entry_from_signal(1380, symbol="KRW-AVAX")
    assert out["ok"] is False
    assert out["reason"] == "PENDING_ENTRY_LIMIT"


@patch("stock_platform.trading.symbol_ownership.SymbolOwnershipService")
@patch(
    "stock_platform.operation.upbit_full_market.portfolio_service.resolve_portfolio_entry_risk_limits"
)
def test_begin_entry_ignores_legacy_100k_executor_cap(
    mock_resolve_risk,
    mock_ownership_cls,
) -> None:
    """execution_config.order_amount(100k) legacy cap은 Risk보다 높으면 무시."""

    mock_resolve_risk.return_value = _risk_limits("10000")
    ownership = MagicMock()
    ownership.entry_gate.return_value = (True, None, SimpleNamespace(owner="FREE", reasons=[]))
    mock_ownership_cls.return_value = ownership

    session = MagicMock()
    slot = _slot(symbol="KRW-WLD", candidate_selection_id=None)
    session.scalar = MagicMock(return_value=slot)
    session.get = MagicMock(return_value=SimpleNamespace(user_id=61))
    svc = UpbitPortfolioService(session)
    svc.pending_entry_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._assignment._has_preexisting_holding = MagicMock(return_value=False)  # type: ignore[method-assign]
    policy = SimpleNamespace(
        enabled=True,
        entry_state="RUNNING",
        portfolio_capital_limit_krw=300000,
        min_cash_reserve_pct=0.6,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=0.12,
        max_total_exposure_pct=0.3,
    )
    svc.get_or_create_policy = MagicMock(return_value=policy)  # type: ignore[method-assign]
    svc.strategy_exposure_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]
    svc.reserved_amount_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]

    out = svc.begin_entry_from_signal(
        1380,
        symbol="KRW-WLD",
        available_krw=Decimal("500000"),
        account_max_order_amount=Decimal("100000"),
    )
    assert out["ok"] is True
    assert float(out["final_order_amount_krw"]) == 10000.0


def test_resolved_policy_layers_used_by_resolver_contract() -> None:
    """UBA overlay가 system보다 엄격하면 effective cap이 UBA 값."""

    policy = ResolvedRiskPolicy(
        max_order_amount=Decimal("10000"),
        daily_max_order_amount=Decimal("1000000"),
        max_total_investment_amount=Decimal("5000000"),
        max_position_amount=Decimal("1000000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        max_investment_ratio=Decimal("0.5"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("100000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=None,
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("1000000"),
        daily_order_limit=100,
        duplicate_order_window_seconds=60,
        max_open_orders=1,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=3600,
        source_layers=("system", "user_broker_account"),
    )
    limits = PortfolioEntryRiskLimits(
        max_order_amount=policy.max_order_amount,
        max_position_amount=policy.max_position_amount,
        source_layers=policy.source_layers,
    )
    assert limits.max_order_amount == Decimal("10000")
    assert "user_broker_account" in limits.source_layers


def test_kiwoom_allocator_still_clamps_with_shared_cap_field() -> None:
    """KIWOOM/Paper 공통 allocator — account_max_order_amount clamp 유지."""

    result = allocate_entry_amount(
        _base_input(
            account_max_order_amount=Decimal("10000"),
            per_position_target_pct=0.10,
        )
    )
    assert not result.skipped
    assert result.approved_amount_krw == Decimal("10000")
