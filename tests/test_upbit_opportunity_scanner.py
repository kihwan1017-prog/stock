"""UPBIT Opportunity Scanner v0 ??focused tests (?ㅼ＜臾??놁쓬)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_scanner.indicators import (
    is_abnormal_spike,
    upbit_minute_rows_to_candles,
)
from stock_platform.operation.upbit_opportunity_scanner.policy import (
    ScannerPolicy,
    load_scanner_policy,
    score_candidate,
)
from stock_platform.operation.upbit_opportunity_scanner.service import (
    UpbitOpportunityScannerService,
)
from stock_platform.operation.upbit_opportunity_scanner.universe import (
    load_krw_universe,
)


def _policy(**overrides) -> ScannerPolicy:
    base = dict(
        enabled=False,
        mode="SHADOW_ONLY",
        interval_seconds=900.0,
        min_24h_trade_value_krw=5_000_000_000.0,
        top_n=5,
        cooldown_seconds=1800.0,
        max_spike_pct=15.0,
        technical_candidate_limit=10,
        min_candles=30,
        candle_unit=1,
        ai_enabled=True,
        notify_hold=False,
        exclude_stablecoins=True,
        exclude_caution_markets=True,
        ai_backfill_enabled=True,
        candle_concurrency=8,
        ai_concurrency=2,
        candle_timeout_seconds=12.0,
    )
    base.update(overrides)
    return ScannerPolicy(**base)


def test_policy_defaults_from_settings():
    settings = SimpleNamespace(
        upbit_opportunity_scanner_enabled=False,
        upbit_opportunity_scanner_mode="SHADOW_ONLY",
        upbit_opportunity_scanner_interval_seconds=900,
        upbit_scanner_min_24h_trade_value_krw=5_000_000_000,
        upbit_scanner_top_n=5,
        upbit_scanner_symbol_cooldown_seconds=1800,
        upbit_scanner_max_spike_pct=15,
        upbit_scanner_technical_candidate_limit=30,
        upbit_scanner_min_candles=30,
        upbit_scanner_candle_unit=1,
        upbit_scanner_ai_enabled=True,
        upbit_scanner_notify_hold=False,
    )
    p = load_scanner_policy(settings)
    assert p.enabled is False
    assert p.top_n == 5
    assert p.min_24h_trade_value_krw == 5_000_000_000.0


def test_universe_krw_only_and_inactive_excluded(monkeypatch):
    active = SimpleNamespace(
        symbol="KRW-BTC",
        name="Bitcoin",
        instrument_id=1,
        is_active=True,
        delisted_date=None,
        extra_data={
            "market_warning": None,
            "market_event": {"warning": False, "caution": {"PRICE_FLUCTUATIONS": False}},
        },
        exchange_code="UPBIT",
    )
    warned = SimpleNamespace(
        symbol="KRW-BAD",
        name="Bad",
        instrument_id=3,
        is_active=True,
        delisted_date=None,
        extra_data={"market_warning": True},
        exchange_code="UPBIT",
    )
    caution_only = SimpleNamespace(
        symbol="KRW-OK",
        name="Ok",
        instrument_id=5,
        is_active=True,
        delisted_date=None,
        extra_data={
            "market_warning": None,
            "market_event": {
                "warning": False,
                "caution": {"PRICE_FLUCTUATIONS": True},
            },
        },
        exchange_code="UPBIT",
    )

    session = MagicMock()
    session.scalars.return_value = [active, warned, caution_only]

    rows = load_krw_universe(session)
    symbols = {r["symbol"] for r in rows}
    assert "KRW-BTC" in symbols
    assert "KRW-OK" not in symbols  # active caution flag → 제외
    assert "KRW-BAD" not in symbols

    # caution 전부 false면 통과
    rows2 = load_krw_universe(
        session,
        exclude_caution=False,
    )
    assert "KRW-OK" in {r["symbol"] for r in rows2}


def test_abnormal_spike_exclusion():
    assert is_abnormal_spike(max_spike_pct=15.0, return_5m_pct=16.0) is True
    assert is_abnormal_spike(max_spike_pct=15.0, return_5m_pct=2.0) is False
    assert (
        is_abnormal_spike(
            max_spike_pct=15.0,
            return_5m_pct=1.0,
            volatility_20m_pct=3.0,
        )
        is True
    )


def test_ranking_prefers_healthy_setup():
    policy = _policy()
    good, _ = score_candidate(
        policy=policy,
        trade_value_24h=10_000_000_000,
        volume_surge=2.0,
        ma_spread_pct=0.2,
        momentum_5m_pct=0.3,
        macd_histogram=0.2,
        rsi14=55.0,
        volatility_20m_pct=0.05,
    )
    bad, _ = score_candidate(
        policy=policy,
        trade_value_24h=5_000_000_000,
        volume_surge=0.5,
        ma_spread_pct=-0.3,
        momentum_5m_pct=-0.4,
        macd_histogram=-0.2,
        rsi14=85.0,
        volatility_20m_pct=0.4,
    )
    assert good > bad


def test_candle_order_ascending():
    rows = [
        {
            "opening_price": 2,
            "high_price": 2,
            "low_price": 2,
            "trade_price": 2,
            "candle_acc_trade_volume": 1,
        },
        {
            "opening_price": 1,
            "high_price": 1,
            "low_price": 1,
            "trade_price": 1,
            "candle_acc_trade_volume": 1,
        },
    ]
    candles = upbit_minute_rows_to_candles(rows)
    assert candles[0]["close"] == 1
    assert candles[-1]["close"] == 2


@pytest.mark.asyncio
async def test_scanner_top_n_ai_only_and_no_orders(monkeypatch):
    policy = _policy(
        min_24h_trade_value_krw=1_000_000_000,
        top_n=3,
        technical_candidate_limit=5,
        min_candles=5,
        ai_enabled=True,
    )

    # 5 candles minimum for indicator helper
    def _candles(price: float) -> list[dict]:
        rows = []
        for i in range(40):
            p = price + (i % 3) * 0.1
            rows.append(
                {
                    "opening_price": p,
                    "high_price": p + 0.2,
                    "low_price": p - 0.2,
                    "trade_price": p,
                    "candle_acc_trade_volume": 1000 + i * 10,
                }
            )
        return list(reversed(rows))  # newest first

    client = MagicMock()
    client.list_tickers = AsyncMock(
        return_value=[
            {
                "market": "KRW-AAA",
                "trade_price": 100,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.01,
            },
            {
                "market": "KRW-BBB",
                "trade_price": 200,
                "acc_trade_price_24h": 8_000_000_000,
                "signed_change_rate": 0.02,
            },
            {
                "market": "KRW-CCC",
                "trade_price": 50,
                "acc_trade_price_24h": 7_000_000_000,
                "signed_change_rate": 0.01,
            },
            {
                "market": "KRW-LOW",
                "trade_price": 10,
                "acc_trade_price_24h": 100_000,
                "signed_change_rate": 0.0,
            },
            {
                "market": "KRW-SPIKE",
                "trade_price": 10,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.25,
            },
        ]
    )

    async def _minute(**kwargs):
        return _candles(100.0)

    client.list_minute_candles = AsyncMock(side_effect=_minute)
    client.aclose = AsyncMock()

    ai_calls: list[str] = []

    async def ai_runner(symbol: str) -> dict:
        ai_calls.append(symbol)
        if symbol == "KRW-AAA":
            return {
                "ok": True,
                "recommendation": "ALLOW",
                "confidence": 0.8,
                "risk_level": "LOW",
                "market_analysis_id": 1,
            }
        if symbol == "KRW-BBB":
            return {
                "ok": True,
                "recommendation": "REDUCE",
                "confidence": 0.7,
                "risk_level": "MEDIUM",
                "market_analysis_id": 2,
            }
        return {
            "ok": True,
            "recommendation": "HOLD",
            "confidence": 0.6,
            "risk_level": "MEDIUM",
            "market_analysis_id": 3,
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
        lambda session, **_kwargs: [
            {"symbol": "KRW-AAA", "name": "A"},
            {"symbol": "KRW-BBB", "name": "B"},
            {"symbol": "KRW-CCC", "name": "C"},
            {"symbol": "KRW-LOW", "name": "L"},
            {"symbol": "KRW-SPIKE", "name": "S"},
        ],
    )

    published: list[dict] = []

    def fake_publish(*, event_type, title, message, detail=None):
        published.append(
            {
                "event_type": event_type,
                "title": title,
                "message": message,
                "detail": detail or {},
            }
        )
        return SimpleNamespace(event_type=event_type)

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.notify.notification_publisher.publish",
        fake_publish,
    )

    svc = UpbitOpportunityScannerService(
        MagicMock(),
        quotation_client=client,
        ai_runner=ai_runner,
        now=datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc),
    )
    out = await svc.run(policy=policy, notify=True)

    assert out["ok"] is True
    assert out["orders_created"] == 0
    assert out["runtime_mutated"] is False
    assert out["liquidity_pass_count"] == 3  # LOW+SPIKE excluded
    assert len(out["candidates"]) <= 3
    assert len(ai_calls) == len(out["candidates"])
    assert len(ai_calls) <= 3
    # HOLD spam 없음 — ALLOW/REDUCE만
    events = [p["detail"]["candidate"]["recommendation"] for p in published]
    assert "HOLD" not in events
    assert "ALLOW" in events or "REDUCE" in events
    assert all(p["detail"]["live_auto_start"] is False for p in published)


@pytest.mark.asyncio
async def test_cooldown_suppresses_repeat_allow(monkeypatch):
    policy = _policy(
        min_24h_trade_value_krw=1_000_000_000,
        top_n=1,
        technical_candidate_limit=1,
        min_candles=5,
        cooldown_seconds=1800,
    )

    def _candles() -> list[dict]:
        rows = []
        for i in range(40):
            p = 100 + (i % 2) * 0.1
            rows.append(
                {
                    "opening_price": p,
                    "high_price": p,
                    "low_price": p,
                    "trade_price": p,
                    "candle_acc_trade_volume": 1000,
                }
            )
        return list(reversed(rows))

    client = MagicMock()
    client.list_tickers = AsyncMock(
        return_value=[
            {
                "market": "KRW-AAA",
                "trade_price": 100,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.01,
            }
        ]
    )
    client.list_minute_candles = AsyncMock(return_value=_candles())
    client.aclose = AsyncMock()

    async def ai_runner(symbol: str) -> dict:
        return {
            "ok": True,
            "recommendation": "ALLOW",
            "confidence": 0.9,
            "risk_level": "LOW",
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
        lambda session, **_kwargs: [{"symbol": "KRW-AAA", "name": "A"}],
    )
    published: list = []
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.notify.notification_publisher.publish",
        lambda **kw: published.append(kw) or SimpleNamespace(),
    )

    now = datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)
    svc = UpbitOpportunityScannerService(
        MagicMock(),
        quotation_client=client,
        ai_runner=ai_runner,
        now=now,
    )
    first = await svc.run(policy=policy, notify=True)
    assert first["notifications"]["emitted"] == 1
    second = await svc.run(policy=policy, notify=True)
    assert second["candidates"][0]["cooldown_suppressed"] is True
    assert second["notifications"]["emitted"] == 0


@pytest.mark.asyncio
async def test_ai_failure_fail_closed_hold(monkeypatch):
    policy = _policy(
        min_24h_trade_value_krw=1_000_000_000,
        top_n=1,
        technical_candidate_limit=1,
        min_candles=5,
    )

    def _candles() -> list[dict]:
        rows = []
        for i in range(40):
            p = 100.0
            rows.append(
                {
                    "opening_price": p,
                    "high_price": p,
                    "low_price": p,
                    "trade_price": p,
                    "candle_acc_trade_volume": 1000,
                }
            )
        return list(reversed(rows))

    client = MagicMock()
    client.list_tickers = AsyncMock(
        return_value=[
            {
                "market": "KRW-AAA",
                "trade_price": 100,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.0,
            }
        ]
    )
    client.list_minute_candles = AsyncMock(return_value=_candles())
    client.aclose = AsyncMock()

    async def ai_runner(symbol: str) -> dict:
        raise RuntimeError("ollama_down")

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
        lambda session, **_kwargs: [{"symbol": "KRW-AAA", "name": "A"}],
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.notify.notification_publisher.publish",
        lambda **kw: SimpleNamespace(),
    )

    svc = UpbitOpportunityScannerService(
        MagicMock(),
        quotation_client=client,
        ai_runner=ai_runner,
    )
    out = await svc.run(policy=policy, notify=False)
    assert out["candidates"][0]["recommendation"] == "HOLD"
    assert out["candidates"][0]["fail_closed"] is True
    assert out["orders_created"] == 0


@pytest.mark.asyncio
async def test_hold_only_emits_summary_not_spam(monkeypatch):
    """ALLOW/REDUCE ?놁쑝硫?Top-N ?붿빟 1嫄대쭔, HOLD 媛쒕퀎 ?ㅽ뙵 ?놁쓬."""

    policy = _policy(
        min_24h_trade_value_krw=1_000_000_000,
        top_n=2,
        technical_candidate_limit=2,
        min_candles=5,
        notify_hold=False,
        cooldown_seconds=1800,
    )

    def _candles() -> list[dict]:
        rows = []
        for i in range(40):
            p = 100.0 + i * 0.05
            rows.append(
                {
                    "opening_price": p,
                    "high_price": p,
                    "low_price": p,
                    "trade_price": p,
                    "candle_acc_trade_volume": 1000,
                }
            )
        return list(reversed(rows))

    client = MagicMock()
    client.list_tickers = AsyncMock(
        return_value=[
            {
                "market": "KRW-AAA",
                "trade_price": 100,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.01,
            },
            {
                "market": "KRW-BBB",
                "trade_price": 200,
                "acc_trade_price_24h": 8_000_000_000,
                "signed_change_rate": 0.02,
            },
        ]
    )
    client.list_minute_candles = AsyncMock(return_value=_candles())
    client.aclose = AsyncMock()

    async def ai_runner(symbol: str) -> dict:
        return {
            "ok": False,
            "recommendation": None,
            "analysis_status": "BLOCKED",
            "error": "ANALYSIS_NOT_VALIDATED:BLOCKED",
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
        lambda session, **_kwargs: [
            {"symbol": "KRW-AAA", "name": "A"},
            {"symbol": "KRW-BBB", "name": "B"},
        ],
    )
    published: list = []
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.notify.notification_publisher.publish",
        lambda **kw: published.append(kw) or SimpleNamespace(),
    )

    now = datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)
    svc = UpbitOpportunityScannerService(
        MagicMock(),
        quotation_client=client,
        ai_runner=ai_runner,
        now=now,
    )
    first = await svc.run(policy=policy, notify=True)
    assert first["notifications"]["emitted"] == 0
    assert first["notifications"]["summary_emitted"] is True
    assert first["notifications"]["skipped_hold"] >= 1
    assert len(published) == 1
    assert published[0]["detail"]["source"] == "upbit_opportunity_scanner_v0_summary"
    assert all(c["recommendation"] == "HOLD" for c in first["candidates"])
    assert all(c.get("fail_closed") for c in first["candidates"])

    second = await svc.run(policy=policy, notify=True)
    assert second["notifications"]["emitted"] == 0
    assert second["notifications"]["summary_emitted"] is False


@pytest.mark.asyncio
async def test_ticker_failure_does_not_crash(monkeypatch):
    policy = _policy(top_n=1, technical_candidate_limit=1)
    client = MagicMock()
    client.list_tickers = AsyncMock(side_effect=RuntimeError("upbit_get"))
    client.aclose = AsyncMock()
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
        lambda session, **_kwargs: [{"symbol": "KRW-AAA", "name": "A"}],
    )
    svc = UpbitOpportunityScannerService(
        MagicMock(),
        quotation_client=client,
        ai_runner=AsyncMock(),
    )
    out = await svc.run(policy=policy, notify=False)
    assert out["ok"] is True
    assert out["liquidity_pass_count"] == 0
    assert out["candidates"] == []
    assert out["orders_created"] == 0


@pytest.mark.asyncio
async def test_candle_fetch_uses_bounded_concurrency(monkeypatch):
    """분봉은 직렬 N+1이 아니라 concurrency 한도 안에서 gather."""

    policy = _policy(
        top_n=2,
        technical_candidate_limit=4,
        candle_concurrency=2,
        ai_enabled=False,
    )
    inflight = {"n": 0, "max": 0}

    def _candles(price: float = 100.0):
        rows = []
        for i in range(40):
            p = price + (i % 3) * 0.1
            rows.append(
                {
                    "opening_price": p,
                    "high_price": p + 0.2,
                    "low_price": p - 0.2,
                    "trade_price": p,
                    "candle_acc_trade_volume": 1000 + i * 10,
                }
            )
        return list(reversed(rows))

    async def _minute(**kwargs):
        inflight["n"] += 1
        inflight["max"] = max(inflight["max"], inflight["n"])
        await asyncio.sleep(0.05)
        inflight["n"] -= 1
        return _candles()

    client = MagicMock()
    client.list_tickers = AsyncMock(
        return_value=[
            {
                "market": f"KRW-S{i}",
                "trade_price": 100,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.01,
            }
            for i in range(4)
        ]
    )
    client.list_minute_candles = AsyncMock(side_effect=_minute)
    client.aclose = AsyncMock()
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
        lambda session, **_kwargs: [
            {"symbol": f"KRW-S{i}", "name": str(i)} for i in range(4)
        ],
    )

    svc = UpbitOpportunityScannerService(
        MagicMock(), quotation_client=client, now=datetime.now(timezone.utc)
    )
    out = await svc.run(policy=policy, notify=False, persist_shadow=False)
    assert out["ok"] is True
    assert client.list_minute_candles.await_count == 4
    assert inflight["max"] <= 2
    assert out["api_call_counts"]["minute_candles"] == 4
    assert "CANDIDATE_RANK_MS" in out["stage_timings_ms"]


@pytest.mark.asyncio
async def test_ai_fresh_cache_does_not_fail_closed_slot():
    policy = _policy(top_n=1, technical_candidate_limit=1, ai_backfill_enabled=True)

    def _candles():
        rows = []
        for i in range(40):
            p = 100 + (i % 3) * 0.1
            rows.append(
                {
                    "opening_price": p,
                    "high_price": p + 0.2,
                    "low_price": p - 0.2,
                    "trade_price": p,
                    "candle_acc_trade_volume": 1000 + i * 10,
                }
            )
        return list(reversed(rows))

    client = MagicMock()
    client.list_tickers = AsyncMock(
        return_value=[
            {
                "market": "KRW-AAA",
                "trade_price": 100,
                "acc_trade_price_24h": 9_000_000_000,
                "signed_change_rate": 0.01,
            }
        ]
    )
    client.list_minute_candles = AsyncMock(return_value=_candles())
    client.aclose = AsyncMock()

    async def ai_runner(symbol: str) -> dict:
        return {
            "skipped": True,
            "skip_reason": "FRESH_RESULT_EXISTS",
            "recommendation": "ALLOW",
            "confidence": 0.9,
            "market_analysis_id": 9,
        }

    svc = UpbitOpportunityScannerService(
        MagicMock(),
        quotation_client=client,
        ai_runner=ai_runner,
    )
    # universe monkeypatch via direct liquid path — use run with monkeypatch in caller
    with (
        patch(
            "stock_platform.operation.upbit_opportunity_scanner.service.load_krw_universe",
            return_value=[{"symbol": "KRW-AAA", "name": "A"}],
        ),
        patch.object(
            UpbitOpportunityScannerService,
            "_prefetch_ai_candles",
            new=AsyncMock(return_value=None),
        ),
    ):
        out = await svc.run(policy=policy, notify=False, persist_shadow=False)
    assert out["ok"] is True
    assert out["candidates"][0]["recommendation"] == "ALLOW"
    assert not out["candidates"][0].get("fail_closed")


@pytest.mark.asyncio
async def test_scheduler_single_flight_skips_overlap():
    from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
        UpbitOpportunityScannerScheduler,
    )

    sched = UpbitOpportunityScannerScheduler()
    sched._tick_in_progress = True
    out = await sched._run_tick(notify=False)
    assert out["skipped"] is True
    assert out["code"] == "OVERLAP_SKIP"
    assert sched._overlap_skip_count == 1
    assert out["orders_created"] == 0

