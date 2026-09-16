"""COV-C source range reconciliation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator import (
    UpbitOpportunityShadowEvaluator,
)
from stock_platform.operation.upbit_opportunity_shadow.path_quality import (
    PATH_QUALITY_VERSION,
    compute_path_quality,
    expected_minute_slots,
)
from stock_platform.operation.upbit_opportunity_shadow.source_range_reconcile import (
    STATE_DB_MISSING_SOURCE_PRESENT,
    STATE_DB_PRESENT,
    STATE_SOURCE_ABSENT_CONFIRMED,
    STATE_SOURCE_NOT_CHECKED,
    STATE_SOURCE_UNAVAILABLE,
    classify_expected_minutes,
    dry_reconcile_from_sets,
)


def _bar(at: datetime, px: str = "100") -> MinuteBar:
    d = Decimal(px)
    return MinuteBar(
        candle_at=at,
        open=d,
        high=d,
        low=d,
        close=d,
    )


def test_classify_db_present_and_absent_and_missing_present():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    expected = [t0 + timedelta(minutes=i) for i in range(5)]
    db = {t0, t0 + timedelta(minutes=1)}
    source = {t0, t0 + timedelta(minutes=1), t0 + timedelta(minutes=2)}
    # missing 2 present in source; 3,4 absent in source
    c = classify_expected_minutes(
        expected=expected,
        db_ats=db,
        source_ats=source,
        check_performed=True,
        source_unavailable=False,
    )
    assert c[STATE_DB_PRESENT] == db
    assert c[STATE_DB_MISSING_SOURCE_PRESENT] == {t0 + timedelta(minutes=2)}
    assert c[STATE_SOURCE_ABSENT_CONFIRMED] == {
        t0 + timedelta(minutes=3),
        t0 + timedelta(minutes=4),
    }
    assert not c[STATE_SOURCE_NOT_CHECKED]
    assert not c[STATE_SOURCE_UNAVAILABLE]


def test_classify_unavailable_and_not_checked():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    expected = [t0, t0 + timedelta(minutes=1)]
    c1 = classify_expected_minutes(
        expected=expected,
        db_ats=set(),
        source_ats=None,
        check_performed=True,
        source_unavailable=True,
    )
    assert c1[STATE_SOURCE_UNAVAILABLE] == set(expected)

    c2 = classify_expected_minutes(
        expected=expected,
        db_ats=set(),
        source_ats=None,
        check_performed=False,
        source_unavailable=False,
    )
    assert c2[STATE_SOURCE_NOT_CHECKED] == set(expected)


def test_path_quality_v2_absent_reduces_unresolved():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=1)
    bars = [_bar(t0 + timedelta(minutes=i)) for i in range(60)]  # miss last
    miss = t0 + timedelta(minutes=60)
    pq = compute_path_quality(
        detected_at=t0,
        end_at=terminal,
        now=now,
        bars=bars,
        source_absent_confirmed_ats={miss},
        source_check_performed=True,
        source_check_result="OK",
        source_candle_count=60,
    )
    assert PATH_QUALITY_VERSION == "technical_path_quality_v2"
    assert pq.path_quality_version == PATH_QUALITY_VERSION
    assert pq.unresolved_missing == 0
    assert pq.source_absent_confirmed == 1
    assert pq.source_check_performed is True


def test_no_synthetic_from_absent():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=5)
    now = terminal + timedelta(minutes=1)
    expected = expected_minute_slots(
        detected_at=t0, end_at=terminal, now=now
    )
    bars = [_bar(t0)]
    pq = compute_path_quality(
        detected_at=t0,
        end_at=terminal,
        now=now,
        bars=bars,
        source_absent_confirmed_ats=set(expected[1:]),
    )
    assert pq.observed_candles == 1
    assert len(bars) == 1


@pytest.mark.asyncio
async def test_evaluator_absent_confirmed_still_completes_under_cov_b(monkeypatch):
    """COV-C absence evidence → unresolved=0 → COV-B gate PASS → COMPLETED."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = [_bar(t0 + timedelta(minutes=i), str(100 + i)) for i in range(65)]
    # hole → after reconcile still may have unresolved if no sync
    drop = {t0 + timedelta(minutes=i) for i in range(10, 20)}
    bars = [b for b in bars if b.candle_at not in drop]
    now = t0 + timedelta(minutes=65)

    async def _fake_ensure(*_a, **_k):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def _fake_resolve(session, **kwargs):
        return {
            "bars": list(kwargs.get("bars") or bars),
            "absent_by_target": {},
            "source_unavailable_by_target": {},
            "resolve_detail": {},
        }

    async def _fake_reconcile(session, **kwargs):
        from stock_platform.operation.upbit_opportunity_shadow.source_range_reconcile import (
            SourceRangeEvidence,
        )

        # simulate successful range: all holes SOURCE_ABSENT_CONFIRMED
        ev = SourceRangeEvidence(
            source_check_performed=True,
            source_check_result="OK",
            source_candle_count=51,
            source_absent_confirmed_ats=set(drop),
            requests=1,
        )
        return list(kwargs.get("bars") or bars), ev

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.resolve_missing_target_minutes",
        _fake_resolve,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.reconcile_observation_source",
        _fake_reconcile,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=9101,
        scanner_run_id="cov-c",
        symbol="KRW-BTC",
        recommendation="ALLOW",
        detected_at=t0,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        live_auto_start=False,
        status=SHADOW_STATUS_ACTIVE,
        evaluation_detail={"windows": {}},
    )
    ev = UpbitOpportunityShadowEvaluator(
        MagicMock(), now=now, allow_sync=False
    )
    result = await ev._apply_timeseries(row, persist=True)
    pq = result["computed"]["path_quality"]
    assert pq["path_quality_version"] == "technical_path_quality_v2"
    assert pq["source_absent_confirmed"] == 10
    assert pq["unresolved_missing"] == 0
    assert pq["source_check_performed"] is True
    # COV-B gate PASS (absent reduces unresolved)
    assert result.get("deferred") is not True
    assert row.status == SHADOW_STATUS_COMPLETED
    assert result["just_completed"] is True
