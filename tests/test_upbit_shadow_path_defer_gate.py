"""COV-B path completeness defer gate tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import MinuteBar
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
    path_completeness_pass,
    path_defer_reasons,
)
from stock_platform.operation.upbit_opportunity_shadow.source_range_reconcile import (
    SourceRangeEvidence,
)


def _bar(at: datetime, px: str = "100") -> MinuteBar:
    d = Decimal(px)
    return MinuteBar(candle_at=at, open=d, high=d, low=d, close=d)


def _full(t0: datetime, n: int = 65) -> list[MinuteBar]:
    return [_bar(t0 + timedelta(minutes=i), str(100 + i * 0.01)) for i in range(n)]


def test_path_completeness_pass_predicate():
    assert path_completeness_pass(
        {"unresolved_missing": 0, "source_unavailable": False}
    )
    assert not path_completeness_pass(
        {"unresolved_missing": 1, "source_unavailable": False}
    )
    assert not path_completeness_pass(
        {"unresolved_missing": 0, "source_unavailable": True}
    )
    assert "SOURCE_UNAVAILABLE" in path_defer_reasons(
        {"unresolved_missing": 0, "source_unavailable": True}
    )


def _patch_common(monkeypatch, bars, *, evidence: SourceRangeEvidence):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )

    async def _ensure(*_a, **_k):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def _resolve(session, **kwargs):
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


def _row(t0: datetime, sid: int = 9200) -> UpbitOpportunityShadowEntity:
    return UpbitOpportunityShadowEntity(
        shadow_id=sid,
        scanner_run_id="cov-b",
        symbol="KRW-BTC",
        recommendation="ALLOW",
        detected_at=t0,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        live_auto_start=False,
        status=SHADOW_STATUS_ACTIVE,
        evaluation_detail={"windows": {}},
    )


@pytest.mark.asyncio
async def test_case_a_complete_path_allows_completed(monkeypatch):
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full(t0)
    now = t0 + timedelta(minutes=65)
    _patch_common(
        monkeypatch,
        bars,
        evidence=SourceRangeEvidence(
            source_check_performed=False,
            source_check_result="SKIPPED_NO_MISSING",
        ),
    )
    row = _row(t0, 9201)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    out = await ev._apply_timeseries(row, persist=True)
    assert out.get("deferred") is not True
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.evaluated_60m_at is not None
    assert out["just_completed"] is True


@pytest.mark.asyncio
async def test_case_b_unresolved_defers(monkeypatch):
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full(t0)
    drop = {t0 + timedelta(minutes=i) for i in range(10, 15)}
    bars = [b for b in bars if b.candle_at not in drop]
    now = t0 + timedelta(minutes=65)
    _patch_common(
        monkeypatch,
        bars,
        evidence=SourceRangeEvidence(
            source_check_performed=False,
            source_check_result="SKIPPED_NO_SYNC",
        ),
    )
    row = _row(t0, 9202)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    out = await ev._apply_timeseries(row, persist=True)
    assert out["deferred"] is True
    assert row.status == SHADOW_STATUS_ACTIVE
    assert row.evaluated_60m_at is None
    assert (row.evaluation_detail or {}).get("path_defer", {}).get("defer_count") == 1


@pytest.mark.asyncio
async def test_case_c_source_unavailable_defers(monkeypatch):
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full(t0, 50)
    now = t0 + timedelta(minutes=65)
    _patch_common(
        monkeypatch,
        bars,
        evidence=SourceRangeEvidence(
            source_check_performed=True,
            source_check_result="UNAVAILABLE",
            source_unavailable=True,
            requests=1,
            error_code="Timeout",
        ),
    )
    row = _row(t0, 9203)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=True)
    out = await ev._apply_timeseries(row, persist=True)
    assert out["deferred"] is True
    assert row.status == SHADOW_STATUS_ACTIVE
    reasons = (row.evaluation_detail or {}).get("path_defer", {}).get(
        "defer_reasons"
    ) or []
    assert "SOURCE_UNAVAILABLE" in reasons


@pytest.mark.asyncio
async def test_case_d_absent_confirmed_allows_complete(monkeypatch):
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full(t0)
    drop = {t0 + timedelta(minutes=i) for i in range(20, 25)}
    bars = [b for b in bars if b.candle_at not in drop]
    now = t0 + timedelta(minutes=65)
    _patch_common(
        monkeypatch,
        bars,
        evidence=SourceRangeEvidence(
            source_check_performed=True,
            source_check_result="OK",
            source_absent_confirmed_ats=set(drop),
            source_candle_count=56,
            requests=1,
        ),
    )
    row = _row(t0, 9204)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    out = await ev._apply_timeseries(row, persist=True)
    assert out.get("deferred") is not True
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.evaluated_60m_at is not None
    pq = (row.evaluation_detail or {}).get("path_quality") or {}
    assert pq.get("unresolved_missing") == 0
    assert pq.get("source_absent_confirmed") == 5


@pytest.mark.asyncio
async def test_case_e_not_checked_missing_defers(monkeypatch):
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _full(t0, 40)
    now = t0 + timedelta(minutes=65)
    _patch_common(
        monkeypatch,
        bars,
        evidence=SourceRangeEvidence(
            source_check_performed=False,
            source_check_result="SKIPPED_NO_SYNC",
        ),
    )
    row = _row(t0, 9205)
    out = await UpbitOpportunityShadowEvaluator(
        MagicMock(), now=now, allow_sync=False
    )._apply_timeseries(row, persist=True)
    assert out["deferred"] is True
    assert row.status == SHADOW_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_retry_defer_then_complete(monkeypatch):
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars_hole = [b for b in _full(t0) if b.candle_at != t0 + timedelta(minutes=30)]
    bars_full = _full(t0)
    now = t0 + timedelta(minutes=65)
    state = {
        "bars": bars_hole,
        "evidence": SourceRangeEvidence(
            source_check_performed=False, source_check_result="SKIPPED_NO_SYNC"
        ),
    }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )

    async def _ensure(*_a, **_k):
        return {"bars": state["bars"], "sync": None, "count": len(state["bars"])}

    async def _resolve(session, **kwargs):
        return {
            "bars": list(kwargs.get("bars") or state["bars"]),
            "absent_by_target": {},
            "source_unavailable_by_target": {},
            "resolve_detail": {},
        }

    async def _reconcile(session, **kwargs):
        return list(kwargs.get("bars") or state["bars"]), state["evidence"]

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

    row = _row(t0, 9206)
    ev = UpbitOpportunityShadowEvaluator(MagicMock(), now=now, allow_sync=False)
    out1 = await ev._apply_timeseries(row, persist=True)
    assert out1["deferred"] is True
    assert row.status == SHADOW_STATUS_ACTIVE
    assert (row.evaluation_detail or {}).get("path_defer", {}).get("defer_count") == 1

    state["bars"] = bars_full
    state["evidence"] = SourceRangeEvidence(
        source_check_performed=False, source_check_result="SKIPPED_NO_MISSING"
    )
    out2 = await ev._apply_timeseries(row, persist=True)
    assert out2.get("deferred") is not True
    assert out2["just_completed"] is True
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.evaluated_60m_at is not None
    assert (row.evaluation_detail or {}).get("path_defer", {}).get("resolved") is True
