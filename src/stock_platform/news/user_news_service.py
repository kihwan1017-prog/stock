"""회원 관심종목 뉴스 서비스 — STEP68."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.news.models import NewsArticle
from stock_platform.news.repository import NewsRepository
from stock_platform.trading.watchlist_repository import WatchlistRepository


SOURCE_NAMES = {
    "NAVER": "네이버 뉴스",
}


class UserNewsError(ValueError):
    pass


class UserNewsService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._news = NewsRepository(session)
        self._watchlist = WatchlistRepository(session)

    def _watchlist_pairs(
        self,
        user_id: int,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
        watchlist_id: int | None = None,
    ) -> list[tuple[str, str, str]]:
        """(market, symbol, symbol_name) 목록 — news_enabled만."""

        rows = self._watchlist.list_for_user(user_id)
        result: list[tuple[str, str, str]] = []
        for row in rows:
            if not row.news_enabled:
                continue
            if watchlist_id is not None and int(row.watchlist_id) != int(
                watchlist_id
            ):
                continue
            if market_code and row.market.upper() != market_code.upper():
                continue
            if symbol and row.symbol.upper() != symbol.upper():
                continue
            result.append(
                (row.market.upper(), row.symbol.upper(), row.symbol_name)
            )
        return result

    def list_news(
        self,
        user_id: int,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
        watchlist_id: int | None = None,
        keyword: str | None = None,
        source_code: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        read_status: str | None = None,
        bookmarked: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        # 관심종목(news_enabled) 전체 — 소유권·빈 목록 판별용
        all_enabled = self._watchlist_pairs(user_id)
        if not all_enabled:
            return {
                "items": [],
                "page": page,
                "page_size": page_size,
                "total_count": 0,
                "has_next": False,
                "watchlist_empty": True,
                "message": "관심종목을 먼저 등록해 주세요.",
            }

        # 심볼 필터가 관심종목에 없으면 거부 (타 종목 조회 차단)
        if symbol and not any(
            p[1] == symbol.upper()
            and (
                not market_code
                or p[0] == market_code.upper()
            )
            for p in all_enabled
        ):
            raise UserNewsError(
                "해당 종목은 관심종목에 없거나 뉴스 수집이 비활성입니다."
            )

        pairs_full = self._watchlist_pairs(
            user_id,
            market_code=market_code,
            symbol=symbol,
            watchlist_id=watchlist_id,
        )
        if not pairs_full:
            return {
                "items": [],
                "page": page,
                "page_size": page_size,
                "total_count": 0,
                "has_next": False,
                "watchlist_empty": False,
            }

        symbol_pairs = [(m, s) for m, s, _ in pairs_full]
        name_map = {(m, s): n for m, s, n in pairs_full}

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        date_from_dt = (
            datetime.combine(from_date, time.min, tzinfo=timezone.utc)
            if from_date
            else None
        )
        date_to_dt = (
            datetime.combine(to_date, time.max, tzinfo=timezone.utc)
            if to_date
            else None
        )

        needs_state_filter = (
            read_status in ("read", "unread") or bookmarked is not None
        )

        if needs_state_filter:
            # 읽음/북마크 필터는 사용자 상태 Join 없이 메모리 필터 (관심종목 소규모 전제)
            articles = self._news.list_for_symbols(
                symbol_pairs=symbol_pairs,
                limit=500,
                offset=0,
                keyword=keyword,
                source_code=source_code,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            states = self._news.list_user_states(
                user_id=user_id,
                article_ids=[int(a.article_id) for a in articles],
            )
            filtered: list[NewsArticle] = []
            for article in articles:
                state = states.get(int(article.article_id))
                if state and state.hidden_at is not None:
                    continue
                is_read = bool(state.is_read) if state else False
                is_bookmarked = bool(state.is_bookmarked) if state else False
                if read_status == "read" and not is_read:
                    continue
                if read_status == "unread" and is_read:
                    continue
                if bookmarked is True and not is_bookmarked:
                    continue
                if bookmarked is False and is_bookmarked:
                    continue
                filtered.append(article)
            total = len(filtered)
            start = (page - 1) * page_size
            page_items = filtered[start : start + page_size]
        else:
            total = self._news.count_for_symbols(
                symbol_pairs=symbol_pairs,
                keyword=keyword,
                source_code=source_code,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            offset = (page - 1) * page_size
            page_items = self._news.list_for_symbols(
                symbol_pairs=symbol_pairs,
                limit=page_size,
                offset=offset,
                keyword=keyword,
                source_code=source_code,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            states = self._news.list_user_states(
                user_id=user_id,
                article_ids=[int(a.article_id) for a in page_items],
            )

        links = self._news.list_symbol_links(
            [int(a.article_id) for a in page_items]
        )
        links_by_article: dict[int, list] = {}
        for link in links:
            links_by_article.setdefault(int(link.article_id), []).append(
                link
            )

        items = [
            self._item_dict(
                article,
                user_id=user_id,
                states=states,
                links_by_article=links_by_article,
                name_map=name_map,
                watchlist_pairs=symbol_pairs,
            )
            for article in page_items
        ]
        start = (page - 1) * page_size
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "has_next": start + page_size < total,
            "watchlist_empty": False,
        }

    def get_detail(
        self,
        user_id: int,
        news_id: int,
    ) -> dict[str, Any]:
        article = self._news.get_article(news_id)
        if article is None:
            raise UserNewsError("뉴스를 찾을 수 없습니다.")
        pairs_full = self._watchlist_pairs(user_id)
        symbol_pairs = [(m, s) for m, s, _ in pairs_full]
        name_map = {(m, s): n for m, s, n in pairs_full}
        if not self._article_visible(article, symbol_pairs):
            raise UserNewsError("관심종목과 연결되지 않은 뉴스입니다.")
        states = self._news.list_user_states(
            user_id=user_id, article_ids=[news_id]
        )
        links = self._news.list_symbol_links([news_id])
        return self._item_dict(
            article,
            user_id=user_id,
            states=states,
            links_by_article={news_id: links},
            name_map=name_map,
            watchlist_pairs=symbol_pairs,
            include_summary=True,
        )

    def mark_read(
        self, user_id: int, news_id: int, *, read: bool = True
    ) -> dict[str, Any]:
        self.get_detail(user_id, news_id)  # 가시성 검증
        state = self._news.get_or_create_user_state(
            user_id=user_id, article_id=news_id
        )
        state.is_read = read
        state.read_at = datetime.now(timezone.utc) if read else None
        self._session.commit()
        self._session.refresh(state)
        return {
            "news_id": news_id,
            "is_read": state.is_read,
            "read_at": state.read_at,
        }

    def mark_bookmark(
        self, user_id: int, news_id: int, *, bookmarked: bool = True
    ) -> dict[str, Any]:
        self.get_detail(user_id, news_id)
        state = self._news.get_or_create_user_state(
            user_id=user_id, article_id=news_id
        )
        state.is_bookmarked = bookmarked
        state.bookmarked_at = (
            datetime.now(timezone.utc) if bookmarked else None
        )
        self._session.commit()
        self._session.refresh(state)
        return {
            "news_id": news_id,
            "is_bookmarked": state.is_bookmarked,
            "bookmarked_at": state.bookmarked_at,
        }

    def read_all(
        self,
        user_id: int,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """현재 관심종목(선택 필터) 미읽음 뉴스 전체 읽음."""

        updated = 0
        for _ in range(50):
            listed = self.list_news(
                user_id,
                market_code=market_code,
                symbol=symbol,
                read_status="unread",
                page=1,
                page_size=100,
            )
            items = listed.get("items") or []
            if not items:
                break
            for item in items:
                self.mark_read(user_id, int(item["news_id"]), read=True)
                updated += 1
        return {"updated_count": updated, "scope": "watchlist_unread"}

    def unread_count(self, user_id: int) -> dict[str, Any]:
        listed = self.list_news(
            user_id, read_status="unread", page=1, page_size=500
        )
        by_symbol: dict[tuple[str, str], int] = {}
        total = int(listed.get("total_count") or 0)
        for item in listed.get("items") or []:
            for matched in item.get("matched_symbols") or []:
                key = (
                    str(matched["market_code"]),
                    str(matched["symbol"]),
                )
                by_symbol[key] = by_symbol.get(key, 0) + 1
        return {
            "unread_count": total,
            "total": total,
            "by_symbol": [
                {
                    "market_code": m,
                    "symbol": s,
                    "count": c,
                }
                for (m, s), c in sorted(by_symbol.items())
            ],
        }

    def _article_visible(
        self,
        article: NewsArticle,
        symbol_pairs: list[tuple[str, str]],
    ) -> bool:
        pair_set = {(m, s) for m, s in symbol_pairs}
        if (article.exchange_code.upper(), article.symbol.upper()) in pair_set:
            return True
        links = self._news.list_symbol_links([int(article.article_id)])
        return any(
            (link.market_code.upper(), link.symbol.upper()) in pair_set
            for link in links
        )

    def _item_dict(
        self,
        article: NewsArticle,
        *,
        user_id: int,
        states: dict,
        links_by_article: dict,
        name_map: dict[tuple[str, str], str],
        watchlist_pairs: list[tuple[str, str]],
        include_summary: bool = False,
    ) -> dict[str, Any]:
        _ = user_id
        state = states.get(int(article.article_id))
        pair_set = set(watchlist_pairs)
        matched: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for link in links_by_article.get(int(article.article_id), []):
            key = (link.market_code.upper(), link.symbol.upper())
            if key not in pair_set or key in seen:
                continue
            seen.add(key)
            matched.append(
                {
                    "market_code": key[0],
                    "symbol": key[1],
                    "symbol_name": name_map.get(key, key[1]),
                    "relevance_score": float(link.relevance_score),
                    "match_type": link.match_type,
                }
            )
        legacy = (
            article.exchange_code.upper(),
            article.symbol.upper(),
        )
        if legacy in pair_set and legacy not in seen:
            matched.append(
                {
                    "market_code": legacy[0],
                    "symbol": legacy[1],
                    "symbol_name": name_map.get(legacy, legacy[1]),
                    "relevance_score": 1.0,
                    "match_type": "PROVIDER",
                }
            )

        payload: dict[str, Any] = {
            "news_id": article.article_id,
            "title": article.title,
            "summary": article.description,
            "source_code": article.source_code,
            "source_name": SOURCE_NAMES.get(
                article.source_code, article.source_code
            ),
            "original_url": article.original_link or article.naver_link,
            "published_at": article.published_at,
            "matched_symbols": matched,
            "is_read": bool(state.is_read) if state else False,
            "is_bookmarked": bool(state.is_bookmarked) if state else False,
        }
        if include_summary:
            payload["collected_at"] = article.created_at
        return payload
