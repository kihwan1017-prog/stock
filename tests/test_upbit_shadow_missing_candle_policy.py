"""Shadow LAST_KNOWN_PRICE_AT_TARGET — missing minute candle finalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    FALLBACK_ABSENT_CONFIRMED,
    MinuteBar,
    SELECTION_EXACT,
    SELECTION_LAST_KNOWN,
    compute_mfe_mae,
    compute_tp_sl,
    observe_windows,
    select_final_window_close,
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
from stock_platform.operation.upbit_opportunity_shadow.mismatch import (
    LEGACY_PROVENANCE_MISMATCH,
    MISMATCH_CODE,
    _compare,
)
from stock_platform.operation.upbit_opportunity_shadow.stats import (
    compute_shadow_stats,
)


def _bar(at: datetime, close: str, *, high: str | None = None, low: str | None = None) -> MinuteBar:
    c = Decimal(close)
    return MinuteBar(
        candle_at=at,
        open=c,
        high=Decimal(high) if high else c,
        low=Decimal(low) if low else c,
        close=c,
    )


def _series_with_gap(
    detected: datetime,
    *,
    gap_at: datetime,
    minutes: int = 65,
) -> list[MinuteBar]:
    """gap_at minute 을 제외한 actual candle path."""

    bars: list[MinuteBar] = []
    t0 = detected.replace(second=0, microsecond=0)
    for i in range(minutes):
        at = t0 + timedelta(minutes=i)
        if at == gap_at:
            continue
        # 기본 close=643, gap prior(12:52)=636 스타일 fixture 는 별도
        bars.append(_bar(at, "643"))
    return bars


def test_exact_target_candle_present():
    """1. exact target candle 존재 → EXACT."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    now = datetime(2026, 8, 13, 12, 54, tzinfo=timezone.utc)
    bars = [
        _bar(start - timedelta(minutes=1), "636"),
        _bar(start, "640"),
    ]
    sel = select_final_window_close(bars, target_at=target, now=now)
    assert sel.status == "OK"
    assert sel.selection_type == SELECTION_EXACT
    assert sel.bar is not None
    assert sel.bar.close == Decimal("640")
    assert sel.fallback_reason is None


def test_final_forbidden_while_target_candle_incomplete():
    """2. target candle 아직 미완료 → FINAL 금지 (prior 있어도)."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    now = datetime(2026, 8, 13, 12, 53, 30, tzinfo=timezone.utc)
    bars = [_bar(start - timedelta(minutes=1), "636")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
    )
    assert sel.status == "NOT_MATURED"
    assert sel.bar is None


def test_exact_after_completion():
    """3. target 완료 후 exact 존재 → EXACT."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(start, "641")]
    sel = select_final_window_close(bars, target_at=target, now=now)
    assert sel.status == "OK"
    assert sel.selection_type == SELECTION_EXACT
    assert sel.bar is not None and sel.bar.candle_at == start


def test_absent_confirmed_prior_1m():
    """4. exact absent confirmed + prior 1m → LAST_KNOWN."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = start - timedelta(minutes=1)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(prior, "636")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
    )
    assert sel.status == "OK"
    assert sel.selection_type == SELECTION_LAST_KNOWN
    assert sel.fallback_reason == FALLBACK_ABSENT_CONFIRMED
    assert sel.bar is not None
    assert sel.bar.candle_at == prior
    assert sel.lag_seconds == pytest.approx(60.0)


def test_absent_confirmed_prior_2m():
    """5. prior 2m → LAST_KNOWN."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = start - timedelta(minutes=2)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(prior, "630")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
    )
    assert sel.status == "OK"
    assert sel.selection_type == SELECTION_LAST_KNOWN
    assert sel.lag_seconds == pytest.approx(120.0)


def test_prior_within_180s_allowed():
    """6. prior <=180s → 허용."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = start - timedelta(seconds=180)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(prior, "629")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
        max_prior_lag_seconds=180,
    )
    assert sel.status == "OK"
    assert sel.selection_type == SELECTION_LAST_KNOWN


def test_prior_over_180s_missing():
    """7. prior >180s → MISSING."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = start - timedelta(seconds=181)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(prior, "620")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
        max_prior_lag_seconds=180,
    )
    assert sel.status == "MISSING_CANDLE"
    assert sel.bar is None


