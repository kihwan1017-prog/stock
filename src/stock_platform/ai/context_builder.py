from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.disclosure.repository import (
    DartDisclosureRepository,
)
from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import PriceBar
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import PriceDailyService
from stock_platform.news.repository import NewsRepository
from stock_platform.screener.run_repository import (
    CandidateRunRepository,
)


class CandidateContextBuilder:
    """가격·지표·후보점수·뉴스·공시를 AI 컨텍스트로 결합한다."""

    PROMPT_VERSION = "context-v2"
    MAX_NEWS = 8
    MAX_DISCLOSURES = 8
    MAX_CHARS = 6000

    def __init__(self, session: Session) -> None:
        self._news_repository = NewsRepository(session)
        self._dart_repository = DartDisclosureRepository(session)
        self._candidate_repository = CandidateRunRepository(session)
        self._price_service = PriceDailyService(
            PriceDailyRepository(session)
        )
        self._indicator_engine = IndicatorEngine()

    def build(
        self,
        *,
        exchange_code: str,
        symbol: str,
        as_of_date: date,
        news_limit: int = 20,
        disclosure_limit: int = 20,
        lookback_days: int = 90,
    ) -> dict[str, Any]:
        normalized_exchange = exchange_code.strip().upper()
        normalized_symbol = symbol.strip().upper()
        built_at = datetime.now(timezone.utc)

        news_rows = self._news_repository.list_context(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            limit=max(news_limit, self.MAX_NEWS),
        )
        news_rows = self._prioritize_news(news_rows)[: self.MAX_NEWS]

        disclosures = []
        if normalized_exchange == "KRX":
            disclosures = self._dart_repository.list_context(
                stock_code=normalized_symbol,
                start_date=as_of_date - timedelta(days=lookback_days),
                end_date=as_of_date,
                limit=max(disclosure_limit, self.MAX_DISCLOSURES),
            )[: self.MAX_DISCLOSURES]

        price_context = self._price_indicator_context(
            normalized_exchange,
            normalized_symbol,
            as_of_date,
        )
        candidate_context = self._candidate_score_context(
            normalized_exchange,
            normalized_symbol,
        )

        context = {
            "price": price_context,
            "indicators": price_context.get("indicators"),
            "candidate_score": candidate_context,
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
                    "source": "news",
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
                    "category_code": getattr(
                        item, "category_code", "OTHER"
                    ),
                    "importance_score": str(
                        getattr(item, "importance_score", 0)
                    ),
                    "is_correction": bool(
                        getattr(item, "is_correction", False)
                    ),
                    "source": "dart",
                }
                for item in disclosures
            ],
            "metadata": {
                "exchange_code": normalized_exchange,
                "symbol": normalized_symbol,
                "as_of_date": as_of_date.isoformat(),
                "lookback_days": lookback_days,
                "built_at": built_at.isoformat(),
                "prompt_version": self.PROMPT_VERSION,
                "sources": ["price_daily", "indicator_engine", "news", "dart"],
            },
        }

        return self._truncate(context)

    def _price_indicator_context(
        self,
        exchange_code: str,
        symbol: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        try:
            rows = self._price_service.get_between(
                exchange_code=exchange_code,
                symbol=symbol,
                start_date=as_of_date - timedelta(days=420),
                end_date=as_of_date,
            )
        except Exception:
            return {"available": False}

        if not rows:
            return {"available": False}

        bars = [
            PriceBar(
                trade_date=row.trade_date,
                open_price=Decimal(row.open_price),
                high_price=Decimal(row.high_price),
                low_price=Decimal(row.low_price),
                close_price=Decimal(row.close_price),
                volume=Decimal(row.volume),
            )
            for row in rows
            if row.trade_date <= as_of_date
        ]
        if not bars:
            return {"available": False}

        latest = bars[-1]
        indicator = self._indicator_engine.calculate(bars)[-1]

        return {
            "available": True,
            "trade_date": latest.trade_date.isoformat(),
            "close_price": str(latest.close_price),
            "volume": str(latest.volume),
            "indicators": {
                "ma5": str(indicator.ma5) if indicator.ma5 is not None else None,
                "ma20": str(indicator.ma20) if indicator.ma20 is not None else None,
                "ma60": str(indicator.ma60) if indicator.ma60 is not None else None,
                "rsi14": str(indicator.rsi14) if indicator.rsi14 is not None else None,
                "volume_ma20": (
                    str(indicator.volume_ma20)
                    if indicator.volume_ma20 is not None
                    else None
                ),
                "high_52w": (
                    str(indicator.high_52w)
                    if indicator.high_52w is not None
                    else None
                ),
                "low_52w": (
                    str(indicator.low_52w)
                    if indicator.low_52w is not None
                    else None
                ),
                "status_code": indicator.status_code,
            },
        }

    def _candidate_score_context(
        self,
        exchange_code: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        run = self._candidate_repository.get_latest_run(
            exchange_code=exchange_code
        )
        if run is None:
            return None

        for row in self._candidate_repository.get_results(run.run_id):
            if row.symbol == symbol:
                return {
                    "run_id": run.run_id,
                    "rank_no": row.rank_no,
                    "total_score": str(row.total_score),
                    "rules_passed_count": row.rules_passed_count,
                    "all_rules_passed": row.all_rules_passed,
                    "rule_result": row.rule_result,
                    "score_breakdown": row.score_breakdown,
                }
        return None

    @staticmethod
    def _prioritize_news(news_rows: list) -> list:
        def sort_key(pair) -> tuple:
            article, summary = pair
            importance = Decimal("0")
            if summary is not None and summary.importance_score is not None:
                importance = Decimal(str(summary.importance_score))
            published = article.published_at or datetime.min.replace(
                tzinfo=timezone.utc
            )
            return (-importance, published)

        return sorted(news_rows, key=sort_key, reverse=True)

    def _truncate(self, context: dict[str, Any]) -> dict[str, Any]:
        import json

        encoded = json.dumps(context, ensure_ascii=False)
        if len(encoded) <= self.MAX_CHARS:
            return context

        # 토큰/문자 제한: 뉴스·공시를 줄인다
        context = dict(context)
        context["news"] = context.get("news", [])[:3]
        context["disclosures"] = context.get("disclosures", [])[:3]
        context["metadata"] = {
            **context.get("metadata", {}),
            "truncated": True,
        }
        return context
