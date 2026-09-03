"""News Intelligence Pipeline V1 — focused regression tests."""

from __future__ import annotations

from types import SimpleNamespace

from stock_platform.news.intelligence.upbit_targets import (
    list_upbit_dynamic_news_targets,
)
from stock_platform.news.symbol_mapper import _extract_explicit_krw_matches
from stock_platform.news.symbol_mapping_constants import (
    FIELD_TITLE,
    MATCH_EXACT_MARKET_SYMBOL,
)
from stock_platform.notification.telegram_policy import (
    is_telegram_event_allowlisted,
)
from stock_platform.operation.news_intelligence_shadow.policy import (
    UPBIT_CRITICAL_NOTICE_CATEGORIES,
)


def test_explicit_krw_title_match_boost() -> None:
    matches = _extract_explicit_krw_matches(
        title="업비트 KRW-BTC 마켓 유의 안내",
        body="기타 내용",
    )
    assert len(matches) == 1
    assert matches[0].symbol == "KRW-BTC"
    assert matches[0].match_type == MATCH_EXACT_MARKET_SYMBOL
    assert matches[0].matched_field == FIELD_TITLE
    assert matches[0].mapping_confidence >= 0.99


def test_telegram_allowlist_includes_news_intelligence_events() -> None:
    assert is_telegram_event_allowlisted("UPBIT_IMPORTANT_NOTICE")
    assert is_telegram_event_allowlisted("KIWOOM_IMPORTANT_DISCLOSURE")


def test_upbit_critical_notice_categories() -> None:
    assert "CAUTION" in UPBIT_CRITICAL_NOTICE_CATEGORIES
    assert "DELISTING" in UPBIT_CRITICAL_NOTICE_CATEGORIES


def test_list_context_uses_symbol_links(monkeypatch) -> None:
    """CandidateContextBuilder가 링크 조인 list_context를 쓰는지 확인."""

    from stock_platform.ai.context_builder import CandidateContextBuilder
    from datetime import date

    called: dict[str, object] = {}

    class FakeNewsRepository:
        def list_context(self, **kwargs):
            called.update(kwargs)
            article = SimpleNamespace(
                title="mapped news",
                published_at=None,
                description="body",
            )
            return [(article, None)]

    class FakeDartRepository:
        def list_context(self, **kwargs):
            return []

    builder = CandidateContextBuilder.__new__(CandidateContextBuilder)
    builder._news_repository = FakeNewsRepository()
    builder._dart_repository = FakeDartRepository()
    builder._price_indicator_context = (  # type: ignore[method-assign]
        lambda *args, **kwargs: {"available": False}
    )
    builder._candidate_score_context = (  # type: ignore[method-assign]
        lambda *args, **kwargs: None
    )

    result = builder.build(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        as_of_date=date(2026, 9, 4),
    )
    assert called.get("exchange_code") == "UPBIT"
    assert called.get("symbol") == "KRW-BTC"
    assert len(result["news"]) == 1
    assert result["metadata"]["prompt_version"] == "context-v3"


def test_dynamic_targets_empty_session_safe() -> None:
    class FakeSession:
        def scalars(self, *args, **kwargs):
            return iter([])

        def execute(self, *args, **kwargs):
            return SimpleNamespace(all=lambda: [])

    # exception-safe: portfolio entity import may fail with FakeSession
    out = list_upbit_dynamic_news_targets(FakeSession(), limit=5)  # type: ignore[arg-type]
    assert isinstance(out, list)
