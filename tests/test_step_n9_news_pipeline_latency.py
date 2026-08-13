"""STEP N9 — news pipeline latency alignment focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.news.news_ai_analysis_constants import STATUS_COMPLETED
from stock_platform.news.news_ai_analysis_service import NewsAIAnalysisService
from stock_platform.operation.upbit_news_combined_shadow.matching import (
    is_influence_eligible,
)
from stock_platform.operation.upbit_news_combined_shadow.pipeline_observation import (
    diagnose_latency_alignment,
)


T0 = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_latency_alignment_separates_cohorts() -> None:
    session = MagicMock()
    # execute called for rows then backlog
    session.execute.side_effect = [
        MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    all=MagicMock(
                        return_value=[
                            {
                                "article_id": 1,
                                "published_at": T0 - timedelta(hours=2),
                                "collected_at": T0 - timedelta(hours=1),
                                "mapped_at_txt": (
                                    T0 - timedelta(minutes=50)
                                ).isoformat(),
                                "n4_created_at": T0 - timedelta(minutes=40),
                                "analyzed_at": T0 - timedelta(minutes=39),
                                "elapsed_ms": 50000,
                                "signal_at": T0 - timedelta(minutes=38),
                                "signal_created_at": T0 - timedelta(minutes=38),
                                "cohort": "realtime",
                            }
                        ]
                    )
                )
            )
        ),
        MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    one=MagicMock(
                        return_value={
                            "trusted_n": 10,
                            "pending_n": 2,
                            "n4_ok": 5,
                            "n4_fail": 1,
                            "n4_skip": 0,
                            "oldest_pending_age_s": 100.0,
                            "newest_pending_age_s": 10.0,
                            "n5_pending_completed_n4": 0,
                            "articles_1h": 1,
                            "n4_ok_1h": 1,
                        }
                    )
                )
            )
        ),
    ]
    out = diagnose_latency_alignment(session, realtime_since=T0 - timedelta(hours=3))
    assert "historical" in out
    assert "realtime" in out
    assert out["chosen_fix"]["n4_to_n5_event_driven"] is True
    assert out["chosen_fix"]["look_ahead_relaxed"] is False
    assert out["backlog"]["pending_n"] == 2


def test_n5_trigger_failure_does_not_raise() -> None:
    session = MagicMock()
    settings = SimpleNamespace(upbit_news_signal_enabled=True)
    svc = NewsAIAnalysisService(session, settings=settings)

    with patch(
        "stock_platform.database.session.get_session_factory",
        side_effect=RuntimeError("boom"),
    ):
        out = svc._trigger_n5_fail_isolated([1, 2])
    assert out["ok"] is False
    assert "error" in out


def test_n5_trigger_skipped_when_disabled() -> None:
    session = MagicMock()
    settings = SimpleNamespace(upbit_news_signal_enabled=False)
    svc = NewsAIAnalysisService(session, settings=settings)
    out = svc._trigger_n5_fail_isolated([1])
    assert out["skipped"] is True
    assert out["reason"] == "N5_DISABLED"


def test_fresh_unprocessed_skips_existing_analysis() -> None:
    session = MagicMock()
    article_new = SimpleNamespace(
        article_id=10,
        source_code="CRYPTO_NEWS",
        created_at=T0,
        raw_data={
            "symbol_mapping": {
                "mappings": [{"symbol": "KRW-BTC", "quality_status": "TRUSTED"}]
            }
        },
    )
    article_done = SimpleNamespace(
        article_id=9,
        source_code="CRYPTO_NEWS",
        created_at=T0 - timedelta(minutes=1),
        raw_data={
            "symbol_mapping": {
                "mappings": [{"symbol": "KRW-ETH", "quality_status": "TRUSTED"}]
            }
        },
    )
    session.scalars.return_value = [article_new, article_done]

    def _scalar(stmt):  # noqa: ARG001
        # first call for article_new → None, second for article_done → id
        if not hasattr(_scalar, "n"):
            _scalar.n = 0  # type: ignore[attr-defined]
        _scalar.n += 1  # type: ignore[attr-defined]
        return None if _scalar.n == 1 else 99  # type: ignore[attr-defined]

    session.scalar.side_effect = _scalar
    settings = SimpleNamespace(upbit_news_signal_enabled=True)
    svc = NewsAIAnalysisService(session, settings=settings)

    with patch(
        "stock_platform.news.news_ai_analysis_service.extract_trusted_symbols",
        side_effect=lambda a: ["KRW-BTC"] if a.article_id == 10 else ["KRW-ETH"],
    ):
        selected = svc._list_fresh_unprocessed_trusted(limit=5)
    assert [a.article_id for a in selected] == [10]


def test_look_ahead_still_enforced() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 + timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
    )
    ok, reason = is_influence_eligible(signal=signal, article=None, t0=T0)
    assert ok is False
    assert reason == "FUTURE_SIGNAL_AT"


def test_pre_t0_still_eligible() -> None:
    signal = SimpleNamespace(
        signal_status="VALID",
        published_at=T0 - timedelta(hours=1),
        signal_at=T0 - timedelta(minutes=10),
        expires_at=T0 + timedelta(hours=6),
    )
    article = SimpleNamespace(created_at=T0 - timedelta(minutes=30))
    ok, _ = is_influence_eligible(signal=signal, article=article, t0=T0)
    assert ok is True


def test_collector_does_not_import_ollama_inline() -> None:
    import inspect

    from stock_platform.news import collector_scheduler as mod

    src = inspect.getsource(mod)
    assert "OllamaClient" not in src
    assert "chat_structured" not in src
