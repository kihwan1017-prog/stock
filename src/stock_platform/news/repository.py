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
        """직접 exchange/symbol 행 + news_article_symbol 링크를 모두 포함.

        UPBIT notice/crypto는 placeholder symbol로 저장되므로
        CandidateContextBuilder가 mapped KRW 뉴스를 보려면 링크 조인이 필수.
        """

        market = exchange_code.strip().upper()
        sym = symbol.strip().upper()
        # UPBIT/KRX 등 market_code ↔ exchange_code 정규화
        market_aliases = {market}
        if market == "UPBIT":
            market_aliases.add("CRYPTO")
        elif market in {"KRX", "KOSPI", "KOSDAQ"}:
            market_aliases.update({"KRX", "KOSPI", "KOSDAQ"})

        link_match = (
            (NewsArticleSymbol.market_code.in_(sorted(market_aliases)))
            & (NewsArticleSymbol.symbol == sym)
        )
        legacy_match = (
            (NewsArticle.exchange_code == market)
            & (NewsArticle.symbol == sym)
        )

        stmt = (
            select(NewsArticle, NewsSummary)
            .outerjoin(
                NewsSummary,
                NewsSummary.article_id == NewsArticle.article_id,
            )
            .outerjoin(
                NewsArticleSymbol,
                NewsArticleSymbol.article_id == NewsArticle.article_id,
            )
            .where(or_(link_match, legacy_match))
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.article_id.desc(),
            )
            .limit(max(1, int(limit)))
        )
        # outerjoin으로 중복 행이 생길 수 있어 article_id 기준 고유화
        seen: set[int] = set()
        out: list[tuple[NewsArticle, NewsSummary | None]] = []
        for article, summary in self._session.execute(stmt).all():
            aid = int(article.article_id)
            if aid in seen:
                continue
            seen.add(aid)
            out.append((article, summary))
        return out

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

    # --- STEP N2 collector (symbol 링크 생성 금지) ---

    def find_by_content_hash(self, content_hash: str) -> NewsArticle | None:
        return self._session.scalar(
            select(NewsArticle).where(
                NewsArticle.content_hash == content_hash
            )
        )

    def find_by_original_link(self, url: str) -> NewsArticle | None:
        if not url:
            return None
        return self._session.scalar(
            select(NewsArticle)
            .where(NewsArticle.original_link == url)
            .order_by(NewsArticle.article_id.desc())
            .limit(1)
        )

    def find_by_source_external_id(
        self,
        *,
        source_code: str,
        external_id: str,
    ) -> NewsArticle | None:
        """raw_data.external_id 로 조회 (N2 — migration 없이 재사용)."""

        return self._session.scalar(
            select(NewsArticle)
            .where(
                NewsArticle.source_code == source_code,
                NewsArticle.raw_data["external_id"].astext == str(external_id),
            )
            .order_by(NewsArticle.article_id.desc())
            .limit(1)
        )

    def upsert_collector_article(self, row: dict) -> str:
        """COLLECT store — news_article_symbol 링크 없음.

        Returns: inserted | updated | duplicate
        """

        content_hash = str(row["content_hash"])
        existing = self.find_by_content_hash(content_hash)
        if existing is None and row.get("original_link"):
            existing = self.find_by_original_link(str(row["original_link"]))

        if existing is None:
            ext = None
            raw = row.get("raw_data") or {}
            if isinstance(raw, dict):
                ext = raw.get("external_id")
            if ext is not None:
                existing = self.find_by_source_external_id(
                    source_code=str(row["source_code"]),
                    external_id=str(ext),
                )

        if existing is None:
            entity = NewsArticle(**row)
            self._session.add(entity)
            self._session.flush()
            return "inserted"

        # 내용 변경 여부 — body_fingerprint / title / published_at
        incoming_raw = row.get("raw_data") or {}
        prev_raw = existing.raw_data or {}
        changed = False
        if existing.title != row.get("title"):
            existing.title = row["title"]
            changed = True
        if (existing.description or None) != (row.get("description") or None):
            existing.description = row.get("description")
            changed = True
        if (existing.original_link or None) != (
            row.get("original_link") or None
        ):
            existing.original_link = row.get("original_link")
            changed = True
        if row.get("published_at") is not None and (
            existing.published_at != row.get("published_at")
        ):
            existing.published_at = row.get("published_at")
            changed = True
        # identity hash 유지 — content_hash 는 바꾸지 않음
        if isinstance(incoming_raw, dict):
            merged = dict(prev_raw) if isinstance(prev_raw, dict) else {}
            merged.update(incoming_raw)
            prev_fp = (
                prev_raw.get("body_fingerprint")
                if isinstance(prev_raw, dict)
                else None
            )
            new_fp = incoming_raw.get("body_fingerprint")
            if new_fp and new_fp != prev_fp:
                changed = True
            existing.raw_data = merged

        if changed:
            self._session.flush()
            return "updated"
        return "duplicate"

    def list_by_source_codes(
        self,
        *,
        source_codes: list[str],
        limit: int = 20,
    ) -> list[NewsArticle]:
        if not source_codes:
            return []
        codes = [c.upper() for c in source_codes]
        stmt = (
            select(NewsArticle)
            .where(NewsArticle.source_code.in_(codes))
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.article_id.desc(),
            )
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def latest_published_at(self, *, source_code: str) -> object | None:
        from sqlalchemy import func

        return self._session.scalar(
            select(func.max(NewsArticle.published_at)).where(
                NewsArticle.source_code == source_code
            )
        )

    def get_articles_by_ids(self, article_ids: list[int]) -> list[NewsArticle]:
        if not article_ids:
            return []
        return list(
            self._session.scalars(
                select(NewsArticle).where(
                    NewsArticle.article_id.in_(article_ids)
                )
            )
        )

    def upsert_symbol_mapping_link(
        self,
        *,
        article_id: int,
        market_code: str,
        symbol: str,
        match_type: str,
        relevance_score: Decimal,
    ) -> str:
        """article_id+market+symbol 멱등. hard delete 없음.

        Returns: inserted | updated | duplicate
        """

        market = str(market_code).upper()
        sym = str(symbol).upper()
        # placeholder 절대 저장 금지
        if sym.startswith("_") or sym in {"_NOTICE_", "_CRYPTO_"}:
            return "duplicate"

        existing = self._session.scalar(
            select(NewsArticleSymbol).where(
                NewsArticleSymbol.article_id == article_id,
                NewsArticleSymbol.market_code == market,
                NewsArticleSymbol.symbol == sym,
            )
        )
        score = Decimal(str(relevance_score))
        mt = str(match_type)[:30]
        if existing is None:
            stmt = insert(NewsArticleSymbol).values(
                article_id=article_id,
                market_code=market,
                symbol=sym,
                match_type=mt,
                relevance_score=score,
            )
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["article_id", "market_code", "symbol"],
            )
            result = self._session.execute(stmt)
            self._session.flush()
            # race: conflict → duplicate
            if (result.rowcount or 0) == 0:
                return "duplicate"
            return "inserted"

        changed = False
        if existing.match_type != mt:
            existing.match_type = mt
            changed = True
        if Decimal(str(existing.relevance_score)) != score:
            # evidence 강화 시에만 상향/갱신
            if score >= Decimal(str(existing.relevance_score)):
                existing.relevance_score = score
                changed = True
        if changed:
            self._session.flush()
            return "updated"
        return "duplicate"

    def list_mappings_with_articles(
        self,
        *,
        source_codes: list[str],
        limit: int = 20,
    ) -> list[tuple[NewsArticle, list[NewsArticleSymbol]]]:
        articles = self.list_by_source_codes(
            source_codes=source_codes,
            limit=limit,
        )
        if not articles:
            return []
        ids = [int(a.article_id) for a in articles]
        links = self.list_symbol_links(ids)
        by_article: dict[int, list[NewsArticleSymbol]] = {}
        for link in links:
            if str(link.symbol).upper().startswith("_"):
                continue
            by_article.setdefault(int(link.article_id), []).append(link)
        return [(a, by_article.get(int(a.article_id), [])) for a in articles]

    def reconcile_resolver_links(
        self,
        *,
        article_id: int,
        keep_symbols: set[str],
        resolver_match_types: set[str],
    ) -> int:
        """재매핑 시 resolver가 만든 링크만 정리 — PROVIDER 링크는 보존.

        hard delete of article 금지. stale resolver link row만 제거.
        """

        links = self.list_symbol_links([article_id])
        removed = 0
        for link in links:
            mt = str(link.match_type or "")
            if mt not in resolver_match_types:
                continue
            if str(link.symbol).upper() in keep_symbols:
                continue
            self._session.delete(link)
            removed += 1
        if removed:
            self._session.flush()
        return removed
