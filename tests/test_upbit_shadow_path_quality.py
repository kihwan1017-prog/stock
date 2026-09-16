"""COV-A path quality pure computation + evaluator observability tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    compute_mfe_mae,
    compute_tp_sl,
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
    absent_ats_from_target_map,
    compute_path_quality,
    expected_minute_slots,
)


def _bar(at: datetime, px: str = "100") -> MinuteBar:
    d = Decimal(px)
    return MinuteBar(
        candle_at=at,
        open=d,
        high=d + Decimal("0.1"),
        low=d - Decimal("0.1"),
        close=d,
    )


def _full_bars(t0: datetime, n: int = 61) -> list[MinuteBar]:
    start = t0.replace(second=0, microsecond=0)
    return [_bar(start + timedelta(minutes=i), str(100 + i * 0.01)) for i in range(n)]


def test_expected_minutes_off_by_one_60m_window():
    t0 = datetime(2026, 8, 13, 4, 0, 30, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=5)
    slots = expected_minute_slots(detected_at=t0, end_at=terminal, now=now)
    # floor(detected)=04:00 … 05:00 inclusive → 61
    assert len(slots) == 61
    assert slots[0] == datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    assert slots[-1] == datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc)


def test_full_candles_unresolved_zero():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=1)
    bars = _full_bars(t0, 61)
    pq = compute_path_quality(
        detected_at=t0, end_at=terminal, now=now, bars=bars
    )
    assert pq.path_quality_version == PATH_QUALITY_VERSION
    assert pq.expected_minutes == 61
    assert pq.observed_candles == 61
    assert pq.source_absent_confirmed == 0
    assert pq.unresolved_missing == 0
    assert pq.coverage_ratio_raw == 1.0
    assert pq.coverage_ratio_resolved == 1.0
    assert pq.max_gap_minutes == 0


def test_db_missing_no_source_evidence_unresolved():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=1)
    bars = _full_bars(t0, 61)
    # drop 10 middle minutes
    drop = {t0 + timedelta(minutes=i) for i in range(20, 30)}
    bars = [b for b in bars if b.candle_at not in drop]
    pq = compute_path_quality(
        detected_at=t0, end_at=terminal, now=now, bars=bars
    )
    assert pq.observed_candles == 51
    assert pq.source_absent_confirmed == 0
    assert pq.unresolved_missing == 10
    assert pq.max_gap_minutes == 10


def test_source_absent_confirmed_reduces_unresolved_no_synthetic():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=1)
    bars = _full_bars(t0, 61)
    miss = t0 + timedelta(minutes=25)
    bars = [b for b in bars if b.candle_at != miss]
    pq = compute_path_quality(
        detected_at=t0,
        end_at=terminal,
        now=now,
        bars=bars,
        source_absent_confirmed_ats={miss},
    )
    assert pq.observed_candles == 60
    assert pq.source_absent_confirmed == 1
    assert pq.unresolved_missing == 0
    assert pq.coverage_ratio_resolved == 1.0
    # 관측 bar 수 증가 없음 (synthetic 없음)
    assert len(bars) == 60


def test_source_unavailable_observe_only():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=1)
    pq = compute_path_quality(
        detected_at=t0,
        end_at=terminal,
        now=now,
        bars=_full_bars(t0, 50),
        source_unavailable=True,
        sync_last_result="SYNC_FAILED:Timeout",
    )
    assert pq.source_unavailable is True
    assert pq.unresolved_missing > 0


def test_distributed_and_consecutive_gaps():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    terminal = t0 + timedelta(minutes=60)
    now = terminal + timedelta(minutes=1)
    bars = _full_bars(t0, 61)
    # consecutive 5 + isolated 1
    drop = {t0 + timedelta(minutes=i) for i in range(10, 15)}
    drop.add(t0 + timedelta(minutes=40))
    bars = [b for b in bars if b.candle_at not in drop]
    pq = compute_path_quality(
        detected_at=t0, end_at=terminal, now=now, bars=bars
    )
    assert pq.max_gap_minutes == 5
    assert pq.gap_count == 2
    assert pq.missing_range_count == 2


def test_absent_ats_from_target_map_iso():
    t = datetime(2026, 8, 13, 4, 5, tzinfo=timezone.utc)
    got = absent_ats_from_target_map({t.isoformat(): True, "skip": False})
    assert t in got


@pytest.mark.asyncio
async def test_evaluator_attaches_path_quality_without_changing_metrics(
    monkeypatch,
):
    """회귀: return/MFE/MAE/TP/SL/status 불변 + path_quality만 추가."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )

    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full_bars(t0, 65)
    now = t0 + timedelta(minutes=65)

    async def _fake_ensure(*_a, **_k):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def _fake_resolve2(session, **kwargs):
        return {
            "bars": list(kwargs.get("bars") or bars),
            "absent_by_target": {},
            "source_unavailable_by_target": {},
            "resolve_detail": {},
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.resolve_missing_target_minutes",
        _fake_resolve2,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=9001,
        scanner_run_id="cov-a",
        symbol="KRW-BTC",
        recommendation="ALLOW",
        detected_at=t0,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        live_auto_start=False,
        status=SHADOW_STATUS_ACTIVE,
        evaluation_detail={"windows": {}, "prices_seen": []},
    )
    session = MagicMock()
    ev = UpbitOpportunityShadowEvaluator(session, now=now, allow_sync=False)

    mfe, mae, _ = compute_mfe_mae(
        bars,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0 + timedelta(minutes=60),
        now=now,
    )
    tp_sl = compute_tp_sl(
        bars,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0 + timedelta(minutes=60),
        now=now,
        tp_pct=6.0,
        sl_pct=3.0,
    )

    result = await ev._apply_timeseries(row, persist=True)
    assert result["changed"] is True
    computed = result["computed"]
    assert computed["path_quality"]["path_quality_version"] == PATH_QUALITY_VERSION
    assert computed["path_quality"]["unresolved_missing"] == 0
    assert computed["mfe_pct"] == pytest.approx(float(mfe), rel=1e-6)
    assert computed["mae_pct"] == pytest.approx(float(mae), rel=1e-6)
    assert computed["tp_sl"]["tp_hit"] == tp_sl.tp_hit
    assert computed["tp_sl"]["sl_hit"] == tp_sl.sl_hit
    assert computed["tp_pct"] == 6.0
    assert computed["sl_pct"] == 3.0

    detail = row.evaluation_detail or {}
    assert "path_quality" in detail
    assert "windows" in detail
    assert detail.get("window_finalization") == "last_known_price_at_target_v1"
    assert row.evaluated_60m_at is not None
    assert row.status == SHADOW_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_path_gap_defers_completion(monkeypatch):
    """COV-B: unresolved_missing > 0 → ACTIVE DEFER (COMPLETED 금지)."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )

    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full_bars(t0, 65)
    drop = {t0 + timedelta(minutes=i) for i in range(5, 25)}
    bars = [b for b in bars if b.candle_at not in drop]
    now = t0 + timedelta(minutes=65)

    async def _fake_ensure(*_a, **_k):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def _fake_resolve2(session, **kwargs):
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

        # allow_sync=False path: no check → unresolved remains
        return list(kwargs.get("bars") or bars), SourceRangeEvidence(
            source_check_performed=False,
            source_check_result="SKIPPED_NO_SYNC",
        )

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.resolve_missing_target_minutes",
        _fake_resolve2,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.reconcile_observation_source",
        _fake_reconcile,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=9002,
        scanner_run_id="cov-b",
        symbol="KRW-ETH",
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
    assert pq["unresolved_missing"] > 0
    assert result.get("deferred") is True
    assert result["just_completed"] is False
    assert row.status == SHADOW_STATUS_ACTIVE
    assert row.evaluated_60m_at is None
    assert row.return_60m_pct is None
    defer = (row.evaluation_detail or {}).get("path_defer") or {}
    assert "PATH_UNRESOLVED_MISSING" in (defer.get("defer_reasons") or [])
    assert defer.get("defer_count") == 1
    assert "path_quality" in (row.evaluation_detail or {})
