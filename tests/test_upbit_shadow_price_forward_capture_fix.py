"""Shadow entry price + forward capture fix — research pipeline only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import MinuteBar
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    COHORT_LEGACY,
    COHORT_NEW,
    LEGACY_FORWARD_COUNT,
    assign_cohorts,
    run_b1_forward_validation,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_price_resolver import (
    QUALITY_CANDIDATE_REJECTED,
    resolve_canonical_entry_price,
)
from stock_platform.operation.upbit_opportunity_shadow.research_stamp_backfill import (
    _missing_research_stamps,
    backfill_missing_research_stamps,
)
from stock_platform.operation.upbit_opportunity_shadow.service import (
    UpbitOpportunityShadowService,
)


def _outcome(net: float) -> dict:
    return {
        "net_pnl_krw": net,
        "gross_pnl_krw": net + 10,
        "estimated_fee_krw": 10.0,
        "net_return_pct": net / 100.0,
        "holding_seconds": 200,
        "exit_reason": "MA_DEAD_CROSS",
        "fee_only_loss": False,
    }


def _shadow_row(
    *,
    sid: int,
    detected: datetime,
    with_exit_ab: bool = True,
) -> SimpleNamespace:
    detail: dict = {"windows": {}}
    if with_exit_ab:
        detail["exit_ab"] = {"baseline": _outcome(1.0)}
    return SimpleNamespace(
        shadow_id=sid,
        symbol=f"KRW-S{sid % 7}",
        scanner_score=70,
        scanner_rank=1,
        recommendation="ALLOW",
        confidence=0.8,
        ma5=101.0,
        ma20=100.0,
        rsi14=60.0,
        volume_surge=0.9,
        entry_price=Decimal("100"),
        entry_snapshot={"candidate": {"ma_spread_pct": 0.1}},
        evaluation_detail=detail,
        return_5m_pct=0.0,
        return_15m_pct=0.0,
        return_30m_pct=0.0,
        return_60m_pct=0.0,
        mfe_pct=0.5,
        mae_pct=-0.1,
        detected_at=detected,
        status="COMPLETED",
        deleted_at=None,
    )


def test_missing_research_stamps_detects_gap() -> None:
    assert _missing_research_stamps({}) is True
    assert _missing_research_stamps({"exit_ab": {}}) is True
    assert (
        _missing_research_stamps({"exit_ab": {"baseline": _outcome(1.0)}})
        is False
    )


@pytest.mark.asyncio
async def test_backfill_stamps_without_numeric_mutation() -> None:
    row = _shadow_row(sid=999, detected=datetime.now(timezone.utc), with_exit_ab=False)
    row.evaluation_detail = {
        "windows": {"5": {"return_pct": -11.0, "price": 130.0}},
    }
    row.return_5m_pct = -11.0
    row.price_5m = Decimal("130")

    session = MagicMock()
    session.scalars.return_value = iter([row])
    session.commit = MagicMock()

    fake_exit_ab = {
        "baseline": _outcome(-5.0),
        "schema": "exit_policy_ab_v1",
    }
    fake_computed = {
        "ok": True,
        "exit_ab": fake_exit_ab,
        "entry_ab": {"schema": "entry_policy_ab_v1"},
        "entry_forward_features": {"ok": True},
    }

    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.research_stamp_backfill.UpbitOpportunityShadowEvaluator"
    ) as EvalCls:
        inst = EvalCls.return_value
        inst._compute_payload = AsyncMock(return_value=fake_computed)
        out = await backfill_missing_research_stamps(session, limit=10)

    assert out["stamped"] == 1
    assert row.return_5m_pct == -11.0
    assert row.price_5m == Decimal("130")
    assert row.evaluation_detail["exit_ab"]["baseline"]["net_pnl_krw"] == -5.0
    assert row.evaluation_detail["research_stamp_backfill"]["numeric_columns_mutated"] is False


def test_legacy_boundary_stays_459_after_backfill_eligible() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow_row(sid=i, detected=t0 + timedelta(minutes=i), with_exit_ab=True)
        for i in range(LEGACY_FORWARD_COUNT + 5)
    ]
    obs = assign_cohorts(rows)
    assert sum(1 for o in obs if o.cohort == COHORT_LEGACY) == LEGACY_FORWARD_COUNT
    assert sum(1 for o in obs if o.cohort == COHORT_NEW) == 5


def test_new_unseen_increases_when_exit_ab_present() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow_row(sid=i, detected=t0 + timedelta(minutes=i), with_exit_ab=True)
        for i in range(LEGACY_FORWARD_COUNT + 2)
    ]
    report = run_b1_forward_validation(rows)
    assert report["legacy_sample_count"] == LEGACY_FORWARD_COUNT
    assert report["new_sample_count"] == 2


def test_resolve_canonical_rejects_stale_candidate(monkeypatch) -> None:
    detected = datetime(2026, 8, 23, 9, 54, 40, tzinfo=timezone.utc)
    bar = MinuteBar(
        candle_at=datetime(2026, 8, 23, 9, 54, tzinfo=timezone.utc),
        open=Decimal("129"),
        high=Decimal("129"),
        low=Decimal("129"),
        close=Decimal("129"),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.entry_price_resolver.list_minute_bars_db",
        lambda *_a, **_k: [bar],
    )
    session = MagicMock()
    resolved = resolve_canonical_entry_price(
        session,
        symbol="KRW-XPL",
        detected_at=detected,
        candidate_price=Decimal("147"),
    )
    assert resolved.quality == QUALITY_CANDIDATE_REJECTED
    assert resolved.price == Decimal("129")


def test_xpl_type_regression_return_alignment(monkeypatch) -> None:
    """entry 129 → +5m candle 130 = 약 +0.78% (147 기준 -11% 아님)."""

    detected = datetime(2026, 8, 23, 9, 54, 40, tzinfo=timezone.utc)
    entry_bar = MinuteBar(
        candle_at=datetime(2026, 8, 23, 9, 54, tzinfo=timezone.utc),
        open=Decimal("129"),
        high=Decimal("129"),
        low=Decimal("129"),
        close=Decimal("129"),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.entry_price_resolver.list_minute_bars_db",
        lambda *_a, **_k: [entry_bar],
    )
    session = MagicMock()
    resolved = resolve_canonical_entry_price(
        session,
        symbol="KRW-XPL",
        detected_at=detected,
        candidate_price=Decimal("147"),
    )
    entry = float(resolved.price)
    price_5m = 130.0
    ret = (price_5m - entry) / entry * 100.0
    assert abs(ret - 0.775) < 0.1
    assert ret > -1.0


def test_duplicate_scanner_run_skipped(monkeypatch) -> None:
    store: list = []
    session = MagicMock()

    def add(row):
        row.shadow_id = len(store) + 1
        store.append(row)

    def scalar(stmt):  # noqa: ARG001
        if not store:
            return None
        return store[0]

    session.add.side_effect = add
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.scalar.side_effect = scalar
    session.scalars.return_value = iter(store)

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
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.resolve_canonical_entry_price",
        lambda *_a, **_k: SimpleNamespace(
            ok=True,
            price=Decimal("100"),
            to_provenance_dict=lambda: {},
        ),
    )
    svc = UpbitOpportunityShadowService(session)
    cand = {
        "symbol": "KRW-TEST",
        "recommendation": "ALLOW",
        "rank": 1,
        "score": 90,
        "price": 100,
    }
    first = svc.create_from_candidates(
        candidates=[cand],
        scanner_run_id="run-abc",
    )
    second = svc.create_from_candidates(
        candidates=[cand],
        scanner_run_id="run-abc",
    )
    assert first["created"] == 1
    assert second["created"] == 0
    assert any(
        s.get("reason") == "DUPLICATE_SCANNER_RUN" for s in second["skipped"]
    )


def test_ai_flip_only_does_not_create_duplicate_sample() -> None:
    """동일 scanner_run 재호출 시 +0 — AI flip 만으로는 새 row 없음."""

    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [_shadow_row(sid=1, detected=t0, with_exit_ab=True)]
    report1 = run_b1_forward_validation(rows)
    report2 = run_b1_forward_validation(rows)
    assert report1["combined_sample_count"] == report2["combined_sample_count"] == 1


def test_research_error_fail_open(monkeypatch) -> None:
    from stock_platform.operation.upbit_opportunity_shadow import (
        entry_b1_forward_validation as mod,
    )
    from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
        summarize_b1_forward_from_shadows,
    )

    def _boom(_rows):
        raise RuntimeError("research boom")

    monkeypatch.setattr(mod, "run_b1_forward_validation", _boom)
    out = summarize_b1_forward_from_shadows([object()])
    assert out.get("research_failed_open") is True
    assert out["REAL_PROMOTION_RECOMMENDED"] == "NO"
