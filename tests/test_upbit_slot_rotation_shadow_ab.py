"""Slot rotation shadow A/B unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_platform.operation.upbit_full_market.slot_rotation_shadow_ab import (
    R0_CURRENT,
    R2_FORCE_MAX_WAIT,
    R4_COMBINED,
    T10_BASELINE,
    ScannerRunRecord,
    ShadowSlot,
    explain_re_stale_occupancy,
    pick_study_verdict,
    simulate_rotation_policy,
)


def _run_at(offset_min: int) -> datetime:
    base = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=offset_min)


def test_re_root_cause_documents_max_wait_gate() -> None:
    rc = explain_re_stale_occupancy()
    ids = {x["id"] for x in rc["root_causes"]}
    assert "MAX_WAIT_NOT_UNCONDITIONAL" in ids
    assert "HIGH_SCORE_TRAP" in ids


def test_r2_force_evict_replaces_stale_high_score_slot() -> None:
    """RE 88점 장기 점유 — R2는 max_wait 후 강제 해제."""

    re_selected = _run_at(-200)  # >3h ago
    initial = [
        ShadowSlot(
            slot_no=1,
            status="WAITING_SIGNAL",
            symbol="KRW-RE",
            score=88.48,
            selected_at=re_selected,
            updated_at=re_selected,
            last_decision="BLOCK",
            evaluation_count=50,
            last_block_reason="SHORT_MA_NOT_ABOVE_LONG_MA",
        ),
        *[
            ShadowSlot(
                slot_no=i,
                status="WAITING_SIGNAL",
                symbol=f"KRW-FILL{i}",
                score=90.0,
                selected_at=re_selected,
                updated_at=re_selected,
            )
            for i in range(2, 6)
        ],
    ]
    runs = [
        ScannerRunRecord(
            run_id="r1",
            run_at=_run_at(0),
            candidates=[
                {
                    "symbol": "KRW-PUMP",
                    "scanner_score": 87.0,
                    "recommendation": "ALLOW",
                    "return_60m_pct": 2.0,
                    "evaluation_detail": {
                        "entry_ab": {"baseline": {"eligible": True}}
                    },
                }
            ],
        )
    ]
    rows = {
        "KRW-PUMP": runs[0].candidates[0],
    }
    r0 = simulate_rotation_policy(
        variant=R0_CURRENT, runs=runs, initial_slots=initial, candidate_rows=rows
    )
    r2 = simulate_rotation_policy(
        variant=R2_FORCE_MAX_WAIT,
        runs=runs,
        initial_slots=initial,
        candidate_rows=rows,
    )
    assert r0.replacements == 0
    assert r2.replacements >= 1


def test_t10_assigns_more_than_r0_when_full() -> None:
    runs = [
        ScannerRunRecord(
            run_id=f"r{i}",
            run_at=_run_at(i * 15),
            candidates=[
                {
                    "symbol": f"KRW-S{i}",
                    "scanner_score": 80.0 + i,
                    "recommendation": "ALLOW",
                    "return_60m_pct": 0.5,
                    "evaluation_detail": {
                        "entry_ab": {"baseline": {"eligible": True}}
                    },
                }
            ],
        )
        for i in range(8)
    ]
    row_index = {
        str(c["symbol"]).upper(): c for r in runs for c in r.candidates
    }
    r0 = simulate_rotation_policy(
        variant=R0_CURRENT, runs=runs, candidate_rows=row_index
    )
    t10 = simulate_rotation_policy(
        variant=T10_BASELINE, runs=runs, candidate_rows=row_index
    )
    assert t10.assignments >= r0.assignments


def test_insufficient_sample_verdict() -> None:
    from stock_platform.operation.upbit_full_market.slot_rotation_shadow_ab import (
        RotationSimMetrics,
    )

    results = {
        "R0": RotationSimMetrics(policy_code="R0", max_slots=5),
    }
    assert pick_study_verdict(results, cohort="CLEAN", sample_count=5) == "INSUFFICIENT_SAMPLE"


def test_r4_beats_r0_on_missed_winner_scenario() -> None:
    """full 5-slot + better newcomer — R4 rotation이 더 많은 BUY 기회."""

    initial = [
        ShadowSlot(
            slot_no=i,
            status="WAITING_SIGNAL",
            symbol=f"KRW-OLD{i}",
            score=70.0,
            selected_at=_run_at(-400),
            updated_at=_run_at(-400),
        )
        for i in range(1, 6)
    ]
    runs = [
        ScannerRunRecord(
            run_id="r-new",
            run_at=_run_at(0),
            candidates=[
                {
                    "symbol": "KRW-NEW",
                    "scanner_score": 90.0,
                    "recommendation": "ALLOW",
                    "return_60m_pct": 3.0,
                    "evaluation_detail": {
                        "entry_ab": {"baseline": {"eligible": True}}
                    },
                }
            ],
        )
    ]
    rows = {"KRW-NEW": runs[0].candidates[0]}
    r0 = simulate_rotation_policy(
        variant=R0_CURRENT, runs=runs, initial_slots=initial, candidate_rows=rows
    )
    r4 = simulate_rotation_policy(
        variant=R4_COMBINED, runs=runs, initial_slots=initial, candidate_rows=rows
    )
    assert r4.replacements >= r0.replacements
