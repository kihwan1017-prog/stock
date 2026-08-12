"""Shadow evaluator timeseries — minute candle historical backfill tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    compute_mfe_mae,
    compute_tp_sl,
    observe_windows,
    return_pct,
    select_close_at_or_before,
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


def _bar(at: datetime, o: str, h: str, low: str, c: str) -> MinuteBar:
    return MinuteBar(
        candle_at=at,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def _series(
    t0: datetime,
    *,
    minutes: int = 65,
    base: Decimal = Decimal("100"),
) -> list[MinuteBar]:
    """분별 close가 다른 시계열 — 5/15/30/60 구분 가능."""

    bars: list[MinuteBar] = []
    for i in range(minutes + 1):
        at = t0.replace(second=0, microsecond=0) + timedelta(minutes=i)
        # close = base + i*0.1 → window마다 다른 가격
        close = base + Decimal(i) * Decimal("0.1")
        high = close + Decimal("0.05")
        low = close - Decimal("0.05")
        bars.append(_bar(at, str(close), str(high), str(low), str(close)))
    return bars


def test_return_pct_decimal():
    assert return_pct(Decimal("100"), Decimal("101")) == Decimal("1")


def test_select_close_prior_completed_not_future():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _series(t0, minutes=10)
    now = t0 + timedelta(minutes=10)
    target = t0 + timedelta(minutes=5)
    bar, status = select_close_at_or_before(bars, target_at=target, now=now)
    assert status == "OK"
    assert bar is not None
    assert bar.candle_at == t0 + timedelta(minutes=5)

    # 미래 target
    bar2, status2 = select_close_at_or_before(
        bars, target_at=now + timedelta(minutes=5), now=now
    )
    assert status2 == "NOT_MATURED"
    assert bar2 is None


def test_missing_exact_uses_nearest_prior():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    # 5분봉 누락 — 4분만 존재
    bars = [_series(t0, minutes=4)[i] for i in range(5)]
    now = t0 + timedelta(minutes=10)
    target = t0 + timedelta(minutes=5)
    bar, status = select_close_at_or_before(
        bars, target_at=target, now=now, max_lag_minutes=3
    )
    assert status == "OK"
    assert bar is not None
    assert bar.candle_at == t0 + timedelta(minutes=4)


def test_observe_windows_distinct_prices_at_plus_65():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _series(t0, minutes=65)
    now = t0 + timedelta(minutes=65)
    obs = observe_windows(
        bars,
        detected_at=t0,
        entry=Decimal("100"),
        now=now,
        windows_minutes=(5, 15, 30, 60),
    )
    prices = [o.price for o in obs]
    assert all(p is not None for p in prices)
    assert len(set(prices)) == 4  # 서로 다른 candle close
    assert obs[0].minutes == 5
    assert obs[0].price == Decimal("100.5")  # +5 * 0.1
    assert obs[3].price == Decimal("106.0")  # +60 * 0.1


def test_mfe_mae_from_high_low():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = [
        _bar(t0, "100", "102", "99", "100.5"),
        _bar(t0 + timedelta(minutes=1), "100.5", "103", "98", "101"),
        _bar(t0 + timedelta(minutes=2), "101", "101.5", "97", "99"),
    ]
    now = t0 + timedelta(minutes=5)
    mfe, mae, detail = compute_mfe_mae(
        bars,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0 + timedelta(minutes=2),
        now=now,
    )
    assert mfe == Decimal("3")  # high 103
    assert mae == Decimal("-3")  # low 97
    assert detail["used"] == 3


def test_tp_sl_order_and_same_candle_conservative():
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    # SL first then TP
    bars = [
        _bar(t0, "100", "100.5", "96.5", "97"),  # SL -3.5%
        _bar(t0 + timedelta(minutes=1), "97", "107", "97", "106"),  # TP
    ]
    now = t0 + timedelta(minutes=5)
    r = compute_tp_sl(
        bars,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0 + timedelta(minutes=2),
        now=now,
        tp_pct=6.0,
        sl_pct=3.0,
    )
    assert r.sl_hit is True
    assert r.tp_hit is True
    assert r.first_hit == "SL"

    # same candle both
    same = [
        _bar(t0, "100", "107", "96", "101"),
    ]
    r2 = compute_tp_sl(
        same,
        entry=Decimal("100"),
        start_at=t0,
        end_at=t0,
        now=now,
        tp_pct=6.0,
        sl_pct=3.0,
    )
    assert r2.tp_hit and r2.sl_hit
    assert r2.first_hit == "SAME_CANDLE_SL_CONSERVATIVE"


@pytest.mark.asyncio
async def test_evaluate_at_5m_and_late_65m_backfill(monkeypatch):
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
    bars = _series(t0, minutes=65)

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=1,
        scanner_run_id="r1",
        symbol="KRW-AAA",
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

    # exactly +5m — candle@T+5는 아직 미완료 → T+4 completed close 사용
    ev5 = UpbitOpportunityShadowEvaluator(
        session, now=t0 + timedelta(minutes=5), allow_sync=False
    )
    out5 = await ev5.evaluate_pending(notify=False)
    assert out5["orders_created"] == 0
    assert row.return_5m_pct == pytest.approx(0.4, rel=1e-4)
    assert row.return_15m_pct is None
    assert row.status == SHADOW_STATUS_ACTIVE

    # late +65m → remaining windows distinct (5m은 idempotent 유지)
    ev65 = UpbitOpportunityShadowEvaluator(
        session, now=t0 + timedelta(minutes=65), allow_sync=False
    )
    out65 = await ev65.evaluate_pending(notify=False)
    assert out65["completed"] == 1
    assert row.status == SHADOW_STATUS_COMPLETED
    assert row.return_5m_pct == pytest.approx(0.4, rel=1e-4)  # 덮어쓰지 않음
    assert row.return_15m_pct == pytest.approx(1.5, rel=1e-4)
    assert row.return_30m_pct == pytest.approx(3.0, rel=1e-4)
    assert row.return_60m_pct == pytest.approx(6.0, rel=1e-4)
    assert float(row.price_15m) != float(row.price_30m) != float(row.price_60m)


@pytest.mark.asyncio
async def test_idempotent_and_completed_dry_safe(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_sl_pct=3.0,
            upbit_scanner_shadow_tp_pct=6.0,
        ),
    )
    t0 = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    bars = _series(t0, minutes=65)

    async def fake_load(session, **kwargs):
        return {"bars": bars, "sync": None, "count": len(bars)}

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator.ensure_shadow_minute_bars",
        fake_load,
    )

    row = UpbitOpportunityShadowEntity(
        shadow_id=7,
        scanner_run_id="r1",
        symbol="KRW-AAA",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=t0,
        live_auto_start=False,
        evaluation_detail={},
        return_5m_pct=0.5,
        price_5m=Decimal("100.5"),
        evaluated_5m_at=t0 + timedelta(minutes=5),
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    session.commit = MagicMock()
    session.get.return_value = row

    ev = UpbitOpportunityShadowEvaluator(
        session, now=t0 + timedelta(minutes=65), allow_sync=False
    )
    await ev.evaluate_pending(notify=False)
    # 기존 5m 유지 (idempotent)
    assert row.return_5m_pct == 0.5
    assert row.status == SHADOW_STATUS_COMPLETED

    # dry recompute — persist false, COMPLETED 안전
    dry = await ev.dry_recompute(7)
    assert dry["ok"] is True
    assert dry["persist"] is False
    assert dry["orders_created"] == 0
    assert dry["recomputed"]["windows"]["5"]["return_pct"] == pytest.approx(
        0.5, rel=1e-4
    )
    assert dry["recomputed"]["windows"]["60"]["return_pct"] == pytest.approx(
        6.0, rel=1e-4
    )


@pytest.mark.asyncio
async def test_no_orders_contract():
    session = MagicMock()
    session.scalars.return_value = []
    out = await UpbitOpportunityShadowEvaluator(session).evaluate_pending(
        notify=False
    )
    assert out["orders_created"] == 0
    assert out["completed"] == 0
