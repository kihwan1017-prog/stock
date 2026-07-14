from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.news.models import NewsArticle, NewsSummary


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_articles(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        stmt = insert(NewsArticle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[NewsArticle.content_hash],
            set_={
                "exchange_code": stmt.excluded.exchange_code,
                "symbol": stmt.excluded.symbol,
                "query_text": stmt.excluded.query_text,
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "original_link": stmt.excluded.original_link,
                "naver_link": stmt.excluded.naver_link,
                "published_at": stmt.excluded.published_at,
                "raw_data": stmt.excluded.raw_data,
            },
        )

        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(rows)

    def list_unsummarized(
        self,
        *,
        exchange_code: str,
        symbol: str,
        model_name: str,
        limit: int,
    ) -> list[NewsArticle]:
        summarized_ids = select(
            NewsSummary.article_id
        ).where(
            NewsSummary.model_name == model_name
        )

        stmt = (
            select(NewsArticle)
            .where(
                NewsArticle.exchange_code == exchange_code,
                NewsArticle.symbol == symbol,
                NewsArticle.article_id.not_in(summarized_ids),
            )
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.article_id.desc(),
            )
            .limit(limit)
        )

        return list(self._session.scalars(stmt))

    def save_summary(
        self,
        *,
        article_id: int,
        model_name: str,
        summary_text: str,
        sentiment_score,
        importance_score,
        risks: list[str],
    ) -> NewsSummary:
        existing = self._session.scalar(
            select(NewsSummary).where(
                NewsSummary.article_id == article_id,
                NewsSummary.model_name == model_name,
            )
        )

        if existing is None:
            existing = NewsSummary(
                article_id=article_id,
                model_name=model_name,
                summary_text=summary_text,
                sentiment_score=sentiment_score,
                importance_score=importance_score,
                risks=risks,
            )
            self._session.add(existing)
        else:
            existing.summary_text = summary_text
            existing.sentiment_score = sentiment_score
            existing.importance_score = importance_score
            existing.risks = risks

        self._session.commit()
        self._session.refresh(existing)
        return existing

    def list_context(
        self,
        *,
        exchange_code: str,
        symbol: str,
        limit: int = 20,
    ) -> list[tuple[NewsArticle, NewsSummary | None]]:
        stmt = (
            select(NewsArticle, NewsSummary)
            .outerjoin(
                NewsSummary,
                NewsSummary.article_id
                == NewsArticle.article_id,
            )
            .where(
                NewsArticle.exchange_code == exchange_code,
                NewsArticle.symbol == symbol,
            )
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.article_id.desc(),
            )
            .limit(limit)
        )

        return list(self._session.execute(stmt).all())
