from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.news.models import (
    NewsArticle,
    NewsArticleSymbol,
    NewsCollectionFailure,
    NewsSummary,
    UserNewsState,
)


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_articles(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        stmt = insert(NewsArticle).values(rows)
        # content_hash 중복 시 메타만 갱신 — 종목은 링크 테이블에 추가
        stmt = stmt.on_conflict_do_update(
            index_elements=[NewsArticle.content_hash],
            set_={
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "original_link": stmt.excluded.original_link,
                "naver_link": stmt.excluded.naver_link,
                "published_at": stmt.excluded.published_at,
                "raw_data": stmt.excluded.raw_data,
                "query_text": stmt.excluded.query_text,
            },
        )

        result = self._session.execute(stmt)
        self._session.flush()

        # 종목 링크 upsert (다대다)
        for row in rows:
            article = self._session.scalar(
                select(NewsArticle).where(
                    NewsArticle.content_hash == row["content_hash"]
                )
            )
            if article is None:
                continue
            link_stmt = insert(NewsArticleSymbol).values(
                article_id=article.article_id,
                market_code=str(row["exchange_code"]).upper(),
                symbol=str(row["symbol"]).upper(),
                match_type="PROVIDER",
                relevance_score=Decimal("1.0"),
            )
            link_stmt = link_stmt.on_conflict_do_nothing(
                index_elements=[
                    "article_id",
                    "market_code",
                    "symbol",
                ],
            )
            self._session.execute(link_stmt)

        self._session.commit()
        return result.rowcount or len(rows)

    def get_article(self, article_id: int) -> NewsArticle | None:
        return self._session.get(NewsArticle, article_id)

    def list_symbol_links(
        self,
        article_ids: list[int],
    ) -> list[NewsArticleSymbol]:
        if not article_ids:
            return []
        stmt = select(NewsArticleSymbol).where(
            NewsArticleSymbol.article_id.in_(article_ids)
        )
        return list(self._session.scalars(stmt))

    def record_failure(
        self,
        *,
        exchange_code: str,
        symbol: str,
        query_text: str | None,
        error_message: str,
        source_code: str = "NAVER",
        extra_data: dict | None = None,
    ) -> NewsCollectionFailure:
        entity = NewsCollectionFailure(
            exchange_code=exchange_code,
            symbol=symbol,
            query_text=query_text,
            source_code=source_code,
            error_message=error_message,
            extra_data=extra_data or {},
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def list_failures(
        self,
        *,
        exchange_code: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[NewsCollectionFailure]:
        stmt = select(NewsCollectionFailure)
        if exchange_code:
            stmt = stmt.where(
                NewsCollectionFailure.exchange_code
                == exchange_code.upper()
            )
        if symbol:
            stmt = stmt.where(
                NewsCollectionFailure.symbol == symbol.upper()
            )
        stmt = stmt.order_by(
            NewsCollectionFailure.failed_at.desc()
        ).limit(limit)
        return list(self._session.scalars(stmt))

    def list_unsummarized(
        self,
        *,
        exchange_code: str,
        symbol: str,
        model_name: str,
        limit: int,
    ) -> list[NewsArticle]:
        # NOT IN 서브쿼리 대신 anti-join (대량 요약 이력에서 유리)
        stmt = (
            select(NewsArticle)
            .outerjoin(
                NewsSummary,
                (NewsSummary.article_id == NewsArticle.article_id)
                & (NewsSummary.model_name == model_name),
            )
            .where(
                NewsArticle.exchange_code == exchange_code,
                NewsArticle.symbol == symbol,
                NewsSummary.article_id.is_(None),
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

    def list_for_symbols(
        self,
        *,
        symbol_pairs: list[tuple[str, str]],
        limit: int = 50,
        offset: int = 0,
        keyword: str | None = None,
        source_code: str | None = None,
        date_from=None,
        date_to=None,
    ) -> list[NewsArticle]:
        """관심종목 (market, symbol) 집합의 뉴스 — 링크 테이블 우선."""

        if not symbol_pairs:
            return []

        normalized = [
            (m.upper(), s.upper()) for m, s in symbol_pairs
        ]
        link_match = tuple_(
            NewsArticleSymbol.market_code,
            NewsArticleSymbol.symbol,
        ).in_(normalized)
        legacy_match = tuple_(
            NewsArticle.exchange_code,
            NewsArticle.symbol,
        ).in_(normalized)

        stmt = (
            select(NewsArticle)
            .outerjoin(
                NewsArticleSymbol,
                NewsArticleSymbol.article_id == NewsArticle.article_id,
            )
            .where(or_(link_match, legacy_match))
            .distinct()
        )
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    NewsArticle.title.ilike(pattern),
                    NewsArticle.description.ilike(pattern),
                )
            )
        if source_code:
            stmt = stmt.where(
                NewsArticle.source_code == source_code.upper()
            )
        if date_from is not None:
            stmt = stmt.where(NewsArticle.published_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(NewsArticle.published_at <= date_to)

        stmt = stmt.order_by(
            NewsArticle.published_at.desc().nullslast(),
            NewsArticle.article_id.desc(),
        ).offset(offset).limit(limit)
        return list(self._session.scalars(stmt))

    def count_for_symbols(
        self,
        *,
        symbol_pairs: list[tuple[str, str]],
        keyword: str | None = None,
        source_code: str | None = None,
        date_from=None,
        date_to=None,
    ) -> int:
        if not symbol_pairs:
            return 0
        from sqlalchemy import func

        normalized = [
            (m.upper(), s.upper()) for m, s in symbol_pairs
        ]
        link_match = tuple_(
            NewsArticleSymbol.market_code,
            NewsArticleSymbol.symbol,
        ).in_(normalized)
        legacy_match = tuple_(
            NewsArticle.exchange_code,
            NewsArticle.symbol,
        ).in_(normalized)
        stmt = (
            select(func.count(func.distinct(NewsArticle.article_id)))
            .select_from(NewsArticle)
            .outerjoin(
                NewsArticleSymbol,
                NewsArticleSymbol.article_id == NewsArticle.article_id,
            )
            .where(or_(link_match, legacy_match))
        )
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    NewsArticle.title.ilike(pattern),
                    NewsArticle.description.ilike(pattern),
                )
            )
        if source_code:
            stmt = stmt.where(
                NewsArticle.source_code == source_code.upper()
            )
        if date_from is not None:
            stmt = stmt.where(NewsArticle.published_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(NewsArticle.published_at <= date_to)
        return int(self._session.scalar(stmt) or 0)

    def get_or_create_user_state(
        self,
        *,
        user_id: int,
        article_id: int,
    ) -> UserNewsState:
        row = self._session.scalar(
            select(UserNewsState).where(
                UserNewsState.user_id == user_id,
                UserNewsState.article_id == article_id,
            )
        )
        if row is not None:
            return row
        row = UserNewsState(
            user_id=user_id,
            article_id=article_id,
        )
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def list_user_states(
        self,
        *,
        user_id: int,
        article_ids: list[int],
    ) -> dict[int, UserNewsState]:
        if not article_ids:
            return {}
        rows = list(
            self._session.scalars(
                select(UserNewsState).where(
                    UserNewsState.user_id == user_id,
                    UserNewsState.article_id.in_(article_ids),
                )
            )
        )
        return {int(row.article_id): row for row in rows}
