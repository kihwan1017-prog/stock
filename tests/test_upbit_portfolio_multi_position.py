"""UPBIT portfolio capital allocator + Top-K dry flow (REAL 주문 없음)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_full_market.capital_allocator import (
    AllocationInput,
    allocate_entry_amount,
)
from stock_platform.operation.upbit_full_market.constants import (
    CONFIRM_ENABLE_PORTFOLIO,
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_AUTO,
    MODE_FULL_MARKET_PORTFOLIO,
    MODE_FULL_MARKET_SINGLE,
    PORTFOLIO_ENTRY_PAUSED,
    SLOT_EMPTY,
    SLOT_ENTRY_PENDING,
    SLOT_OPEN,
    is_full_market_portfolio,
    is_full_market_single,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.operation.upbit_full_market.selection_policy import (
    SelectionPolicy,
    select_best_eligible_candidate,
)


def test_mode_helpers_legacy_and_new() -> None:
    assert is_full_market_single(MODE_FULL_MARKET_AUTO)
    assert is_full_market_single(MODE_FULL_MARKET_SINGLE)
    assert not is_full_market_single(MODE_FULL_MARKET_PORTFOLIO)
    assert is_full_market_portfolio(MODE_FULL_MARKET_PORTFOLIO)
    assert not is_full_market_portfolio(MODE_FULL_MARKET_AUTO)


def test_allocator_account_max_order_clamps() -> None:
    result = allocate_entry_amount(
        AllocationInput(
            portfolio_capital_limit_krw=Decimal("500000"),
            available_krw=Decimal("1000000"),
            min_cash_reserve_pct=0.60,
            per_position_target_pct=0.08,
            max_symbol_exposure_pct=0.12,
            max_total_exposure_pct=0.30,
            current_strategy_exposure_krw=Decimal("0"),
            pending_reserved_krw=Decimal("0"),
            current_symbol_exposure_krw=Decimal("0"),
            account_max_order_amount=Decimal("10000"),
            activation_max_order_amount=Decimal("5100"),
            scanner_score=90,
            ai_confidence=0.9,
            volatility="LOW",
        )
    )
    assert not result.skipped
    assert result.approved_amount_krw == Decimal("5100")
    assert "ACCOUNT_MAX_ORDER" in result.clamp_reasons


def test_allocator_cash_reserve_blocks_below_min() -> None:
    result = allocate_entry_amount(
        AllocationInput(
            portfolio_capital_limit_krw=Decimal("500000"),
            available_krw=Decimal("10000"),
            min_cash_reserve_pct=0.60,
            per_position_target_pct=0.08,
            max_symbol_exposure_pct=0.12,
            max_total_exposure_pct=0.30,
            current_strategy_exposure_krw=Decimal("0"),
            pending_reserved_krw=Decimal("0"),
            current_symbol_exposure_krw=Decimal("0"),
            account_max_order_amount=Decimal("100000"),
            scanner_score=80,
            ai_confidence=0.8,
            volatility="MEDIUM",
        )
    )
    # spendable = 10000*0.4 = 4000 < min 5000 → SKIP
    assert result.skipped
    assert result.skip_reason == "BELOW_MIN_NOTIONAL"


def test_allocator_total_exposure_clamp() -> None:
    result = allocate_entry_amount(
        AllocationInput(
            portfolio_capital_limit_krw=Decimal("100000"),
            available_krw=Decimal("1000000"),
            min_cash_reserve_pct=0.10,
            per_position_target_pct=0.50,
            max_symbol_exposure_pct=1.0,
            max_total_exposure_pct=0.30,
            current_strategy_exposure_krw=Decimal("25000"),
            pending_reserved_krw=Decimal("0"),
            current_symbol_exposure_krw=Decimal("0"),
            account_max_order_amount=Decimal("100000"),
            scanner_score=50,
            ai_confidence=0.5,
            volatility="MEDIUM",
        )
    )
    # max total 30000 - 25000 = 5000 remaining
    assert not result.skipped
    assert result.approved_amount_krw == Decimal("5000")
    assert "TOTAL_EXPOSURE_LIMIT" in result.clamp_reasons


def test_topk_skips_hold_picks_allow() -> None:
    now = datetime.now(timezone.utc)
    candidates = [
        {
            "symbol": "KRW-CAP",
            "rank": 1,
            "score": 99,
            "recommendation": "HOLD",
            "confidence": 0.99,
            "market_data_timestamp": now.isoformat(),
        },
        {
            "symbol": "KRW-ETH",
            "rank": 2,
            "score": 88,
            "recommendation": "ALLOW",
            "confidence": 0.86,
            "market_data_timestamp": now.isoformat(),
        },
        {
            "symbol": "KRW-BTC",
            "rank": 3,
            "score": 85,
            "recommendation": "ALLOW",
            "confidence": 0.84,
            "market_data_timestamp": now.isoformat(),
        },
    ]
    decision = select_best_eligible_candidate(
        candidates,
        SelectionPolicy(min_score=0, min_confidence=0, ai_live_gate_mode="ENFORCE"),
        scanner_run_id="t1",
        now=now,
    )
    assert decision.selected is not None
    assert decision.selected.symbol == "KRW-ETH"


def _policy_entity(**kwargs):
    base = dict(
        policy_id=1,
        user_broker_account_id=9999,
        enabled=True,
        max_positions=3,
        portfolio_capital_limit_krw=500000.0,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=0.12,
        max_total_exposure_pct=0.30,
        min_cash_reserve_pct=0.60,
        daily_loss_limit_pct=0.02,
        consecutive_loss_limit=3,
        allow_averaging_down=False,
        allow_duplicate_symbol=False,
        entry_cooldown_seconds=300,
        candidate_max_age_seconds=1800,
        portfolio_max_pending_entries=1,
        portfolio_daily_entry_limit=10,
        entry_state="RUNNING",
        consecutive_loss_count=0,
        version=1,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _slot(slot_no: int, status: str = SLOT_EMPTY, **kwargs):
    base = dict(
        slot_id=slot_no,
        user_broker_account_id=9999,
        strategy_id=1,
        deployment_id=1,
        slot_no=slot_no,
        status=status,
        symbol=None,
        candidate_selection_id=None,
        scanner_run_id=None,
        ai_analysis_id=None,
        recommended_amount_krw=None,
        allocated_amount_krw=None,
        reserved_amount_krw=None,
        clamp_reasons=[],
        entry_order_id=None,
        position_binding_id=None,
        opened_at=None,
        closed_at=None,
        cooldown_until=None,
        version=1,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_consume_top_k_dry_sequential_pending() -> None:
    session = MagicMock()
    assignment = SimpleNamespace(
        mode=MODE_FULL_MARKET_PORTFOLIO,
        strategy_id=1,
        deployment_id=1,
        template_symbol="KRW-XRP",
        current_symbol=None,
        last_scanner_run_id=None,
        policy_json={},
        ai_live_gate_mode="ENFORCE",
    )
    policy = _policy_entity()
    slots = [_slot(1), _slot(2), _slot(3)]

    def scalar_side_effect(stmt):  # noqa: ANN001
        text = str(stmt)
        if "upbit_full_market_assignment" in text or "UpbitFullMarketAssignment" in text:
            return assignment
        if "upbit_portfolio_policy" in text or "UpbitPortfolioPolicy" in text:
            return policy
        return None

    session.scalar.side_effect = scalar_side_effect

    # scalars: ensure_slots / empty / active / pending counts etc.
    call_n = {"i": 0}

    def scalars_side_effect(stmt):  # noqa: ANN001
        call_n["i"] += 1
        # pending entry count → empty list first
        # open slot count
        # reserved
        # strategy exposure
        # cooldown
        # ensure existing slots
        # empty with_for_update
        return iter(list(slots))

    session.scalars.side_effect = scalars_side_effect

    svc = UpbitPortfolioService(session)
    svc._assignment.get_or_create = MagicMock(return_value=assignment)  # type: ignore[method-assign]
    svc._assignment._has_preexisting_holding = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc.tick_cooldown_slots = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.ensure_slots = MagicMock(return_value=slots)  # type: ignore[method-assign]
    svc.pending_entry_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.active_symbols = MagicMock(return_value=[])  # type: ignore[method-assign]
    svc.strategy_exposure_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]
    svc.reserved_amount_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]
    svc.get_or_create_policy = MagicMock(return_value=policy)  # type: ignore[method-assign]

    # empty slots query
    session.scalars.side_effect = lambda stmt: iter([slots[0], slots[1], slots[2]])

    now = datetime.now(timezone.utc)
    candidates = [
        {"symbol": "KRW-CAP", "rank": 1, "score": 99, "recommendation": "HOLD", "confidence": 0.9, "market_data_timestamp": now.isoformat()},
        {"symbol": "KRW-ETH", "rank": 2, "score": 88, "recommendation": "ALLOW", "confidence": 0.86, "market_data_timestamp": now.isoformat(), "volatility": "MEDIUM"},
        {"symbol": "KRW-BTC", "rank": 3, "score": 85, "recommendation": "ALLOW", "confidence": 0.84, "market_data_timestamp": now.isoformat()},
        {"symbol": "KRW-SOL", "rank": 4, "score": 80, "recommendation": "ALLOW", "confidence": 0.8, "market_data_timestamp": now.isoformat()},
    ]
    out = svc.consume_top_k(
        9999,
        candidates=candidates,
        scanner_run_id="dry-e2e",
        available_krw=Decimal("500000"),
        account_max_order_amount=Decimal("10000"),
        dry_run=True,
    )
    assert out["ok"] is True
    assert out["orders_created"] == 0
    assert out["reserved"]
    assert out["reserved"][0]["symbol"] == "KRW-ETH"
    assert out["reserved"][0]["approved_amount_krw"] <= 10000


def test_enable_portfolio_requires_confirm() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="UPBIT")
    svc = UpbitPortfolioService(session)
    bad = svc.enable_portfolio(9999, confirmation_text="x", actor="t")
    assert bad["ok"] is False
    assert bad["error"] == "CONFIRMATION_MISMATCH"


def test_consecutive_loss_pauses_entry() -> None:
    session = MagicMock()
    policy = _policy_entity(consecutive_loss_count=2, consecutive_loss_limit=3)
    svc = UpbitPortfolioService(session)
    svc.get_or_create_policy = MagicMock(return_value=policy)  # type: ignore[method-assign]
    out = svc.record_completed_trade_pnl(9999, pnl_krw=-1000)
    assert out["entry_state"] == PORTFOLIO_ENTRY_PAUSED
    assert policy.consecutive_loss_count == 3


def test_fixed_and_single_mode_constants_stable() -> None:
    assert MODE_FIXED_SYMBOL == "FIXED_SYMBOL"
    assert MODE_FULL_MARKET_AUTO == "FULL_MARKET_AUTO"
    assert MODE_FULL_MARKET_SINGLE == "FULL_MARKET_SINGLE"
    assert CONFIRM_ENABLE_PORTFOLIO.startswith("전체시장")
