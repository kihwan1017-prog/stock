from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from stock_platform.disclosure.repository import (
    DartDisclosureRepository,
)
from stock_platform.news.repository import NewsRepository


class CandidateContextBuilder:
    """뉴스와 DART 공시를 AI 후보평가 컨텍스트로 결합한다."""

    def __init__(self, session: Session) -> None:
        self._news_repository = NewsRepository(session)
        self._dart_repository = DartDisclosureRepository(session)

    def build(
        self,
        *,
        exchange_code: str,
        symbol: str,
        as_of_date: date,
        news_limit: int = 20,
        disclosure_limit: int = 20,
        lookback_days: int = 90,
    ) -> dict:
        normalized_exchange = exchange_code.strip().upper()
        normalized_symbol = symbol.strip().upper()

        news_rows = self._news_repository.list_context(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            limit=news_limit,
        )

        disclosures = []
        if normalized_exchange == "KRX":
            disclosures = self._dart_repository.list_context(
                stock_code=normalized_symbol,
                start_date=as_of_date - timedelta(days=lookback_days),
                end_date=as_of_date,
                limit=disclosure_limit,
            )

        return {
            "news": [
                {
                    "title": article.title,
                    "published_at": (
                        article.published_at.isoformat()
                        if article.published_at
                        else None
                    ),
                    "summary": (
                        summary.summary_text
                        if summary is not None
                        else article.description
                    ),
                    "sentiment_score": (
                        str(summary.sentiment_score)
                        if summary is not None
                        else None
                    ),
                    "importance_score": (
                        str(summary.importance_score)
                        if summary is not None
                        else None
                    ),
                    "risks": (
                        summary.risks
                        if summary is not None
                        else []
                    ),
                }
                for article, summary in news_rows
            ],
            "disclosures": [
                {
                    "receipt_no": item.receipt_no,
                    "receipt_date": item.receipt_date.isoformat(),
                    "report_name": item.report_name,
                    "filer_name": item.filer_name,
                    "remark": item.remark,
                }
                for item in disclosures
            ],
            "metadata": {
                "exchange_code": normalized_exchange,
                "symbol": normalized_symbol,
                "as_of_date": as_of_date.isoformat(),
                "lookback_days": lookback_days,
            },
        }
