"""Shadow window finalization — target candle close boundary race tests."""

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
    observe_windows,
    select_final_window_close,
    target_candle_bounds,
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
    MISMATCH_CODE,
    _compare,
)
from stock_platform.operation.upbit_opportunity_shadow.stats import (
    compute_shadow_stats,
)


def _bar(at: datetime, o: str, h: str, low: str, c: str) -> MinuteBar:
    return MinuteBar(
        candle_at=at,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def _doge_like_series(detected: datetime) -> list[MinuteBar]:
    """shadow #3 재현용 — 30m target 분봉 close=98.2, prior=98.1."""

    t0 = detected.replace(second=0, microsecond=0)
    bars: list[MinuteBar] = []
    for i in range(0, 62):
        at = t0 + timedelta(minutes=i)
        if at == datetime(2026, 8, 12, 22, 39, tzinfo=timezone.utc):
            close = Decimal("98.1")
        elif at == datetime(2026, 8, 12, 22, 40, tzinfo=timezone.utc):
            close = Decimal("98.2")
        else:
            close = Decimal("98.1")
        bars.append(
            _bar(at, str(close), str(close + Decimal("0.1")), str(close), str(close))
        )
    return bars


def test_target_candle_bounds_for_304052():
    target = datetime(2026, 8, 12, 22, 40, 52, tzinfo=timezone.utc)
    start, end = target_candle_bounds(target)
    assert start == datetime(2026, 8, 12, 22, 40, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 12, 22, 41, tzinfo=timezone.utc)


def test_final_not_at_exact_target_time():
    """1. target=22:40:52 / now=22:40:52 → 30m finalization 금지."""

    detected = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    target = detected + timedelta(minutes=30)
    now = target
    bars = _doge_like_series(detected)
    bar, status = select_final_window_close(bars, target_at=target, now=now)
    assert status == "NOT_MATURED"
    assert bar is None


def test_final_not_at_224059():
    """2. now=22:40:59 → still NOT_MATURED."""

    detected = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    target = detected + timedelta(minutes=30)
    now = datetime(2026, 8, 12, 22, 40, 59, tzinfo=timezone.utc)
    bars = _doge_like_series(detected)
    bar, status = select_final_window_close(bars, target_at=target, now=now)
    assert status == "NOT_MATURED"
    assert bar is None


def test_final_at_224100_uses_2240_candle():
    """3/4. now>=22:41 → 22:40 candle, prior 22:39 미사용."""

    detected = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    target = detected + timedelta(minutes=30)
    now = datetime(2026, 8, 12, 22, 41, 0, tzinfo=timezone.utc)
    bars = _doge_like_series(detected)
    bar, status = select_final_window_close(bars, target_at=target, now=now)
    assert status == "OK"
    assert bar is not None
    assert bar.candle_at == datetime(2026, 8, 12, 22, 40, tzinfo=timezone.utc)
    assert bar.close == Decimal("98.2")


def test_observe_not_matured_before_candle_close():
    detected = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    bars = _doge_like_series(detected)
    obs = observe_windows(
        bars,
        detected_at=detected,
        entry=Decimal("98.1"),
        now=datetime(2026, 8, 12, 22, 40, 52, tzinfo=timezone.utc),
        windows_minutes=(30,),
    )
    assert obs[0].status == "NOT_MATURED"
    assert obs[0].final is False
    assert obs[0].price is None


@pytest.mark.asyncio
async def test_late_evaluate_backfill_all_windows(monkeypatch):
    """5. +65m late evaluate → historical backfill."""

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

    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(66):
        at = t0 + timedelta(minutes=i)
        close = Decimal("100") + Decimal(i) * Decimal("0.1")
        bars.append(_bar(at, str(close), str(close), str(close), str(close)))

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=100,
        scanner_run_id="r",
        symbol="KRW-T",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=t0,
        live_auto_start=False,
        evaluation_detail={},
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    session.commit = MagicMock()

    ev = UpbitOpportunityShadowEvaluator(
        session, now=t0 + timedelta(minutes=65), allow_sync=False
    )
    out = await ev.evaluate_pending(notify=False)
    assert out["orders_created"] == 0
    assert out["completed"] == 1
    assert row.return_5m_pct == pytest.approx(0.5)
    assert row.return_15m_pct == pytest.approx(1.5)
    assert row.return_30m_pct == pytest.approx(3.0)
    assert row.return_60m_pct == pytest.approx(6.0)
    # 6. detail/column 동일
    w = (row.evaluation_detail or {})["windows"]
    assert w["30"]["return_pct"] == pytest.approx(row.return_30m_pct)
    assert w["30"]["final"] is True
    assert row.evaluated_30m_at is not None  # 7.


@pytest.mark.asyncio
async def test_no_stamp_before_candle_close_then_idempotent(monkeypatch):
    """1→3→8. 미완료 시 stamp 금지, 완료 후 idempotent."""

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

    detected = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    bars = _doge_like_series(detected)

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=3,
        scanner_run_id="r",
        symbol="KRW-DOGE",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("98.1"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=detected,
        live_auto_start=False,
        evaluation_detail={},
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    session.commit = MagicMock()

    # race 시점 — 30m 미확정
    ev_early = UpbitOpportunityShadowEvaluator(
        session,
        now=datetime(2026, 8, 12, 22, 40, 52, tzinfo=timezone.utc),
        allow_sync=False,
    )
    await ev_early.evaluate_pending(notify=False)
    assert row.return_30m_pct is None
    assert row.evaluated_30m_at is None
    assert (row.evaluation_detail or {}).get("windows", {}).get("30", {}).get(
        "status"
    ) == "NOT_MATURED"

    # candle close 이후 final
    ev_ok = UpbitOpportunityShadowEvaluator(
        session,
        now=datetime(2026, 8, 12, 22, 41, 0, tzinfo=timezone.utc),
        allow_sync=False,
    )
    await ev_ok.evaluate_pending(notify=False)
    assert row.return_30m_pct == pytest.approx(0.101937, rel=1e-4)
    assert float(row.price_30m) == pytest.approx(98.2)
    first_at = row.evaluated_30m_at
    detail_ret = (row.evaluation_detail or {})["windows"]["30"]["return_pct"]
    assert detail_ret == pytest.approx(row.return_30m_pct)

    # duplicate tick idempotent
    await ev_ok.evaluate_pending(notify=False)
    assert row.evaluated_30m_at == first_at
    assert row.return_30m_pct == pytest.approx(0.101937, rel=1e-4)


def test_mfe_mae_tp_sl_regression():
    """9/10. MFE/MAE · TP/SL 정책 회귀."""

    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars_mfe = [
        _bar(t0, "100", "102", "99", "100.5"),
        _bar(t0 + timedelta(minutes=1), "100.5", "103", "98", "101"),
        _bar(t0 + timedelta(minutes=2), "101", "101.5", "97", "99"),
    ]
    now = t0 + timedelta(minutes=5)
    mfe, mae, _ = compute_mfe_mae(
        bars_mfe,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0 + timedelta(minutes=2),
        now=now,
    )
    assert mfe == Decimal("3")
    assert mae == Decimal("-3")

    same = [_bar(t0, "100", "107", "96", "101")]
    r = compute_tp_sl(
        same,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0,
        now=now,
        tp_pct=6.0,
        sl_pct=3.0,
    )
    assert r.sl_hit is True
    assert r.tp_hit is True
    assert r.first_hit == "SAME_CANDLE_SL_CONSERVATIVE"


def test_active_excluded_from_mismatch_count():
    """11. ACTIVE 는 mismatch_count 제외."""

    session = MagicMock()
    active = SimpleNamespace(
        deleted_at=None,
        status="ACTIVE",
        recommendation="ALLOW",
        evaluation_detail={},
        return_5m_pct=None,
        return_15m_pct=None,
        return_30m_pct=None,
        return_60m_pct=None,
        mfe_pct=None,
        mae_pct=None,
        tp_hit=None,
        sl_hit=None,
        completed_at=None,
        shadow_id=19,
        symbol="KRW-RE",
    )
    completed_mismatch = SimpleNamespace(
        deleted_at=None,
        status=SHADOW_STATUS_COMPLETED,
        recommendation="ALLOW",
        evaluation_detail={
            "mismatch_watch": {"ok": False, "code": MISMATCH_CODE}
        },
        return_5m_pct=0.0,
        return_15m_pct=0.0,
        return_30m_pct=0.0,
        return_60m_pct=0.1,
        mfe_pct=0.2,
        mae_pct=-0.2,
        tp_hit=False,
        sl_hit=False,
        completed_at=datetime.now(timezone.utc),
        shadow_id=3,
        symbol="KRW-DOGE",
    )
    session.scalars.return_value = [active, completed_mismatch]
    stats = compute_shadow_stats(session)
    assert stats["active_count"] == 1
    assert stats["completed_count"] == 1
    assert stats["mismatch_count"] == 1


def test_completed_true_mismatch_detected():
    """12. COMPLETED true mismatch 탐지."""

    stored = {
        "return_5m_pct": -0.101937,
        "return_15m_pct": 0.0,
        "return_30m_pct": 0.0,
        "return_60m_pct": 0.101937,
        "mfe_pct": 0.203874,
        "mae_pct": -0.203874,
        "tp_hit": False,
        "sl_hit": False,
    }
    recomputed = {
        "windows": {
            "5": {"return_pct": -0.101937},
            "15": {"return_pct": 0.0},
            "30": {"return_pct": 0.101937},
            "60": {"return_pct": 0.101937},
        },
        "mfe_pct": 0.203874,
        "mae_pct": -0.203874,
        "tp_sl": {"tp_hit": False, "sl_hit": False},
    }
    ok, diffs = _compare(stored, recomputed, tol=5e-4)
    assert ok is False
    assert diffs["return_30m_pct"]["match"] is False


@pytest.mark.asyncio
async def test_shadow3_fixture_regression_then_fixed_path(monkeypatch):
    """13/14. #3 race 재현 방지 + 신규 경로 mismatch=0."""

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

    detected = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    bars = _doge_like_series(detected)

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=203,
        scanner_run_id="r",
        symbol="KRW-DOGE",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("98.1"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=detected,
        live_auto_start=False,
        evaluation_detail={},
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    session.commit = MagicMock()
    session.get.return_value = row

    # 잘못된 early stamp 시점에서는 값 없음
    await UpbitOpportunityShadowEvaluator(
        session,
        now=datetime(2026, 8, 12, 22, 40, 52, tzinfo=timezone.utc),
        allow_sync=False,
    ).evaluate_pending(notify=False)
    assert row.return_30m_pct is None

    # 완료 후 전 window backfill
    await UpbitOpportunityShadowEvaluator(
        session,
        now=datetime(2026, 8, 12, 23, 12, 0, tzinfo=timezone.utc),
        allow_sync=False,
    ).evaluate_pending(notify=False)
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.return_30m_pct == pytest.approx(0.101937, rel=1e-4)

    dry = await UpbitOpportunityShadowEvaluator(
        session,
        now=datetime(2026, 8, 12, 23, 12, 0, tzinfo=timezone.utc),
        allow_sync=False,
    ).dry_recompute(203)
    assert dry["orders_created"] == 0
    assert dry["persist"] is False
    stored = {
        "return_5m_pct": row.return_5m_pct,
        "return_15m_pct": row.return_15m_pct,
        "return_30m_pct": row.return_30m_pct,
        "return_60m_pct": row.return_60m_pct,
        "mfe_pct": row.mfe_pct,
        "mae_pct": row.mae_pct,
        "tp_hit": row.tp_hit,
        "sl_hit": row.sl_hit,
    }
    ok, _ = _compare(stored, dry["recomputed"], tol=5e-4)
    assert ok is True


@pytest.mark.asyncio
async def test_no_order_side_effects(monkeypatch):
    """15–18. 주문/Outbox/adapter 경로 0."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )
    session = MagicMock()
    session.scalars.return_value = []
    out = await UpbitOpportunityShadowEvaluator(session).evaluate_pending(
        notify=False
    )
    assert out["orders_created"] == 0
