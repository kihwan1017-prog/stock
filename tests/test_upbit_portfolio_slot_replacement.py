"""WAITING_SIGNAL slot replacement policy — focused unit tests (REAL 주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_PORTFOLIO,
    MODE_FULL_MARKET_SINGLE,
    SLOT_ENTRY_PENDING,
    SLOT_OPEN,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.slot_replacement import (
    REASON_MAX_WAIT,
    REASON_SCORE_IMPROVEMENT,
    REASON_STALE_CANDIDATE,
    CandidateScoreView,
    ReplacementPolicy,
    SlotScoreView,
    evaluate_slot_replacement,
    is_slot_structurally_replaceable,
    pick_best_replacement,
)


def _now() -> datetime:
    return datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _slot(
    *,
    slot_id: int = 1,
    slot_no: int = 1,
    status: str = SLOT_WAITING_SIGNAL,
    symbol: str = "KRW-PUMP",
    score: float = 75.0,
    age_sec: float = 4000,
    selected_age_sec: float | None = 4000,
    reserved: float | None = 0,
    entry_order_id: int | None = None,
    binding_id: int | None = None,
    has_open_order: bool = False,
    last_block_reason: str | None = None,
    evaluation_count: int = 0,
    last_decision: str | None = None,
) -> SlotScoreView:
    now = _now()
    return SlotScoreView(
        slot_id=slot_id,
        slot_no=slot_no,
        status=status,
        symbol=symbol,
        score=score,
        updated_at=now - timedelta(seconds=age_sec),
        selected_at=(
            None
            if selected_age_sec is None
            else now - timedelta(seconds=selected_age_sec)
        ),
        reserved_amount_krw=reserved,
        entry_order_id=entry_order_id,
        position_binding_id=binding_id,
        has_open_order=has_open_order,
        last_block_reason=last_block_reason,
        evaluation_count=evaluation_count,
        last_decision=last_decision,
    )


def _cand(
    symbol: str = "KRW-SUI", score: float = 84.0, rec: str = "ALLOW"
) -> CandidateScoreView:
    return CandidateScoreView(
        symbol=symbol, score=score, recommendation=rec, rank=1
    )


POLICY = ReplacementPolicy(
    hold_seconds=1800,
    max_wait_seconds=10800,
    switch_min_score_delta=8.0,
    candidate_max_age_seconds=1800,
)


def test_within_hold_no_replace_even_with_large_delta() -> None:
    d = evaluate_slot_replacement(
        slot=_slot(age_sec=600, score=70),
        candidate=_cand(score=90),
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is False
    assert d.reason == "WITHIN_HOLD"


def test_after_hold_insufficient_delta_no_replace() -> None:
    # SUI 81.8 vs PUMP 75.31 = +6.49 < 8
    d = evaluate_slot_replacement(
        slot=_slot(age_sec=4000, score=75.31, symbol="KRW-PUMP"),
        candidate=_cand(symbol="KRW-SUI", score=81.8),
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is False
    assert d.reason == "DELTA_OR_WAIT_INSUFFICIENT"


def test_after_hold_sufficient_delta_replace() -> None:
    d = evaluate_slot_replacement(
        slot=_slot(age_sec=4000, score=70),
        candidate=_cand(score=80),
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is True
    assert d.reason == REASON_SCORE_IMPROVEMENT


def test_max_wait_allows_smaller_delta() -> None:
    d = evaluate_slot_replacement(
        slot=_slot(age_sec=12000, score=75.31, selected_age_sec=12000),
        candidate=_cand(score=81.8),
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is True
    assert d.reason in {REASON_MAX_WAIT, REASON_STALE_CANDIDATE}
    d = evaluate_slot_replacement(
        slot=_slot(
            age_sec=12000,
            score=76,
            selected_age_sec=12000,  # stale + max_wait
        ),
        candidate=_cand(score=78),
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is True
    assert d.reason == REASON_STALE_CANDIDATE


def test_stale_under_max_wait_does_not_replace() -> None:
    d = evaluate_slot_replacement(
        slot=_slot(
            age_sec=4000,
            score=75.31,
            selected_age_sec=5000,
        ),
        candidate=_cand(score=81.8),
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is False
    assert d.reason == "DELTA_OR_WAIT_INSUFFICIENT"


def test_entry_pending_never_replace() -> None:
    ok, reason = is_slot_structurally_replaceable(
        _slot(status=SLOT_ENTRY_PENDING, reserved=5000, entry_order_id=99)
    )
    assert ok is False
    assert reason and "ENTRY_PENDING" in reason


def test_open_never_replace() -> None:
    ok, reason = is_slot_structurally_replaceable(_slot(status=SLOT_OPEN))
    assert ok is False
    assert reason and "OPEN" in reason


def test_reserved_positive_never_replace() -> None:
    ok, reason = is_slot_structurally_replaceable(
        _slot(reserved=1000.0, entry_order_id=None)
    )
    assert ok is False
    assert reason == "RESERVED_POSITIVE"


def test_pick_best_prefers_weak_slot_and_one_pair() -> None:
    """MET2 83 / PUMP 75 / PEPE 77 + SUI 81.8 → max_wait 시 PUMP 교체."""

    slots = [
        _slot(
            slot_id=1,
            slot_no=1,
            symbol="KRW-MET2",
            score=83.12,
            age_sec=12000,
            selected_age_sec=12000,
        ),
        _slot(
            slot_id=2,
            slot_no=2,
            symbol="KRW-PUMP",
            score=75.31,
            age_sec=12000,
            selected_age_sec=12000,
        ),
        _slot(
            slot_id=3,
            slot_no=3,
            symbol="KRW-PEPE",
            score=76.97,
            age_sec=12000,
            selected_age_sec=12000,
        ),
    ]
    cands = [
        _cand("KRW-SUI", 81.8),
        _cand("KRW-SHIB", 79.09),
        _cand("KRW-XLM", 78.77),
    ]
    d = pick_best_replacement(
        slots=slots, candidates=cands, policy=POLICY, now=_now()
    )
    assert d.replace is True
    assert d.old_symbol == "KRW-PUMP"
    assert d.new_symbol == "KRW-SUI"
    assert d.reason in {REASON_MAX_WAIT, REASON_STALE_CANDIDATE}


def test_no_churn_when_delta_under_threshold_and_under_max_wait() -> None:
    """hold 지났지만 max_wait 전 + delta<8 → 교체 없음 (20:01 사례)."""

    slots = [
        _slot(slot_id=2, slot_no=2, symbol="KRW-PUMP", score=75.31, age_sec=4000),
        _slot(slot_id=3, slot_no=3, symbol="KRW-PEPE", score=76.97, age_sec=4000),
    ]
    d = pick_best_replacement(
        slots=slots,
        candidates=[_cand("KRW-SUI", 81.8)],
        policy=POLICY,
        now=_now(),
    )
    assert d.replace is False


def test_duplicate_symbol_across_waiting_denied() -> None:
    slots = [
        _slot(slot_id=1, symbol="KRW-SUI", score=70, age_sec=12000),
        _slot(slot_id=2, symbol="KRW-PUMP", score=60, age_sec=12000),
    ]
    d = pick_best_replacement(
        slots=slots,
        candidates=[_cand("KRW-SUI", 90)],
        policy=POLICY,
        now=_now(),
    )
    # SUI는 이미 slot1에 있으므로 slot2로 배정·자가교체 모두 금지
    assert d.replace is False


def test_protected_open_symbol_blocked() -> None:
    d = pick_best_replacement(
        slots=[_slot(symbol="KRW-PUMP", score=60, age_sec=12000)],
        candidates=[_cand("KRW-ETH", 90)],
        policy=POLICY,
        now=_now(),
        protected_symbols={"KRW-ETH"},
    )
    assert d.replace is False


def test_mode_helpers_unchanged_for_single_fixed() -> None:
    from stock_platform.operation.upbit_full_market.constants import (
        is_full_market_portfolio,
        is_full_market_single,
    )

    assert is_full_market_portfolio(MODE_FULL_MARKET_PORTFOLIO)
    assert is_full_market_single(MODE_FULL_MARKET_SINGLE)
    assert not is_full_market_portfolio(MODE_FIXED_SYMBOL)


def test_consume_top_k_open_full_still_no_empty_compatible() -> None:
    """OPEN 만석은 교체 불가 → NO_EMPTY_SLOT 유지 (regression)."""

    from decimal import Decimal

    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

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
    port_policy = SimpleNamespace(
        enabled=True,
        entry_state="RUNNING",
        max_positions=3,
        portfolio_max_pending_entries=1,
        portfolio_daily_entry_limit=10,
        candidate_max_age_seconds=1800,
        portfolio_capital_limit_krw=500000,
        min_cash_reserve_pct=0.6,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=0.12,
        max_total_exposure_pct=0.3,
        allow_duplicate_symbol=False,
        risk_group_policy_json={},
    )
    svc = UpbitPortfolioService(session)
    svc._assignment.get_or_create = MagicMock(return_value=assignment)  # type: ignore[method-assign]
    svc.tick_cooldown_slots = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.ensure_slots = MagicMock(return_value=[])  # type: ignore[method-assign]
    svc.pending_entry_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.get_or_create_policy = MagicMock(return_value=port_policy)  # type: ignore[method-assign]
    svc.recover_stale_entry_pending_without_order = MagicMock(  # type: ignore[method-assign]
        return_value={"released": 0}
    )
    svc.list_slots = MagicMock(return_value=[])  # type: ignore[method-assign]
    # EMPTY 없음, WAITING도 없음
    session.scalars.side_effect = lambda stmt: iter([])

    out = svc.consume_top_k(
        9999,
        candidates=[
            {
                "symbol": "KRW-SUI",
                "score": 90,
                "rank": 1,
                "recommendation": "ALLOW",
                "confidence": 0.9,
            }
        ],
        scanner_run_id="dry-open-full",
        available_krw=Decimal("500000"),
        account_max_order_amount=Decimal("10000"),
        dry_run=True,
    )
    assert out["reason"] == "NO_EMPTY_SLOT"
    assert out["orders_created"] == 0
