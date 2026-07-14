from datetime import date
from types import SimpleNamespace

from stock_platform.ai.context_builder import CandidateContextBuilder


class FakeNewsRepository:
    def list_context(self, **kwargs):
        article = SimpleNamespace(
            title="테스트 뉴스",
            published_at=None,
            description="설명",
        )
        summary = SimpleNamespace(
            summary_text="요약",
            sentiment_score=10,
            importance_score=80,
            risks=["확인 필요"],
        )
        return [(article, summary)]


class FakeDartRepository:
    def list_context(self, **kwargs):
        return [
            SimpleNamespace(
                receipt_no="202607130001",
                receipt_date=date(2026, 7, 13),
                report_name="주요사항보고서",
                filer_name="삼성전자",
                remark=None,
            )
        ]


def test_build_combines_news_and_disclosures() -> None:
    builder = CandidateContextBuilder.__new__(
        CandidateContextBuilder
    )
    builder._news_repository = FakeNewsRepository()
    builder._dart_repository = FakeDartRepository()

    result = builder.build(
        exchange_code="KRX",
        symbol="005930",
        as_of_date=date(2026, 7, 13),
    )

    assert len(result["news"]) == 1
    assert len(result["disclosures"]) == 1
    assert result["metadata"]["symbol"] == "005930"


def test_upbit_does_not_query_dart() -> None:
    builder = CandidateContextBuilder.__new__(
        CandidateContextBuilder
    )
    builder._news_repository = FakeNewsRepository()
    builder._dart_repository = FakeDartRepository()

    result = builder.build(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        as_of_date=date(2026, 7, 13),
    )

    assert result["disclosures"] == []