def test_source_unavailable_no_fallback():
    """8. source/API failure → fallback 금지."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(start - timedelta(minutes=1), "636")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
        source_unavailable=True,
    )
    assert sel.status == "SOURCE_UNAVAILABLE"
    assert sel.bar is None


def test_db_missing_but_api_exact_in_bars_uses_exact():
    """9. DB missing but API exact 가 bars 에 병합되면 exact 사용."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    # resolve 후 API bar 가 들어온 상태
    bars = [_bar(start, "650")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,  # 있어도 exact 우선
    )
    assert sel.selection_type == SELECTION_EXACT
    assert sel.bar is not None and sel.bar.close == Decimal("650")


def test_no_synthetic_candle_created():
    """10. missing minute synthetic candle 생성 없음."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = start - timedelta(minutes=1)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(prior, "636")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=True,
    )
    assert sel.bar is not None
    assert sel.bar.candle_at == prior
    assert sel.bar.candle_at != start
    # bars 입력에 12:53 이 추가되지 않음
    assert all(b.candle_at != start for b in bars)


def test_observe_detail_matches_observation_object():
    """11. detail/column 동일 observation."""

    detected = datetime(2026, 8, 13, 12, 23, 4, tzinfo=timezone.utc)
    gap = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = gap - timedelta(minutes=1)
    bars = [
        _bar(prior, "636"),
        _bar(gap + timedelta(minutes=1), "637"),
    ]
    key = gap.isoformat()
    obs = observe_windows(
        bars,
        detected_at=detected,
        entry=Decimal("643"),
        now=datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc),
        windows_minutes=(30,),
        absent_by_target={key: True},
    )[0]
    assert obs.final is True
    assert obs.selection_type == SELECTION_LAST_KNOWN
    assert obs.price == Decimal("636")
    assert float(obs.return_pct) == pytest.approx(-1.088647, rel=1e-5)


@pytest.mark.asyncio
async def test_duplicate_tick_idempotent_last_known(monkeypatch):
    """12. duplicate tick idempotent."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.publish_shadow_result",
        lambda *_a, **_k: None,
    )

    detected = datetime(2026, 8, 13, 12, 23, 4, tzinfo=timezone.utc)
    gap = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    bars = []
    t0 = detected.replace(second=0, microsecond=0)
    for i in range(66):
        at = t0 + timedelta(minutes=i)
        if at == gap:
            continue
        close = "636" if at == gap - timedelta(minutes=1) else "643"
        bars.append(_bar(at, close))

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def fake_resolve(session, **kwargs):
        start = gap
        return {
            "bars": bars,
            "absent_by_target": {start.isoformat(): True},
            "source_unavailable_by_target": {},
            "resolve_detail": {
                start.isoformat(): {"status": "TARGET_CANDLE_ABSENT_CONFIRMED"}
            },
            "orders_created": 0,
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.resolve_missing_target_minutes",
        fake_resolve,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=19,
        scanner_run_id="r",
        symbol="KRW-RE",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("643"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=detected,
        live_auto_start=False,
        evaluation_detail={},
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    session.commit = MagicMock()

    now = datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc)
    ev = UpbitOpportunityShadowEvaluator(session, now=now, allow_sync=False)
    await ev.evaluate_pending(notify=False)
    first_at = row.evaluated_30m_at
    first_ret = row.return_30m_pct
    assert first_ret == pytest.approx(-1.088647, rel=1e-5)
    w30 = (row.evaluation_detail or {})["windows"]["30"]
    assert w30["selection_type"] == SELECTION_LAST_KNOWN
    assert w30["return_pct"] == pytest.approx(first_ret)
    assert w30["final"] is True

    await ev.evaluate_pending(notify=False)
    assert row.evaluated_30m_at == first_at
    assert row.return_30m_pct == first_ret


@pytest.mark.asyncio
async def test_late_65m_historical_backfill_with_gap(monkeypatch):
    """13. late +65m historical backfill."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.publish_shadow_result",
        lambda *_a, **_k: None,
    )

    detected = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    gap = datetime(2026, 8, 13, 12, 30, tzinfo=timezone.utc)  # 30m target floor
    bars = _series_with_gap(detected, gap_at=gap, minutes=70)
    # prior close 구분
    bars = [
        b
        if b.candle_at != gap - timedelta(minutes=1)
        else _bar(gap - timedelta(minutes=1), "636")
        for b in bars
    ]

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    async def fake_resolve(session, **kwargs):
        starts = kwargs.get("candle_starts") or []
        absent = {s.isoformat(): True for s in starts}
        return {
            "bars": bars,
            "absent_by_target": absent,
            "source_unavailable_by_target": {},
            "resolve_detail": {},
            "orders_created": 0,
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.resolve_missing_target_minutes",
        fake_resolve,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=190,
        scanner_run_id="r",
        symbol="KRW-RE",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("643"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=detected,
        live_auto_start=False,
        evaluation_detail={},
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    session.commit = MagicMock()
    out = await UpbitOpportunityShadowEvaluator(
        session,
        now=detected + timedelta(minutes=65),
        allow_sync=False,
    ).evaluate_pending(notify=False)
    assert out["orders_created"] == 0
    assert row.status == SHADOW_STATUS_COMPLETED
    assert (row.evaluation_detail or {})["windows"]["30"][
        "selection_type"
    ] == SELECTION_LAST_KNOWN


def test_mfe_mae_uses_actual_candles_only():
    """14. MFE/MAE — actual candle only, no synthetic gap fill."""

    t0 = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    bars = [
        _bar(t0, "100", high="102", low="99"),
        # gap at t0+1 intentionally missing
        _bar(t0 + timedelta(minutes=2), "101", high="103", low="98"),
    ]
    mfe, mae, detail = compute_mfe_mae(
        bars,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0 + timedelta(minutes=2),
        now=t0 + timedelta(minutes=5),
    )
    assert detail["used"] == 2
    assert mfe == Decimal("3")
    assert mae == Decimal("-2")


def test_tp_sl_uses_actual_candles_only():
    """15. TP/SL regression — actual high/low only."""

    t0 = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    bars = [_bar(t0, "100", high="107", low="96")]
    r = compute_tp_sl(
        bars,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0,
        now=t0 + timedelta(minutes=2),
        tp_pct=6.0,
        sl_pct=3.0,
    )
    assert r.first_hit == "SAME_CANDLE_SL_CONSERVATIVE"


def test_shadow19_regression_fixture():
    """16. #19 regression fixture — LAST_KNOWN 12:52 close=636."""

    detected = datetime(2026, 8, 13, 12, 23, 4, tzinfo=timezone.utc)
    gap = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    prior = gap - timedelta(minutes=1)
    bars = [_bar(prior, "636")]
    obs = observe_windows(
        bars,
        detected_at=detected,
        entry=Decimal("643"),
        now=datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc),
        windows_minutes=(30,),
        absent_by_target={gap.isoformat(): True},
    )[0]
    assert obs.selection_type == SELECTION_LAST_KNOWN
    assert obs.observed_candle_at == prior
    assert obs.price == Decimal("636")
    assert float(obs.return_pct) == pytest.approx(-1.088647, rel=1e-5)
    assert obs.final is True


