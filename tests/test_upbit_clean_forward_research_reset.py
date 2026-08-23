"""Clean Forward Research Baseline Reset — tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    CLEAN_FORWARD_EPOCH_START,
    COHORT_CLEAN_FORWARD,
    COHORT_LEGACY,
    COHORT_STAMPED_BACKFILL,
    HISTORICAL_COMPROMISED_REFERENCE,
    LEGACY_FORWARD_COUNT,
    TARGET_CLEAN_MIN,
    assign_clean_forward_obs,
    classify_forward_row,
    evaluate_clean_promotion_gates,
    partition_forward_rows,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    COHORT_NEW,
    run_b1_forward_validation,
)


def _outcome(net: float) -> dict:
    return {
        "net_pnl_krw": net,
        "gross_pnl_krw": net + 10,
        "estimated_fee_krw": 10.0,
        "net_return_pct": net / 100.0,
        "holding_seconds": 200,
        "exit_reason": "MA_DEAD_CROSS",
        "fee_only_loss": False,
    }


def _windows_ok() -> dict:
    return {
        str(m): {
            "status": "OK",
            "price": 100.0,
            "return_pct": 0.5,
        }
        for m in (5, 15, 30, 60)
    }


def _canonical_provenance() -> dict:
    return {
        "schema": "shadow_entry_price_provenance_v1",
        "quality": "CANONICAL_DB_CANDLE",
        "source": "market.candle_minute.detected_candle_close",
        "ok": True,
    }


def _shadow(
    sid: int,
    detected: datetime,
    *,
    backfill: bool = False,
    canonical: bool = False,
    windows: bool = True,
    with_stamps: bool = True,
) -> SimpleNamespace:
    detail: dict = {}
    if with_stamps:
        detail = {
            "exit_ab": {"baseline": _outcome(1.0)},
            "entry_ab": {"schema": "entry_policy_ab_v1"},
            "entry_forward_features": {
                "ok": True,
                "pre_entry_return_5m": 0.1,
                "dist_from_5m_high_pct": -0.5,
            },
        }
    if backfill:
        detail["research_stamp_backfill"] = {
            "stamped_at": "2026-08-24T00:00:00+00:00",
            "numeric_columns_mutated": False,
        }
    if windows:
        detail["windows"] = _windows_ok()

    snap: dict = {"candidate": {"ma_spread_pct": 0.1}}
    if canonical:
        snap["entry_price_provenance"] = _canonical_provenance()

    return SimpleNamespace(
        shadow_id=sid,
        symbol=f"KRW-S{sid % 7}",
        scanner_score=70,
        scanner_rank=1,
        recommendation="ALLOW",
        confidence=0.8,
        ma5=101.0,
        ma20=100.0,
        rsi14=60.0,
        volume_surge=0.9,
        entry_price=Decimal("100"),
        entry_snapshot=snap,
        evaluation_detail=detail,
        return_5m_pct=0.0,
        return_15m_pct=0.0,
        return_30m_pct=0.0,
        return_60m_pct=0.0,
        mfe_pct=0.5,
        mae_pct=-0.1,
        detected_at=detected,
        created_at=detected,
        status="COMPLETED",
        deleted_at=None,
    )


def test_legacy_excluded_from_promotion() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow(sid=i, detected=t0 + timedelta(minutes=i), with_stamps=True)
        for i in range(LEGACY_FORWARD_COUNT + 2)
    ]
    report = run_b1_forward_validation(rows)
    assert report["clean_forward"]["promotion_uses_legacy"] is False
    assert report["clean_forward"]["promotion_uses_clean_only"] is True
    assert report["legacy_reference"]["label"] == HISTORICAL_COMPROMISED_REFERENCE


def test_backfill_not_clean() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=1)
    row = _shadow(
        sid=900,
        detected=epoch,
        backfill=True,
        canonical=True,
        with_stamps=True,
    )
    cls = classify_forward_row(row)
    assert cls["cohort"] == COHORT_STAMPED_BACKFILL
    assert cls["clean"] is False
    part = partition_forward_rows([row])
    assert part["new_stamped_count"] == 1
    assert part["clean_new_count"] == 0


def test_clean_epoch_boundary() -> None:
    before = _shadow(
        sid=1,
        detected=CLEAN_FORWARD_EPOCH_START - timedelta(seconds=1),
        canonical=True,
        with_stamps=True,
    )
    after = _shadow(
        sid=2,
        detected=CLEAN_FORWARD_EPOCH_START + timedelta(seconds=1),
        canonical=True,
        with_stamps=True,
    )
    assert classify_forward_row(before)["clean"] is False
    assert classify_forward_row(after)["clean"] is True


def test_valid_canonical_sample_included() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=2)
    row = _shadow(sid=100, detected=epoch, canonical=True, with_stamps=True)
    obs = assign_clean_forward_obs([row])
    assert len(obs) == 1
    assert obs[0].cohort == COHORT_CLEAN_FORWARD


def test_invalid_price_excluded() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=2)
    row = _shadow(sid=101, detected=epoch, canonical=False, with_stamps=True)
    cls = classify_forward_row(row)
    assert cls["clean"] is False
    assert "INVALID_PRICE_SOURCE" in cls["exclusions"]


def test_invalid_time_alignment_excluded() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=2)
    row = _shadow(
        sid=102, detected=epoch, canonical=True, with_stamps=True, windows=False
    )
    cls = classify_forward_row(row)
    assert "INVALID_TIME_ALIGNMENT" in cls["exclusions"]


def test_promotion_clean_lt_500_reject() -> None:
    gates = evaluate_clean_promotion_gates(
        clean_n=100,
        baseline={"net_pnl": 10, "profit_factor": 1.2, "max_loss": -50},
        b1={"net_pnl": 20, "profit_factor": 1.3, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert gates["PROMOTION_STATUS"] == "NOT READY"
    assert "A_clean_ge_500" in gates["PROMOTION_GATE_FAILURES"]


def test_promotion_net_lt_0_reject() -> None:
    gates = evaluate_clean_promotion_gates(
        clean_n=600,
        baseline={"net_pnl": -10, "profit_factor": 0.8, "max_loss": -50},
        b1={"net_pnl": -1, "profit_factor": 1.2, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert "C_b1_net_gt_0" in gates["PROMOTION_GATE_FAILURES"]


def test_promotion_pf_lt_1_reject() -> None:
    gates = evaluate_clean_promotion_gates(
        clean_n=600,
        baseline={"net_pnl": -10, "profit_factor": 0.8, "max_loss": -50},
        b1={"net_pnl": 5, "profit_factor": 0.9, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert "D_b1_pf_gt_1" in gates["PROMOTION_GATE_FAILURES"]


def test_clean_count_increment() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=1)
    rows = [
        _shadow(sid=i, detected=epoch + timedelta(minutes=i), canonical=True)
        for i in range(3)
    ]
    part = partition_forward_rows(rows)
    assert part["clean_new_count"] == 3


def test_baseline_b1_same_opportunity_clean() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=1)
    row = _shadow(sid=1, detected=epoch, canonical=True)
    report = run_b1_forward_validation([row])
    assert report["baseline"]["opportunities"] == report["b1"]["opportunities"]


def test_report_schema_clean_reset() -> None:
    report = run_b1_forward_validation([])
    assert report["FINAL_VERDICT_CLEAN_RESET"] == "CLEAN_FORWARD_RESEARCH_BASELINE_RESET"
    assert report["NEXT_ACTION_CLEAN"] == "COLLECT_CLEAN_FORWARD_SAMPLE"
    assert report["schema"] == "entry_b1_forward_validation_v2_clean_epoch"
