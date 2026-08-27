"""Entry signal shadow — isolation + replay unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    SymbolEntrySnapshot,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    VARIANT_E0,
    VARIANT_E1,
    VARIANT_E2,
    VARIANT_E3,
    VARIANT_E4,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.variants import (
    evaluate_all_variants,
    evaluate_variant_entry,
)


def _snap(**kwargs) -> SymbolEntrySnapshot:
    base = dict(
        symbol="KRW-TEST",
        selection_id=1,
        selected_at=datetime.now(timezone.utc),
        ai_recommendation="ALLOW",
        rsi14=65.0,
        volume_surge=1.0,
        bound_to_waiting_slot=True,
    )
    base.update(kwargs)
    return SymbolEntrySnapshot(**base)


def test_e0_blocks_short_ma_not_above() -> None:
    out = evaluate_variant_entry(
        variant=VARIANT_E0,
        short_ma=Decimal("100"),
        long_ma=Decimal("101"),
        snap=_snap(),
    )
    assert out["pass"] is False
    assert out["block_reason"] == "SHORT_MA_NOT_ABOVE_LONG_MA"


def test_e1_relaxes_short_ma_gate_only() -> None:
    # gap ≈ -0.01% — E0 blocks SHORT_MA; E1 unlocks first gate then hits MA_SEP (nested)
    short = Decimal("99.99")
    long_ = Decimal("100")
    e0 = evaluate_variant_entry(
        variant=VARIANT_E0, short_ma=short, long_ma=long_, snap=_snap()
    )
    e1 = evaluate_variant_entry(
        variant=VARIANT_E1, short_ma=short, long_ma=long_, snap=_snap()
    )
    assert e0["pass"] is False
    assert e0["block_reason"] == "SHORT_MA_NOT_ABOVE_LONG_MA"
    assert e1["pass"] is False
    assert e1["block_reason"] == "MA_SEPARATION_TOO_SMALL"



def test_e2_pass_when_e0_ma_sep_block() -> None:
    # gap = 0.04% — below REAL 0.05, above E2 0.03
    short = Decimal("100.04")
    long_ = Decimal("100")
    e0 = evaluate_variant_entry(
        variant=VARIANT_E0, short_ma=short, long_ma=long_, snap=_snap()
    )
    e2 = evaluate_variant_entry(
        variant=VARIANT_E2, short_ma=short, long_ma=long_, snap=_snap()
    )
    assert e0["block_reason"] == "MA_SEPARATION_TOO_SMALL"
    assert e2["pass"] is True


def test_e3_pass_when_e0_rsi_block() -> None:
    short = Decimal("101")
    long_ = Decimal("100")
    snap = _snap(rsi14=72.0)
    e0 = evaluate_variant_entry(
        variant=VARIANT_E0, short_ma=short, long_ma=long_, snap=snap
    )
    e3 = evaluate_variant_entry(
        variant=VARIANT_E3, short_ma=short, long_ma=long_, snap=snap
    )
    assert e0["block_reason"] == "RSI_TOO_HIGH"
    assert e3["pass"] is True


def test_e4_virtual_signal_ignores_emit_suppression() -> None:
    short = Decimal("101")
    long_ = Decimal("100")
    e0 = evaluate_variant_entry(
        variant=VARIANT_E0,
        short_ma=short,
        long_ma=long_,
        snap=_snap(),
        emit_suppressed=True,
    )
    e4 = evaluate_variant_entry(
        variant=VARIANT_E4,
        short_ma=short,
        long_ma=long_,
        snap=_snap(),
        emit_suppressed=True,
    )
    assert e0["block_reason"] == "SIGNAL_EMIT_SUPPRESSED"
    assert e4["pass"] is True


def test_evaluate_all_variants_same_observation() -> None:
    all_d = evaluate_all_variants(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        snap=_snap(rsi14=72.0),
    )
    assert set(all_d.keys()) == {"E0", "E1", "E2", "E3", "E4"}
    assert all_d["E0"]["block_reason"] == "RSI_TOO_HIGH"
    assert all_d["E3"]["pass"] is True


def test_enroll_forward_no_slot_mutation() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
        enroll_forward_observation,
    )

    session = MagicMock()
    session.scalar.return_value = None
    result = enroll_forward_observation(
        session,
        uba_id=1380,
        symbol="KRW-TEST",
        selection_id=999001,
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        snap=_snap(selection_id=999001),
        commit=False,
    )
    assert result["ok"] is True
    assert result["real_order_mutation"] == 0
    assert result["slot_mutation"] == 0
    assert result["daily_count_mutation"] == 0
    assert result["created"] == 5
    assert session.add.call_count == 5


def test_duplicate_selection_skipped() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
        enroll_forward_observation,
    )

    session = MagicMock()
    session.scalar.return_value = 123  # already exists
    result = enroll_forward_observation(
        session,
        uba_id=1380,
        symbol="KRW-TEST",
        selection_id=42,
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        snap=_snap(selection_id=42),
        commit=False,
    )
    assert result["created"] == 0
    assert result["skipped_duplicate"] == 5


def test_replay_outcome_not_used_in_decision() -> None:
    """Entry decision uses only selection-time MA — future prices separate."""

    from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.replay import (
        summarize_replay,
    )

    obs = [
        {
            "observation_id": "sel:1",
            "symbol": "KRW-A",
            "observed_at": "2026-08-20T00:00:00+00:00",
            "attribution": "BLOCKED_BY_RSI",
            "decisions": {
                "E0": {"pass": False, "block_reason": "RSI_TOO_HIGH"},
                "E1": {"pass": False},
                "E2": {"pass": False},
                "E3": {"pass": True},
                "E4": {"pass": False},
            },
            "outcome": {
                "ok": True,
                "net_return_15m_pct": 1.5,
                "mfe_pct": 2.0,
                "mae_pct": -0.5,
                "futures": {"future_15m": 1.6},
            },
        }
    ]
    summary = summarize_replay(obs)
    assert summary["variants"]["E3"]["ENTRIES"] == 1
    assert summary["variants"]["E0"]["ENTRIES"] == 0
    assert summary["opportunity_cost"]["BLOCKED_BY_RSI"]["MISSED_POSITIVE_15M"] == 1