def test_shadow20_legacy_prior_fixture():
    """17. #20 legacy prior stamp 패턴 fixture."""

    detected = datetime(2026, 8, 13, 12, 40, 10, tzinfo=timezone.utc)
    gap = datetime(2026, 8, 13, 13, 10, tzinfo=timezone.utc)  # 30m floor
    prior = gap - timedelta(minutes=1)
    bars = [_bar(prior, "100")]
    obs = observe_windows(
        bars,
        detected_at=detected,
        entry=Decimal("101"),
        now=gap + timedelta(minutes=5),
        windows_minutes=(30,),
        absent_by_target={gap.isoformat(): True},
    )[0]
    assert obs.selection_type == SELECTION_LAST_KNOWN
    assert obs.observed_candle_at == prior


def test_shadow21_exact_control_fixture():
    """18. #21 EXACT_TARGET_CANDLE control sample."""

    detected = datetime(2026, 8, 13, 12, 23, 4, tzinfo=timezone.utc)
    exact = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    bars = [_bar(exact, "640")]
    obs = observe_windows(
        bars,
        detected_at=detected,
        entry=Decimal("643"),
        now=datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc),
        windows_minutes=(30,),
    )[0]
    assert obs.selection_type == SELECTION_EXACT
    assert obs.observed_candle_at == exact
    assert obs.final is True


