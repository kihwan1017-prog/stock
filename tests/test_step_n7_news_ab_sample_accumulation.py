"""STEP N7 — sample accumulation / diagnostics focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
    MATCHED_COMPLETED_TARGET,
    NO_NEWS_COMPLETED_TARGET,
    STATUS_ACCUMULATING,
    STATUS_REVIEW_READY,
    compute_sample_milestone,
)
from stock_platform.operation.upbit_news_combined_shadow.matching import (
    is_influence_eligible,
)
from stock_platform.operation.upbit_news_combined_shadow.scheduler import (
    UpbitNewsCombinedShadowScheduler,
)


T0 = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)


def test_sample_milestone_accumulating() -> None:
    session = MagicMock()
    # scalars called twice for matched/no_news — return short lists
    session.scalars.side_effect = [
        [SimpleNamespace()] * 3,  # matched
        [SimpleNamespace()] * 5,  # no_news
    ]
    out = compute_sample_milestone(session)
    assert out["status"] == STATUS_ACCUMULATING
    assert out["ready"] is False
    assert out["matched_target"] == MATCHED_COMPLETED_TARGET
    assert out["no_news_target"] == NO_NEWS_COMPLETED_TARGET
    assert out["not_a_trading_policy_gate"] is True


def test_sample_milestone_review_ready() -> None:
    session = MagicMock()
    session.scalars.side_effect = [
        [SimpleNamespace()] * 20,
        [SimpleNamespace()] * 20,
    ]
    out = compute_sample_milestone(session)
    assert out["status"] == STATUS_REVIEW_READY
    assert out["ready"] is True


def test_look_ahead_still_blocked() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 + timedelta(minutes=1),
        signal_at=T0 - timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
    )
    ok, reason = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False
    assert reason == "FUTURE_PUBLISHED"


def test_future_collected_still_blocked() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 - timedelta(minutes=30),
        expires_at=T0 + timedelta(hours=6),
    )
    article = SimpleNamespace(created_at=T0 + timedelta(minutes=1))
    ok, reason = is_influence_eligible(signal=signal, article=article, t0=T0)
    assert ok is False
    assert reason == "FUTURE_COLLECTED_AT"


def test_stale_status_excluded() -> None:
    signal = SimpleNamespace(
        signal_status="STALE",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 - timedelta(minutes=30),
        expires_at=T0 + timedelta(hours=6),
    )
    ok, _ = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False


def test_scheduler_default_off_and_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPBIT_NEWS_COMBINED_SHADOW_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    sched = UpbitNewsCombinedShadowScheduler()
    assert sched.enabled() is False
    assert sched.status()["scanner_hook"] is False
    assert sched.status()["max_instances"] == 1
    assert sched.status()["failure_isolation"] is True


@pytest.mark.asyncio
async def test_scheduler_overlap_skip() -> None:
    sched = UpbitNewsCombinedShadowScheduler()
    sched._tick_in_progress = True
    await sched._run_tick()
    assert sched._overlap_skips == 1


def test_source_coverage_documented_in_diagnostics_module() -> None:
    from stock_platform.operation.upbit_news_combined_shadow import diagnostics as d

    assert MATCHED_COMPLETED_TARGET == 20
    assert NO_NEWS_COMPLETED_TARGET == 20
    assert hasattr(d, "diagnose_news_availability")
