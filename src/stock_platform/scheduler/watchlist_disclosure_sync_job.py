"""활성 관심종목 DART 공시 수집 Job — STEP69."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.disclosure.dart_client import DartClient, DartError
from stock_platform.disclosure.repository import (
    DartCorpRepository,
    DartDisclosureRepository,
)
from stock_platform.disclosure.service import DartDisclosureService
from stock_platform.trading.watchlist_models import WatchlistItem


class WatchlistDisclosureSyncJob:
    """disclosure_enabled 관심종목의 distinct stock_code만 수집."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        if not (settings.dart_api_key or "").strip():
            return {
                "job": "watchlist_disclosure_sync",
                "skipped": True,
                "reason": (
                    "DART API Key 미설정 — 수집만 중단, 기존 공시 조회 가능"
                ),
            }

        days = int(payload.get("days") or 7)
        days = max(1, min(days, 90))
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        rows = list(
            self._session.scalars(
                select(WatchlistItem).where(
                    WatchlistItem.disclosure_enabled.is_(True)
                )
            )
        )
        unique_symbols: dict[str, WatchlistItem] = {}
        for row in rows:
            if row.market.upper() not in {"KRX", "KOSPI", "KOSDAQ"}:
                continue
            unique_symbols[row.symbol.upper()] = row

        client = DartClient(settings=settings)
        service = DartDisclosureService(
            client,
            DartDisclosureRepository(self._session),
            corp_repository=DartCorpRepository(self._session),
        )

        synced = 0
        failed = 0
        saved_total = 0
        mapping_failed = 0
        errors: list[dict[str, Any]] = []
        try:
            for symbol, item in unique_symbols.items():
                try:
                    result = await service.sync_by_stock_code(
                        stock_code=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        resume=True,
                    )
                    synced += 1
                    saved_total += int(result.saved_count)
                except LookupError as exc:
                    mapping_failed += 1
                    errors.append(
                        {"symbol": symbol, "error": str(exc)[:200]}
                    )
                except (DartError, ValueError, Exception) as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(
                        {
                            "symbol": symbol,
                            "name": item.symbol_name,
                            "error": str(exc)[:200],
                        }
                    )
        finally:
            await client.aclose()

        return {
            "job": "watchlist_disclosure_sync",
            "symbol_count": len(unique_symbols),
            "synced": synced,
            "failed": failed,
            "mapping_failed": mapping_failed,
            "saved_total": saved_total,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "errors": errors[:20],
            "note": "공용 공시 1회 저장 — 사용자별 중복 수집 없음",
        }