def test_active_excluded_from_mismatch_count():
    """19. ACTIVE mismatch 제외."""

    session = MagicMock()
    active = SimpleNamespace(
        deleted_at=None,
        status=SHADOW_STATUS_ACTIVE,
        recommendation="ALLOW",
        evaluation_detail={
            "mismatch_watch": {"ok": False, "code": MISMATCH_CODE}
        },
        return_5m_pct=None,
        return_15m_pct=None,
        return_30m_pct=None,
        return_60m_pct=None,
        mfe_pct=None,
        mae_pct=None,
        tp_hit=None,
        sl_hit=None,
        completed_at=None,
        shadow_id=20,
        symbol="KRW-X",
    )
    completed = SimpleNamespace(
        deleted_at=None,
        status=SHADOW_STATUS_COMPLETED,
        recommendation="ALLOW",
        evaluation_detail={
            "mismatch_watch": {"ok": True, "code": LEGACY_PROVENANCE_MISMATCH}
        },
        return_5m_pct=0.0,
        return_15m_pct=0.0,
        return_30m_pct=-1.088647,
        return_60m_pct=0.0,
        mfe_pct=0.2,
        mae_pct=-0.2,
        tp_hit=False,
        sl_hit=False,
        completed_at=datetime.now(timezone.utc),
        shadow_id=19,
        symbol="KRW-RE",
    )
    session.scalars.return_value = [active, completed]
    stats = compute_shadow_stats(session)
    assert stats["active_count"] == 1
    assert stats["mismatch_count"] == 0  # LEGACY 는 numeric mismatch_count 제외


def test_compare_legacy_provenance_and_no_orders():
    """20. TradingOrder/Outbox 경로 없음 + legacy provenance 표기."""

    stored = {
        "return_5m_pct": -1.0,
        "return_15m_pct": -1.0,
        "return_30m_pct": -1.088647,
        "return_60m_pct": -1.0,
        "mfe_pct": 0.1,
        "mae_pct": -0.1,
        "tp_hit": False,
        "sl_hit": False,
    }
    recomputed = {
        "windows": {
            "5": {
                "return_pct": -1.0,
                "status": "OK",
                "final": True,
                "selection_type": SELECTION_EXACT,
                "lag_seconds": 4,
            },
            "15": {
                "return_pct": -1.0,
                "status": "OK",
                "final": True,
                "selection_type": SELECTION_EXACT,
                "lag_seconds": 4,
            },
            "30": {
                "return_pct": -1.088647,
                "status": "OK",
                "final": True,
                "selection_type": SELECTION_LAST_KNOWN,
                "lag_seconds": 60,
                "fallback_reason": FALLBACK_ABSENT_CONFIRMED,
            },
            "60": {
                "return_pct": -1.0,
                "status": "OK",
                "final": True,
                "selection_type": SELECTION_EXACT,
                "lag_seconds": 4,
            },
        },
        "mfe_pct": 0.1,
        "mae_pct": -0.1,
        "tp_sl": {"tp_hit": False, "sl_hit": False},
    }
    ok, diffs, provenance = _compare(
        stored,
        recomputed,
        tol=5e-4,
        stored_detail={"windows": {"30": {"final": True}}},  # legacy no type
    )
    assert ok is True
    assert diffs["return_30m_pct"]["match"] is True
    assert provenance["legacy"] is True
    assert diffs["return_30m_pct"]["selection_type"] == SELECTION_LAST_KNOWN


def test_unconfirmed_absent_no_fallback():
    """absent 미확정 시 prior 있어도 MISSING (단순 DB miss fallback 금지)."""

    target = datetime(2026, 8, 13, 12, 53, 4, tzinfo=timezone.utc)
    start = datetime(2026, 8, 13, 12, 53, tzinfo=timezone.utc)
    now = datetime(2026, 8, 13, 12, 54, 0, tzinfo=timezone.utc)
    bars = [_bar(start - timedelta(minutes=1), "636")]
    sel = select_final_window_close(
        bars,
        target_at=target,
        now=now,
        target_absent_confirmed=False,
    )
    assert sel.status == "MISSING_CANDLE"
    assert sel.bar is None
