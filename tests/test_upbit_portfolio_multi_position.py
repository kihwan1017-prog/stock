"""UPBIT portfolio capital allocator + Top-K dry flow (REAL 주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_full_market.capital_allocator import (
    AllocationInput,
    allocate_entry_amount,
    quality_multiplier,
)
from stock_platform.operation.upbit_full_market.constants import (
    CONFIRM_ENABLE_PORTFOLIO,
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_AUTO,
    MODE_FULL_MARKET_PORTFOLIO,
    MODE_FULL_MARKET_SINGLE,
    PORTFOLIO_ENTRY_PAUSED,
    SLOT_COOLDOWN,
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


def test_mode_helpers_fixed_single_portfolio() -> None:
    """FIXED / SINGLE / PORTFOLIO 모드 헬퍼 경계."""

    assert MODE_FIXED_SYMBOL == "FIXED_SYMBOL"
    assert not is_full_market_single(MODE_FIXED_SYMBOL)
    assert not is_full_market_portfolio(MODE_FIXED_SYMBOL)
    assert is_full_market_single(MODE_FULL_MARKET_SINGLE)
    assert is_full_market_portfolio(MODE_FULL_MARKET_PORTFOLIO)


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


def test_allocator_activation_clamp_stricter_than_account() -> None:
    result = allocate_entry_amount(
        AllocationInput(
            portfolio_capital_limit_krw=Decimal("500000"),
            available_krw=Decimal("1000000"),
            min_cash_reserve_pct=0.10,
            per_position_target_pct=0.20,
            max_symbol_exposure_pct=1.0,
            max_total_exposure_pct=1.0,
            current_strategy_exposure_krw=Decimal("0"),
            pending_reserved_krw=Decimal("0"),
            current_symbol_exposure_krw=Decimal("0"),
            account_max_order_amount=Decimal("50000"),
            activation_max_order_amount=Decimal("7500"),
            scanner_score=50,
            ai_confidence=0.5,
            volatility="MEDIUM",
        )
    )
    assert not result.skipped
    assert result.approved_amount_krw == Decimal("7500")
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
    assert "CASH_RESERVE_OR_PENDING" in result.clamp_reasons


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


def test_allocator_symbol_exposure_clamp() -> None:
    result = allocate_entry_amount(
        AllocationInput(
            portfolio_capital_limit_krw=Decimal("100000"),
            available_krw=Decimal("1000000"),
            min_cash_reserve_pct=0.10,
            per_position_target_pct=0.50,
            max_symbol_exposure_pct=0.10,
            max_total_exposure_pct=1.0,
            current_strategy_exposure_krw=Decimal("0"),
            pending_reserved_krw=Decimal("0"),
            current_symbol_exposure_krw=Decimal("2000"),
            account_max_order_amount=Decimal("100000"),
            scanner_score=50,
            ai_confidence=0.5,
            volatility="MEDIUM",
        )
    )
    # max symbol 10000 - 2000 = 8000 remaining (≥ min notional)
    assert not result.skipped
    assert result.approved_amount_krw == Decimal("8000")
    assert "SYMBOL_EXPOSURE_LIMIT" in result.clamp_reasons


def test_quality_multiplier_bounds_0_5_to_1_25() -> None:
    low = quality_multiplier(
        scanner_score=0, ai_confidence=0.0, volatility="HIGH"
    )
    high = quality_multiplier(
        scanner_score=100, ai_confidence=1.0, volatility="LOW"
    )
    assert 0.5 <= low <= 1.25
    assert 0.5 <= high <= 1.25
    # HIGH vol는 LOW보다 작아야 함 (동일 score/conf)
    high_vol = quality_multiplier(
        scanner_score=80, ai_confidence=0.8, volatility="HIGH"
    )
    low_vol = quality_multiplier(
        scanner_score=80, ai_confidence=0.8, volatility="LOW"
    )
    assert high_vol < low_vol


def test_allocator_high_vol_reduces_vs_low() -> None:
    common = dict(
        portfolio_capital_limit_krw=Decimal("500000"),
        available_krw=Decimal("1000000"),
        min_cash_reserve_pct=0.10,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=1.0,
        max_total_exposure_pct=1.0,
        current_strategy_exposure_krw=Decimal("0"),
        pending_reserved_krw=Decimal("0"),
        current_symbol_exposure_krw=Decimal("0"),
        account_max_order_amount=Decimal("1000000"),
        scanner_score=80,
        ai_confidence=0.8,
    )
    low = allocate_entry_amount(AllocationInput(**common, volatility="LOW"))
    high = allocate_entry_amount(AllocationInput(**common, volatility="HIGH"))
    assert not low.skipped and not high.skipped
    assert high.approved_amount_krw < low.approved_amount_krw
    assert high.quality_multiplier < low.quality_multiplier


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
    assert any(
        t.get("symbol") == "KRW-CAP" and t.get("reason") == "AI_HOLD"
        for t in decision.skip_trace
    )


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
        risk_group_policy_json={},
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


def _narrative_candidates(now: datetime) -> list[dict]:
    return [
        {
            "symbol": "KRW-CAP",
            "rank": 1,
            "score": 99,
            "recommendation": "HOLD",
            "confidence": 0.9,
            "market_data_timestamp": now.isoformat(),
        },
        {
            "symbol": "KRW-ETH",
            "rank": 2,
            "score": 88,
            "recommendation": "ALLOW",
            "confidence": 0.86,
            "market_data_timestamp": now.isoformat(),
            "volatility": "MEDIUM",
        },
        {
            "symbol": "KRW-BTC",
            "rank": 3,
            "score": 85,
            "recommendation": "ALLOW",
            "confidence": 0.84,
            "market_data_timestamp": now.isoformat(),
        },
        {
            "symbol": "KRW-SOL",
            "rank": 4,
            "score": 80,
            "recommendation": "ALLOW",
            "confidence": 0.8,
            "market_data_timestamp": now.isoformat(),
        },
        {
            "symbol": "KRW-XRP",
            "rank": 5,
            "score": 78,
            "recommendation": "ALLOW",
            "confidence": 0.79,
            "market_data_timestamp": now.isoformat(),
        },
    ]


def test_full_dry_cycle_narrative_pending1_slot_full_refill() -> None:
    """
    CAP HOLD skip → ETH/BTC/SOL 순차 선택 (pending=1) → 3 OPEN이면 SLOT_FULL
    → ETH exit/cooldown → EMPTY → XRP refill 자격.
    순수 selector + slot 상태머신 (REAL 주문 없음).
    """

    now = datetime.now(timezone.utc)
    candidates = _narrative_candidates(now)
    policy = SelectionPolicy(
        min_score=0, min_confidence=0, ai_live_gate_mode="ENFORCE"
    )
    selected_order: list[str] = []
    open_symbols: set[str] = set()

    # --- 1) pending=1: 한 번에 하나만 고르고 즉시 OPEN으로 승격(시뮬) ---
    remaining = list(candidates)
    for _ in range(3):
        sel_policy = SelectionPolicy(
            min_score=0,
            min_confidence=0,
            ai_live_gate_mode="ENFORCE",
            excluded_symbols=frozenset(open_symbols),
        )
        decision = select_best_eligible_candidate(
            remaining, sel_policy, scanner_run_id="dry-cycle", now=now
        )
        assert decision.selected is not None
        sym = decision.selected.symbol
        selected_order.append(sym)
        open_symbols.add(sym)
        # pending=1 의미: 다음 선택 전 이전 심볼은 이미 active로 제외
        remaining = [
            c for c in remaining if str(c["symbol"]).upper() != sym
        ]

    assert selected_order == ["KRW-ETH", "KRW-BTC", "KRW-SOL"]
    # CAP는 HOLD로 스킵되었어야 함
    first = select_best_eligible_candidate(
        candidates, policy, scanner_run_id="dry-hold", now=now
    )
    assert any(
        t.get("symbol") == "KRW-CAP" and not t.get("ok")
        for t in first.skip_trace
    )

    # --- 2) 3 OPEN → empty 없음 = SLOT_FULL (서비스 reason: NO_EMPTY_SLOT) ---
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
    port_policy = _policy_entity()
    open_slots = [
        _slot(1, SLOT_OPEN, symbol="KRW-ETH", allocated_amount_krw=8000),
        _slot(2, SLOT_OPEN, symbol="KRW-BTC", allocated_amount_krw=8000),
        _slot(3, SLOT_OPEN, symbol="KRW-SOL", allocated_amount_krw=8000),
    ]
    svc = UpbitPortfolioService(session)
    svc._assignment.get_or_create = MagicMock(return_value=assignment)  # type: ignore[method-assign]
    svc.tick_cooldown_slots = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.ensure_slots = MagicMock(return_value=open_slots)  # type: ignore[method-assign]
    svc.pending_entry_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.get_or_create_policy = MagicMock(return_value=port_policy)  # type: ignore[method-assign]
    # EMPTY 없음
    session.scalars.side_effect = lambda stmt: iter([])
    # daily entry count 조회는 빈 리스트
    session.scalars.side_effect = lambda stmt: iter([])

    full = svc.consume_top_k(
        9999,
        candidates=candidates,
        scanner_run_id="dry-full",
        available_krw=Decimal("500000"),
        account_max_order_amount=Decimal("10000"),
        dry_run=True,
    )
    # SLOT_FULL 시맨틱 = NO_EMPTY_SLOT
    assert full["reason"] == "NO_EMPTY_SLOT"
    assert full["orders_created"] == 0

    # --- 3) ETH exit → COOLDOWN → tick → EMPTY → XRP 자격 ---
    eth_slot = open_slots[0]
    eth_slot.status = SLOT_COOLDOWN
    eth_slot.cooldown_until = now - timedelta(seconds=1)
    eth_slot.closed_at = now

    # tick_cooldown_slots 실로직: COOLDOWN 만료 → EMPTY
    cool_svc = UpbitPortfolioService(session)
    session.scalars.side_effect = lambda stmt: iter([eth_slot])
    released = cool_svc.tick_cooldown_slots(9999)
    assert released == 1
    assert eth_slot.status == SLOT_EMPTY
    assert eth_slot.symbol is None

    # refill: 남은 OPEN(BTC/SOL) + 방금 청산된 ETH 재진입 제외 → XRP
    refill_policy = SelectionPolicy(
        min_score=0,
        min_confidence=0,
        ai_live_gate_mode="ENFORCE",
        excluded_symbols=frozenset({"KRW-ETH", "KRW-BTC", "KRW-SOL"}),
    )
    refill = select_best_eligible_candidate(
        candidates, refill_policy, scanner_run_id="dry-refill", now=now
    )
    assert refill.selected is not None
    assert refill.selected.symbol == "KRW-XRP"


def test_consume_top_k_pending_entry_limit_semantics() -> None:
    """portfolio_max_pending_entries=1 → 이미 pending이면 추가 reserve 차단."""

    session = MagicMock()
    assignment = SimpleNamespace(
        mode=MODE_FULL_MARKET_PORTFOLIO,
        strategy_id=1,
        deployment_id=1,
        template_symbol="KRW-XRP",
        current_symbol="KRW-ETH",
        last_scanner_run_id=None,
        policy_json={},
        ai_live_gate_mode="ENFORCE",
    )
    policy = _policy_entity(portfolio_max_pending_entries=1)
    slots = [
        _slot(1, SLOT_ENTRY_PENDING, symbol="KRW-ETH", reserved_amount_krw=8000),
        _slot(2),
        _slot(3),
    ]
    svc = UpbitPortfolioService(session)
    svc._assignment.get_or_create = MagicMock(return_value=assignment)  # type: ignore[method-assign]
    svc.tick_cooldown_slots = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.ensure_slots = MagicMock(return_value=slots)  # type: ignore[method-assign]
    svc.pending_entry_count = MagicMock(return_value=1)  # type: ignore[method-assign]
    svc.get_or_create_policy = MagicMock(return_value=policy)  # type: ignore[method-assign]

    now = datetime.now(timezone.utc)
    out = svc.consume_top_k(
        9999,
        candidates=_narrative_candidates(now),
        scanner_run_id="pending-1",
        available_krw=Decimal("500000"),
        dry_run=True,
    )
    assert out["reason"] == "PENDING_ENTRY_LIMIT"
    assert out["orders_created"] == 0
    assert out["reserved"] == []


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

    # empty slots + daily entries (빈)
    def scalars_side_effect(stmt):  # noqa: ANN001
        text = str(stmt)
        if "UpbitLiveCandidateSelection" in text or "upbit_live_candidate" in text:
            return iter([])
        return iter([slots[0], slots[1], slots[2]])

    session.scalars.side_effect = scalars_side_effect

    now = datetime.now(timezone.utc)
    candidates = _narrative_candidates(now)
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


def test_enable_confirmation_mismatch_expected_phrase() -> None:
    session = MagicMock()
    svc = UpbitPortfolioService(session)
    out = svc.enable_portfolio(
        9999, confirmation_text="wrong", actor="unit"
    )
    assert out["ok"] is False
    assert out["error"] == "CONFIRMATION_MISMATCH"
    assert out["expected"] == CONFIRM_ENABLE_PORTFOLIO


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


def test_risk_group_policy_json_default_on_entity_helper() -> None:
    """nullable future-ready JSONB bag — 기본 {}."""

    policy = _policy_entity()
    assert policy.risk_group_policy_json == {}
