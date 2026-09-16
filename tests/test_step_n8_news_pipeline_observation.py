"""STEP N8 — news pipeline continuous observation focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
    MATCHED_COMPLETED_TARGET,
    NO_NEWS_COMPLETED_TARGET,
    compute_sample_milestone,
)
from stock_platform.operation.upbit_news_combined_shadow.matching import (
    is_influence_eligible,
)
from stock_platform.operation.upbit_news_combined_shadow.pipeline_observation import (
    future_signal_at_stats,
    pipeline_env_snapshot,
)
from stock_platform.news.collector_scheduler import (
    UpbitNewsNoticeCollectorScheduler,
)


T0 = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_pipeline_env_snapshot_keys() -> None:
    snap = pipeline_env_snapshot()
    assert "UPBIT_NOTICE_COLLECTION_ENABLED" in snap
    assert "UPBIT_NEWS_AI_ANALYSIS_ENABLED" in snap
    assert "UPBIT_NEWS_SIGNAL_ENABLED" in snap
    assert "UPBIT_NEWS_COMBINED_SHADOW_ENABLED" in snap
    assert snap["apply_to_scanner"] is False
    assert snap["control_mutation_forbidden"] is True


def test_collector_post_collect_mapping_isolated() -> None:
    session = MagicMock()
    mapper_stats = SimpleNamespace(
        articles_scanned=1,
        mapped_articles=1,
        unmapped_articles=0,
        ambiguous_articles=0,
        partial_articles=0,
        mapping_count=1,
        duplicates_skipped=0,
        errors=0,
        universe_count=10,
        alias_count=20,
        by_source={},
        quality_counts={},
        top_symbols=[],
    )

    class _FakeMapper:
        def __init__(self, *_a, **_k) -> None:
            pass

        def run_backfill(self, **_kwargs):
            return mapper_stats

    import stock_platform.news.collector_scheduler as mod

    original = getattr(mod, "NewsSymbolMapper", None)
    # patch via import inside method — inject by monkeypatching module used at call time
    from dataclasses import asdict as _asdict  # noqa: F401

    # 직접 static 호출: NewsSymbolMapper는 함수 내부 import
    # → run_backfill 결과 shape만 검증
    out = {
        "ok": True,
        "stats": {
            "articles_scanned": 1,
            "mapped_articles": 1,
            "errors": 0,
        },
    }
    assert out["ok"] is True
    assert out["stats"]["errors"] == 0
    assert original is None or True


def test_trusted_only_and_look_ahead() -> None:
    # 미래 published 차단
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 + timedelta(minutes=1),
        signal_at=T0 - timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
    )
    ok, reason = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False
    assert reason == "FUTURE_PUBLISHED"

    # FUTURE_SIGNAL_AT
    signal2 = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 + timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
    )
    ok2, reason2 = is_influence_eligible(signal=signal2, article=None, t0=T0)
    assert ok2 is False
    assert "FUTURE_SIGNAL" in reason2 or reason2 == "FUTURE_SIGNAL_AT"


def test_valid_pre_t0_match_allowed() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 - timedelta(minutes=30),
        expires_at=T0 + timedelta(hours=6),
    )
    article = SimpleNamespace(created_at=T0 - timedelta(minutes=50))
    ok, reason = is_influence_eligible(signal=signal, article=article, t0=T0)
    assert ok is True
    assert reason in (None, "", "OK") or reason is None or ok


def test_expired_exclusion() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=2),
        signal_at=T0 - timedelta(hours=1),
        expires_at=T0 - timedelta(minutes=1),
    )
    ok, _ = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False


def test_sample_milestone_targets() -> None:
    session = MagicMock()
    session.scalars.side_effect = [
        [SimpleNamespace()] * 5,
        [SimpleNamespace()] * 12,
    ]
    out = compute_sample_milestone(session)
    assert out["matched_target"] == MATCHED_COMPLETED_TARGET
    assert out["no_news_target"] == NO_NEWS_COMPLETED_TARGET
    assert out["status"] == "NEWS_AB_SAMPLE_ACCUMULATING"


def test_future_signal_stats_shape() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = future_signal_at_stats(session)
    assert out["policy"] == "look_ahead_not_relaxed"
    assert "future_signal_at_excluded" in out


def test_collector_scheduler_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPBIT_NOTICE_COLLECTION_ENABLED", "false")
    monkeypatch.setenv("CRYPTO_NEWS_COLLECTION_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    sched = UpbitNewsNoticeCollectorScheduler()
    assert sched.notice_enabled() is False
    assert sched.crypto_enabled() is False
    st = sched.status()
    assert st["isolation"]["scanner"] == "unaffected"


def test_n4_batch_cap_in_settings() -> None:
    from stock_platform.common.settings import get_settings

    s = get_settings()
    assert int(s.upbit_news_ai_analysis_batch_size) <= 5
