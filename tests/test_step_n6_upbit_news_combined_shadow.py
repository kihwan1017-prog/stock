"""STEP N6 — News Combined Shadow Experiment focused tests."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_platform.operation.upbit_news_combined_shadow.matching import (
    is_influence_eligible,
)
from stock_platform.operation.upbit_news_combined_shadow.policy import (
    NEWS_SCORE_MAX_ADJUSTMENT,
)
from stock_platform.operation.upbit_news_combined_shadow.scoring import (
    aggregate_news_component,
    assign_counterfactual_ranks,
    direction_value,
    experimental_combined_score,
    experimental_decision,
    recency_weight,
    signal_contribution,
    strength_weight,
    reliability_weight,
)


T0 = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)


def test_direction_encoding() -> None:
    assert direction_value("POSITIVE") == 1.0
    assert direction_value("NEGATIVE") == -1.0
    assert direction_value("NEUTRAL") == 0.0
    assert direction_value("MIXED") == 0.0
    assert direction_value("UNKNOWN") == 0.0


def test_strength_reliability_weights() -> None:
    assert strength_weight("WEAK") == 0.5
    assert strength_weight("MODERATE") == 1.0
    assert strength_weight("STRONG") == 1.5
    assert reliability_weight("HIGH") == 1.0
    assert reliability_weight("MEDIUM") == 0.6
    assert reliability_weight("LOW") == 0.25


def test_positive_and_negative_contribution() -> None:
    pos = signal_contribution(
        direction="POSITIVE",
        strength="MODERATE",
        reliability="HIGH",
        published_at=T0 - timedelta(minutes=30),
        t0=T0,
        influence_allowed=True,
    )
    neg = signal_contribution(
        direction="NEGATIVE",
        strength="MODERATE",
        reliability="HIGH",
        published_at=T0 - timedelta(minutes=30),
        t0=T0,
        influence_allowed=True,
    )
    assert pos["contribution"] > 0
    assert neg["contribution"] < 0


def test_neutral_contribution_zero() -> None:
    out = signal_contribution(
        direction="NEUTRAL",
        strength="STRONG",
        reliability="HIGH",
        published_at=T0 - timedelta(minutes=10),
        t0=T0,
        influence_allowed=True,
    )
    assert out["contribution"] == 0.0


def test_stale_or_invalid_influence_zero() -> None:
    out = signal_contribution(
        direction="POSITIVE",
        strength="STRONG",
        reliability="HIGH",
        published_at=T0 - timedelta(minutes=10),
        t0=T0,
        influence_allowed=False,
    )
    assert out["contribution"] == 0.0


def test_aggregate_clamp_and_normalize() -> None:
    agg = aggregate_news_component([1.5, 1.5, 1.5])
    assert agg["experimental_news_component"] == 3.0
    assert agg["news_component_normalized"] == 1.0
    agg2 = aggregate_news_component([-2.0, -2.0])
    assert agg2["experimental_news_component"] == -3.0
    assert agg2["news_component_normalized"] == -1.0


def test_experimental_score_adjustment_and_clamp() -> None:
    assert experimental_combined_score(
        scanner_score=70, news_component_normalized=0.5
    ) == 70 + 0.5 * NEWS_SCORE_MAX_ADJUSTMENT
    assert experimental_combined_score(
        scanner_score=95, news_component_normalized=1.0
    ) == 100.0
    assert experimental_combined_score(
        scanner_score=5, news_component_normalized=-1.0
    ) == 0.0


def test_decisions() -> None:
    assert experimental_decision(0.3) == "BOOST"
    assert experimental_decision(-0.3) == "DEPRIORITIZE"
    assert experimental_decision(0.1) == "UNCHANGED"


def test_counterfactual_rank() -> None:
    rows = [
        {"symbol": "KRW-A", "experimental_combined_score": 70, "control_scanner_rank": 1},
        {"symbol": "KRW-B", "experimental_combined_score": 80, "control_scanner_rank": 2},
        {"symbol": "KRW-C", "experimental_combined_score": 60, "control_scanner_rank": 3},
    ]
    out = assign_counterfactual_ranks(rows)
    by_sym = {r["symbol"]: r for r in out}
    assert by_sym["KRW-B"]["counterfactual_rank"] == 1
    assert by_sym["KRW-A"]["counterfactual_rank"] == 2
    assert by_sym["KRW-A"]["rank_delta"] == 1 - 2  # actual 1, cf 2 → -1


def test_future_published_excluded() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 + timedelta(hours=1),
        signal_at=T0 - timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
    )
    ok, reason = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False
    assert reason == "FUTURE_PUBLISHED"


def test_future_signal_at_excluded() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 + timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
    )
    ok, reason = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False
    assert reason == "FUTURE_SIGNAL_AT"


def test_future_collected_at_excluded() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=2),
        signal_at=T0 - timedelta(hours=1),
        expires_at=T0 + timedelta(hours=6),
    )
    article = SimpleNamespace(created_at=T0 + timedelta(minutes=5))
    ok, reason = is_influence_eligible(signal=signal, article=article, t0=T0)
    assert ok is False
    assert reason == "FUTURE_COLLECTED_AT"


def test_lookback_exceeded() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=30),
        signal_at=T0 - timedelta(hours=25),
        expires_at=T0 + timedelta(hours=1),
    )
    ok, reason = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False
    assert reason == "LOOKBACK_EXCEEDED"


def test_non_valid_status_excluded() -> None:
    for status in ("STALE", "INVALID", "LOW_CONFIDENCE"):
        signal = SimpleNamespace(
            signal_status=status,
            published_at=T0 - timedelta(hours=1),
            signal_at=T0 - timedelta(minutes=30),
            expires_at=T0 + timedelta(hours=6),
        )
        ok, _ = is_influence_eligible(signal=signal, article=None, t0=T0)
        assert ok is False


def test_valid_fresh_signal_ok() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 - timedelta(minutes=30),
        expires_at=T0 + timedelta(hours=6),
    )
    article = SimpleNamespace(created_at=T0 - timedelta(minutes=40))
    ok, reason = is_influence_eligible(signal=signal, article=article, t0=T0)
    assert ok is True
    assert reason == "OK"


def test_recency_decay() -> None:
    assert recency_weight(published_at=T0 - timedelta(minutes=30), t0=T0) == 1.0
    assert recency_weight(published_at=T0 - timedelta(hours=3), t0=T0) == 0.75
    assert recency_weight(published_at=T0 - timedelta(hours=10), t0=T0) == 0.5
    assert recency_weight(published_at=T0 - timedelta(hours=20), t0=T0) == 0.25
    assert recency_weight(published_at=T0 - timedelta(hours=30), t0=T0) == 0.0


def test_no_ollama_or_scanner_mutation_imports() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stock_platform"
        / "operation"
        / "upbit_news_combined_shadow"
    )
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "ollama" not in node.module
                # CONTROL service write path 금지 — evaluator/service import OK as READ helpers
                assert "ai_signal_gate" not in node.module


def test_scheduler_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPBIT_NEWS_COMBINED_SHADOW_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache, get_settings
    from stock_platform.operation.upbit_news_combined_shadow.scheduler import (
        UpbitNewsCombinedShadowScheduler,
    )

    clear_settings_cache()
    assert get_settings().upbit_news_combined_shadow_enabled is False
    assert UpbitNewsCombinedShadowScheduler().enabled() is False


def test_multiple_news_aggregate() -> None:
    c1 = signal_contribution(
        direction="POSITIVE",
        strength="WEAK",
        reliability="MEDIUM",
        published_at=T0 - timedelta(minutes=20),
        t0=T0,
        influence_allowed=True,
    )["contribution"]
    c2 = signal_contribution(
        direction="NEGATIVE",
        strength="STRONG",
        reliability="HIGH",
        published_at=T0 - timedelta(minutes=10),
        t0=T0,
        influence_allowed=True,
    )["contribution"]
    agg = aggregate_news_component([c1, c2])
    assert -3.0 <= agg["experimental_news_component"] <= 3.0
