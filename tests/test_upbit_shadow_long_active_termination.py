"""U-TERM-A — LONG_ACTIVE permanent-absence termination (TARGET_ONLY)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    FALLBACK_ABSENT_CONFIRMED,
    MinuteBar,
)
from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (
    _is_valid_cohort_row,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_CANCELLED,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator import (
    UpbitOpportunityShadowEvaluator,
)
from stock_platform.operation.upbit_opportunity_shadow.source_range_reconcile import (
    SourceRangeEvidence,
)
from stock_platform.operation.upbit_opportunity_shadow.termination import (
    TERMINATION_REASON_TARGET,
    apply_permanent_absence_termination,
    grace_seconds,
    is_permanent_absence_candidate,
)


def _bar(at: datetime, px: str = "100") -> MinuteBar:
    d = Decimal(px)
    return MinuteBar(candle_at=at, open=d, high=d, low=d, close=d)


def _full(t0: datetime, n: int = 65) -> list[MinuteBar]:
    return [_bar(t0 + timedelta(minutes=i), str(100 + i * 0.01)) for i in range(n)]


def _patch_common(monkeypatch, bars, *, evidence: SourceRangeEvidence, resolve=None):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
            upbit_scanner_shadow_evaluator_interval_seconds=180.0,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.termination.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_evaluator_interval_seconds=180.0,
        ),
    )

    async def _ensure(*_a, **_k):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def _resolve(session, **kwargs):
        if resolve is not None:
            return resolve
        return {
            "bars": list(kwargs.get("bars") or bars),
            "absent_by_target": {},
            "source_unavailable_by_target": {},
            "resolve_detail": {},
        }

    async def _reconcile(session, **kwargs):
        return list(kwargs.get("bars") or bars), evidence

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        _ensure,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.resolve_missing_target_minutes",
        _resolve,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.reconcile_observation_source",
        _reconcile,
    )


def _row(t0: datetime, sid: int = 5200) -> UpbitOpportunityShadowEntity:
    return UpbitOpportunityShadowEntity(
        shadow_id=sid,
        scanner_run_id="term-a",
        symbol="KRW-PRL",
        recommendation="ALLOW",
        detected_at=t0,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("100000"),
        status=SHADOW_STATUS_ACTIVE,
        evaluation_detail={},
    )


def _ok_evidence(
    *,
    absent_ats: set[datetime] | None = None,
    source_unavailable: bool = False,
    source_check_result: str = "OK",
    **kwargs,
) -> SourceRangeEvidence:
    return SourceRangeEvidence(
        source_check_performed=True,
        source_unavailable=source_unavailable,
        source_absent_confirmed_ats=set(absent_ats or ()),
        source_candle_count=kwargs.get("source_candle_count", 10),
        source_check_result=source_check_result,
        upserted_count=0,
        requests=1,
        rate_limited=False,
        error_code=kwargs.get("error_code"),
    )


def _gap_bars_and_absent(
    floor: datetime, *, keep_minutes: int = 10
) -> tuple[list[MinuteBar], set[datetime]]:
    """초반 keep_minutes만 존재 · 나머지는 SOURCE_ABSENT (path_pass용)."""

    bars = [_bar(floor + timedelta(minutes=i)) for i in range(0, keep_minutes)]
    absent = {
        floor + timedelta(minutes=i) for i in range(keep_minutes, 61)
    }
    return bars, absent


@pytest.mark.asyncio
async def test_a_source_present_completes(monkeypatch):
    t0 = datetime(2026, 8, 13, 21, 19, 40, tzinfo=timezone.utc)
    now = t0 + timedelta(hours=2)
    bars = _full(t0.replace(second=0, microsecond=0), 70)
    _patch_common(monkeypatch, bars, evidence=_ok_evidence())
    row = _row(t0)
    session = MagicMock()
    ev = UpbitOpportunityShadowEvaluator(session, now=now, allow_sync=False)
    result = await ev._apply_timeseries(row, persist=True)
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.evaluated_60m_at is not None
    assert result.get("terminated") is not True


@pytest.mark.asyncio
async def test_b_absent_prior_within_fallback_last_known(monkeypatch):
    """target absent 이지만 prior lag <=180 → LAST_KNOWN → COMPLETED."""
    t0 = datetime(2026, 8, 13, 21, 19, 40, tzinfo=timezone.utc)
    floor = t0.replace(second=0, microsecond=0)
    # 60m target ~22:19 — prior at 22:17 (lag 120s) 만 두고 22:19 exact 제외
    bars = []
    for i in range(0, 58):
        bars.append(_bar(floor + timedelta(minutes=i)))
    bars.append(_bar(floor + timedelta(minutes=58)))  # 22:17
    # skip 22:18, 22:19
    for i in range(60, 70):
        bars.append(_bar(floor + timedelta(minutes=i)))

    target_60 = floor + timedelta(minutes=60)  # 22:19
    absent = {floor + timedelta(minutes=58 + 1), target_60}  # 22:18, 22:19
    resolve = {
        "bars": bars,
        "absent_by_target": {target_60: True},
        "source_unavailable_by_target": {},
        "resolve_detail": {
            target_60.isoformat(): {
                "status": FALLBACK_ABSENT_CONFIRMED,
                "api_rows": 5,
            }
        },
    }
    _patch_common(
        monkeypatch,
        bars,
        evidence=_ok_evidence(absent_ats=absent),
        resolve=resolve,
    )
    row = _row(t0, sid=5201)
    now = t0 + timedelta(hours=3)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    await ev._apply_timeseries(row, persist=True)
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.evaluated_60m_at is not None


@pytest.mark.asyncio
async def test_c_grace_not_elapsed_stays_active(monkeypatch):
    t0 = datetime(2026, 8, 13, 21, 19, 40, tzinfo=timezone.utc)
    floor = t0.replace(second=0, microsecond=0)
    bars, absent = _gap_bars_and_absent(floor, keep_minutes=10)
    target_60 = floor + timedelta(minutes=60)
    resolve = {
        "bars": bars,
        "absent_by_target": {target_60: True},
        "source_unavailable_by_target": {},
        "resolve_detail": {
            target_60.isoformat(): {
                "status": FALLBACK_ABSENT_CONFIRMED,
                "api_rows": 0,
            }
        },
    }
    _patch_common(
        monkeypatch,
        bars,
        evidence=_ok_evidence(absent_ats=absent),
        resolve=resolve,
    )
    row = _row(t0, sid=5202)
    # candle_end 직후 — grace 540s 미경과
    now = target_60 + timedelta(minutes=1) + timedelta(seconds=60)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    await ev._apply_timeseries(row, persist=True)
    assert row.status == SHADOW_STATUS_ACTIVE
    assert row.evaluated_60m_at is None
    cand = (row.evaluation_detail or {}).get("termination_candidate") or {}
    assert cand.get("first_blocked_at")


@pytest.mark.asyncio
async def test_d_grace_elapsed_cancelled(monkeypatch):
    t0 = datetime(2026, 8, 13, 21, 19, 40, tzinfo=timezone.utc)
    floor = t0.replace(second=0, microsecond=0)
    bars, absent = _gap_bars_and_absent(floor, keep_minutes=10)
    target_60 = floor + timedelta(minutes=60)
    resolve = {
        "bars": bars,
        "absent_by_target": {target_60: True},
        "source_unavailable_by_target": {},
        "resolve_detail": {
            target_60.isoformat(): {
                "status": FALLBACK_ABSENT_CONFIRMED,
                "api_rows": 0,
            }
        },
    }
    _patch_common(
        monkeypatch,
        bars,
        evidence=_ok_evidence(absent_ats=absent),
        resolve=resolve,
    )
    row = _row(t0, sid=5203)
    now = target_60 + timedelta(minutes=1) + timedelta(seconds=600)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    result = await ev._apply_timeseries(row, persist=True)
    assert result.get("terminated") is True
    assert row.status == SHADOW_STATUS_CANCELLED
    assert row.evaluated_60m_at is None
    assert row.return_60m_pct is None
    term = (row.evaluation_detail or {}).get("termination") or {}
    assert term.get("reason") == TERMINATION_REASON_TARGET
    assert term.get("terminated_at")
    assert term.get("first_blocked_at")


@pytest.mark.asyncio
async def test_e_source_unavailable_stays_active(monkeypatch):
    t0 = datetime(2026, 8, 13, 21, 19, 40, tzinfo=timezone.utc)
    floor = t0.replace(second=0, microsecond=0)
    bars = [_bar(floor + timedelta(minutes=i)) for i in range(0, 5)]
    evidence = _ok_evidence(
        source_unavailable=True,
        source_check_result="UNAVAILABLE",
        error_code="Timeout",
    )
    _patch_common(monkeypatch, bars, evidence=evidence)
    row = _row(t0, sid=5204)
    now = t0 + timedelta(hours=5)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    await ev._apply_timeseries(row, persist=True)
    assert row.status == SHADOW_STATUS_ACTIVE
    assert (row.evaluation_detail or {}).get("termination") is None


@pytest.mark.asyncio
async def test_f_cancelled_next_tick_no_rewrite(monkeypatch):
    t0 = datetime(2026, 8, 13, 21, 19, 40, tzinfo=timezone.utc)
    floor = t0.replace(second=0, microsecond=0)
    bars, absent = _gap_bars_and_absent(floor, keep_minutes=10)
    target_60 = floor + timedelta(minutes=60)
    resolve = {
        "bars": bars,
        "absent_by_target": {target_60: True},
        "source_unavailable_by_target": {},
        "resolve_detail": {
            target_60.isoformat(): {
                "status": FALLBACK_ABSENT_CONFIRMED,
                "api_rows": 0,
            }
        },
    }
    _patch_common(
        monkeypatch,
        bars,
        evidence=_ok_evidence(absent_ats=absent),
        resolve=resolve,
    )
    row = _row(t0, sid=5205)
    now = target_60 + timedelta(minutes=20)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    await ev._apply_timeseries(row, persist=True)
    assert row.status == SHADOW_STATUS_CANCELLED
    first_term = dict((row.evaluation_detail or {}).get("termination") or {})
    result2 = apply_permanent_absence_termination(
        row,
        computed={"ok": True, "windows": {}, "path_quality": {}},
        now=now + timedelta(minutes=5),
    )
    assert result2.get("already_cancelled") or result2.get("already_terminated")
    assert (row.evaluation_detail or {}).get("termination") == first_term


def test_g_cancelled_excluded_from_cohort_and_stats():
    t0 = datetime(2026, 8, 13, 21, 19, tzinfo=timezone.utc)
    cancelled = _row(t0, sid=52)
    cancelled.status = SHADOW_STATUS_CANCELLED
    cancelled.evaluation_detail = {
        "termination": {"reason": TERMINATION_REASON_TARGET}
    }
    completed = _row(t0, sid=53)
    completed.status = SHADOW_STATUS_COMPLETED
    completed.evaluated_5m_at = t0
    completed.evaluated_15m_at = t0
    completed.evaluated_30m_at = t0
    completed.evaluated_60m_at = t0
    completed.return_5m_pct = 1.0
    completed.return_15m_pct = 1.0
    completed.return_30m_pct = 1.0
    completed.return_60m_pct = 1.0
    completed.evaluation_detail = {
        "windows": {
            "5": {"selection_type": "EXACT_TARGET_CANDLE", "final": True},
            "15": {"selection_type": "EXACT_TARGET_CANDLE", "final": True},
            "30": {"selection_type": "EXACT_TARGET_CANDLE", "final": True},
            "60": {"selection_type": "EXACT_TARGET_CANDLE", "final": True},
        },
        "window_finalization": "last_known_price_at_target_v1",
    }
    assert not _is_valid_cohort_row(cancelled)
    # stats API는 Session 기반 — COMPLETED 필터만 직접 검증
    rows = [cancelled, completed]
    completed_n = sum(1 for r in rows if r.status == SHADOW_STATUS_COMPLETED)
    active_n = sum(1 for r in rows if r.status == SHADOW_STATUS_ACTIVE)
    assert completed_n == 1
    assert active_n == 0
    cancelled_in_completed = any(
        r.status == SHADOW_STATUS_COMPLETED and r.shadow_id == 52 for r in rows
    )
    assert cancelled_in_completed is False


@pytest.mark.asyncio
async def test_h_shadow52_equivalent_cancelled(monkeypatch):
    """shadow52 equivalent fixture — UPDATE production 52 금지."""
    t0 = datetime(2026, 8, 13, 21, 19, 40, 472000, tzinfo=timezone.utc)
    floor = t0.replace(second=0, microsecond=0)
    # 21:19..22:13 (55 bars) — 60m prior lag 360s
    bars = [_bar(floor + timedelta(minutes=i), "423") for i in range(0, 55)]
    absent = {floor + timedelta(minutes=i) for i in range(55, 61)}
    target_60 = floor + timedelta(minutes=60)
    resolve = {
        "bars": bars,
        "absent_by_target": {target_60: True},
        "source_unavailable_by_target": {},
        "resolve_detail": {
            target_60.isoformat(): {
                "status": FALLBACK_ABSENT_CONFIRMED,
                "api_rows": 5,
            }
        },
    }
    _patch_common(
        monkeypatch,
        bars,
        evidence=_ok_evidence(absent_ats=absent),
        resolve=resolve,
    )
    row = _row(t0, sid=9052)
    now = datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    result = await ev._apply_timeseries(row, persist=True)
    assert result.get("terminated") is True
    assert row.status == SHADOW_STATUS_CANCELLED
    assert row.evaluated_60m_at is None
    assert row.completed_at is None


def test_grace_formula_default_540():
    assert grace_seconds(interval_seconds=180.0) == 540.0


def test_candidate_blocks_when_prior_within_limit():
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    detail = {}
    computed = {
        "windows": {
            "60": {
                "status": "MISSING_CANDLE",
                "fallback_reason": FALLBACK_ABSENT_CONFIRMED,
                "target_candle_end": "2026-08-13T22:20:00+00:00",
                "target_at": "2026-08-13T22:19:40+00:00",
                "lag_seconds": 120,
            }
        },
        "path_quality": {
            "source_unavailable": False,
            "unresolved_missing": 0,
            "source_check_performed": True,
            "source_check_result": "OK",
        },
    }
    cand = is_permanent_absence_candidate(
        status=SHADOW_STATUS_ACTIVE,
        computed=computed,
        detail=detail,
        now=now,
    )
    assert cand.get("candidate") is False
    assert cand.get("reason_blocked") == "PRIOR_WITHIN_FALLBACK"
