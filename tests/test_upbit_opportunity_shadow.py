"""UPBIT Opportunity Scanner Paper Shadow v1 — focused tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_opportunity_scanner.policy import (
    ScannerPolicy,
    load_scanner_policy,
)
from stock_platform.operation.upbit_opportunity_scanner.universe import (
    is_stablecoin_like,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.service import (
    UpbitOpportunityShadowService,
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
        min_candles=5,
        candle_unit=1,
        ai_enabled=True,
        notify_hold=False,
        exclude_stablecoins=True,
        exclude_caution_markets=True,
        ai_backfill_enabled=True,
    )
    base.update(overrides)
    return ScannerPolicy(**base)


def test_stablecoin_excluded_by_base_and_name():
    assert is_stablecoin_like(symbol="KRW-USDT") is True
    assert is_stablecoin_like(symbol="KRW-USDC") is True
    assert is_stablecoin_like(
        symbol="KRW-FOO",
        extra={"english_name": "Tether"},
    ) is True
    assert is_stablecoin_like(symbol="KRW-XRP") is False


def test_policy_shadow_related_defaults():
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
        upbit_scanner_exclude_stablecoins=True,
        upbit_scanner_exclude_caution_markets=True,
        upbit_scanner_ai_backfill_enabled=True,
        upbit_scanner_stablecoin_base_assets="USDT,USDC",
    )
    p = load_scanner_policy(settings)
    assert p.exclude_stablecoins is True
    assert p.exclude_caution_markets is True
    assert "USDT" in p.stablecoin_base_assets


def _mem_session() -> MagicMock:
    """간단한 in-memory shadow store용 Session mock."""

    store: list[UpbitOpportunityShadowEntity] = []
    session = MagicMock()
    session._store = store

    def add(row):
        if getattr(row, "shadow_id", None) is None:
            row.shadow_id = len(store) + 1
        store.append(row)

    def flush():
        for i, row in enumerate(store, start=1):
            if row.shadow_id is None:
                row.shadow_id = i

    def commit():
        flush()

    def scalar(stmt):  # noqa: ARG001
        # ACTIVE / latest 조회 단순화
        actives = [
            r
            for r in store
            if r.status == SHADOW_STATUS_ACTIVE and r.deleted_at is None
        ]
        if actives:
            # where symbol filter는 테스트에서 단일 심볼 가정
            return actives[-1]
        completed = [
            r
            for r in store
            if r.status == SHADOW_STATUS_COMPLETED and r.deleted_at is None
        ]
        return completed[-1] if completed else None

    def scalars(stmt):  # noqa: ARG001
        return SimpleNamespace(all=lambda: list(store), __iter__=lambda self: iter(store))

    session.add.side_effect = add
    session.flush.side_effect = flush
    session.commit.side_effect = commit
    session.scalar.side_effect = scalar
    session.scalars.side_effect = scalars
    return session


@pytest.mark.asyncio
async def test_hold_creates_zero_shadows(monkeypatch):
    session = _mem_session()
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_enabled=True,
            upbit_scanner_shadow_assumed_amount_krw=5000,
            upbit_scanner_shadow_reduce_ratio=0.5,
            upbit_scanner_shadow_cooldown_seconds=3600,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.publish_shadow_opened",
        lambda *_a, **_k: None,
    )
    svc = UpbitOpportunityShadowService(session)
    out = svc.create_from_candidates(
        candidates=[
            {
                "symbol": "KRW-AAA",
                "recommendation": "HOLD",
                "price": 100,
                "rank": 1,
                "score": 70,
            }
        ],
        scanner_run_id="run1",
        notify=False,
    )
    assert out["created"] == 0
    assert out["orders_created"] == 0


@pytest.mark.asyncio
async def test_allow_creates_shadow_and_reduce_half_amount(monkeypatch):
    published = []
    session = _mem_session()
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_enabled=True,
            upbit_scanner_shadow_assumed_amount_krw=5000,
            upbit_scanner_shadow_reduce_ratio=0.5,
            upbit_scanner_shadow_cooldown_seconds=3600,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.publish_shadow_opened",
        lambda s: published.append(s),
    )
    # scalar: no active
    session.scalar.side_effect = lambda *_a, **_k: None

    svc = UpbitOpportunityShadowService(
        session, now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    )
    allow = svc.create_from_candidates(
        candidates=[
            {
                "symbol": "KRW-AAA",
                "recommendation": "ALLOW",
                "price": 100,
                "rank": 1,
                "score": 80,
                "confidence": 0.9,
                "risk_level": "MEDIUM",
            }
        ],
        scanner_run_id="run1",
        notify=True,
    )
    assert allow["created"] == 1
    assert allow["shadows"][0]["assumed_amount_krw"] == 5000.0
    assert allow["orders_created"] == 0
    assert published

    # duplicate active
    session.scalar.side_effect = lambda *_a, **_k: session._store[0]
    dup = svc.create_from_candidates(
        candidates=[
            {
                "symbol": "KRW-AAA",
                "recommendation": "ALLOW",
                "price": 101,
                "rank": 1,
                "score": 81,
            }
        ],
        scanner_run_id="run2",
        notify=False,
    )
    assert dup["created"] == 0
    assert any(s.get("reason") == "ACTIVE_EXISTS" for s in dup["skipped"])

    # REDUCE amount
    session.scalar.side_effect = lambda *_a, **_k: None
    reduce = svc.create_from_candidates(
        candidates=[
            {
                "symbol": "KRW-BBB",
                "recommendation": "REDUCE",
                "price": 50,
                "rank": 2,
                "score": 70,
            }
        ],
        scanner_run_id="run3",
        notify=False,
    )
    assert reduce["created"] == 1
    assert reduce["shadows"][0]["assumed_amount_krw"] == 2500.0


@pytest.mark.asyncio
async def test_ai_failed_no_shadow(monkeypatch):
    session = _mem_session()
    session.scalar.side_effect = lambda *_a, **_k: None
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_enabled=True,
            upbit_scanner_shadow_assumed_amount_krw=5000,
            upbit_scanner_shadow_reduce_ratio=0.5,
            upbit_scanner_shadow_cooldown_seconds=3600,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.publish_shadow_opened",
        lambda *_a, **_k: None,
    )
    svc = UpbitOpportunityShadowService(session)
    out = svc.create_from_candidates(
        candidates=[
            {
                "symbol": "KRW-AAA",
                "recommendation": "ALLOW",
                "price": 100,
                "fail_closed": True,
                "ai_error": "FAILED",
            }
        ],
        scanner_run_id="run1",
        notify=False,
    )
    assert out["created"] == 0


@pytest.mark.asyncio
async def test_shadow_never_creates_orders_flag():
    """계약: shadow 결과는 항상 orders_created=0."""

    session = _mem_session()
    session.scalar.side_effect = lambda *_a, **_k: None
    from unittest.mock import patch

    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.service.get_settings",
        return_value=SimpleNamespace(
            upbit_scanner_shadow_enabled=True,
            upbit_scanner_shadow_assumed_amount_krw=5000,
            upbit_scanner_shadow_reduce_ratio=0.5,
            upbit_scanner_shadow_cooldown_seconds=3600,
        ),
    ), patch(
        "stock_platform.operation.upbit_opportunity_shadow.service.publish_shadow_opened",
        lambda *_a, **_k: None,
    ):
        svc = UpbitOpportunityShadowService(session)
        out = svc.create_from_candidates(
            candidates=[
                {
                    "symbol": "KRW-CCC",
                    "recommendation": "ALLOW",
                    "price": 10,
                    "rank": 1,
                    "score": 60,
                }
            ],
            scanner_run_id="runx",
            notify=False,
        )
    assert out["orders_created"] == 0
    assert out["live_auto_start"] is False
    assert out["paper_shadow"] is True
