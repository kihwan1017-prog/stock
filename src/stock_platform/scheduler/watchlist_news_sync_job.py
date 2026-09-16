"""활성 관심종목 뉴스 수집 Job — STEP68."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.common.settings import get_settings
from stock_platform.news.naver_client import NaverNewsClient, NaverNewsError
from stock_platform.news.repository import NewsRepository
from stock_platform.news.service import NewsService
from stock_platform.trading.watchlist_models import WatchlistItem


class WatchlistNewsSyncJob:
    """news_enabled 관심종목의 distinct (market, symbol)만 수집."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        display = int(payload.get("display") or 20)
        display = max(1, min(display, 50))

        rows = list(
            self._session.scalars(
                select(WatchlistItem).where(
                    WatchlistItem.news_enabled.is_(True)
                )
            )
        )
        # 중복 종목 제거
        unique: dict[tuple[str, str], WatchlistItem] = {}
        for row in rows:
            key = (row.market.upper(), row.symbol.upper())
            unique[key] = row

        naver = NaverNewsClient(settings=settings)
        ollama = OllamaClient(settings=settings)
        service = NewsService(
            repository=NewsRepository(self._session),
            naver_client=naver,
            ollama_client=ollama,
            model_name=settings.ollama_model,
        )

        synced = 0
        failed = 0
        saved_total = 0
        errors: list[dict[str, Any]] = []
        try:
            for (market, symbol), item in unique.items():
                query = (item.symbol_name or symbol).strip() or symbol
                try:
                    result = await service.sync_detailed(
                        exchange_code=market,
                        symbol=symbol,
                        query=query,
                        display=display,
                    )
                    synced += 1
                    saved_total += int(result.saved_count)
                except (ValueError, NaverNewsError, Exception) as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(
                        {
                            "market": market,
                            "symbol": symbol,
                            "error": str(exc)[:200],
                        }
                    )
        finally:
            await naver.aclose()
            await ollama.aclose()

        return {
            "job": "watchlist_news_sync",
            "symbol_count": len(unique),
            "synced": synced,
            "failed": failed,
            "saved_total": saved_total,
            "errors": errors[:20],
            "note": "공용 뉴스 1회 저장 — 사용자별 중복 저장 없음",
        }
