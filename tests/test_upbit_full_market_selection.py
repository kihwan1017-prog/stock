"""UPBIT Full-Market candidate selection / assignment — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    AI_GATE_ENFORCE,
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_AUTO,
)
from stock_platform.operation.upbit_full_market.selection_policy import (
    SelectionPolicy,
    select_best_eligible_candidate,
)


def _cand(
    symbol: str,
    *,
    rank: int,
    rec: str,
    score: float = 10.0,
    confidence: float = 0.8,
    liquidity: float = 1e10,
    ts: datetime | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "rank": rank,
        "recommendation": rec,
        "score": score,
        "confidence": confidence,
        "trade_value_24h": liquidity,
        "market_data_timestamp": ts or datetime.now(timezone.utc),
    }


def test_rank1_hold_selects_rank2_allow() -> None:
    policy = SelectionPolicy(ai_live_gate_mode=AI_GATE_ENFORCE)
    decision = select_best_eligible_candidate(
        [
            _cand("KRW-CAP", rank=1, rec="HOLD"),
            _cand("KRW-ETH", rank=2, rec="ALLOW"),
            _cand("KRW-SOL", rank=3, rec="ALLOW"),
        ],
        policy,
        scanner_run_id="run-a",
    )
    assert decision.selected is not None
    assert decision.selected.symbol == "KRW-ETH"
    assert decision.selected.rank == 2
    assert decision.skip_trace[0]["reason"] == "AI_HOLD"


def test_all_hold_no_selection() -> None:
    policy = SelectionPolicy(ai_live_gate_mode=AI_GATE_ENFORCE)
    decision = select_best_eligible_candidate(
        [
            _cand("KRW-CAP", rank=1, rec="HOLD"),
            _cand("KRW-AAA", rank=2, rec="HOLD"),
        ],
        policy,
    )
    assert decision.selected is None
    assert decision.reason == "NO_ELIGIBLE_CANDIDATE"


def test_stale_scanner_rejected() -> None:
    policy = SelectionPolicy(
        ai_live_gate_mode=AI_GATE_ENFORCE,
        max_candidate_age_seconds=60,
    )
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    decision = select_best_eligible_candidate(
        [_cand("KRW-ETH", rank=1, rec="ALLOW")],
        policy,
        scanner_completed_at=old,
    )
    assert decision.selected is None
    assert decision.reason == "SCANNER_RESULT_STALE"


def test_block_not_forced_allow() -> None:
    policy = SelectionPolicy(ai_live_gate_mode=AI_GATE_ENFORCE)
    decision = select_best_eligible_candidate(
        [
            _cand("KRW-CAP", rank=1, rec="BLOCK"),
            _cand("KRW-ETH", rank=2, rec="ALLOW"),
        ],
        policy,
    )
    assert decision.selected is not None
    assert decision.selected.symbol == "KRW-ETH"
    assert decision.skip_trace[0]["reason"] == "AI_BLOCK"


def test_excluded_symbol_skipped() -> None:
    policy = SelectionPolicy(
        ai_live_gate_mode=AI_GATE_ENFORCE,
        excluded_symbols=frozenset({"KRW-ETH"}),
    )
    decision = select_best_eligible_candidate(
        [
            _cand("KRW-ETH", rank=1, rec="ALLOW"),
            _cand("KRW-SOL", rank=2, rec="ALLOW"),
        ],
        policy,
    )
    assert decision.selected is not None
    assert decision.selected.symbol == "KRW-SOL"


def test_modes_constants() -> None:
    assert MODE_FIXED_SYMBOL != MODE_FULL_MARKET_AUTO


@pytest.mark.parametrize(
    "rec",
    ["HOLD", "BLOCK"],
)
def test_hold_block_never_selected_under_enforce(rec: str) -> None:
    policy = SelectionPolicy(ai_live_gate_mode=AI_GATE_ENFORCE)
    decision = select_best_eligible_candidate(
        [_cand("KRW-ETH", rank=1, rec=rec)],
        policy,
    )
    assert decision.selected is None
