"""관심종목 서비스 — STEP67."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument
from stock_platform.markets.repository import InstrumentRepository
from stock_platform.trading.watchlist_models import WatchlistItem
from stock_platform.trading.watchlist_repository import WatchlistRepository


MAX_WATCHLIST_ITEMS = 50


class WatchlistError(ValueError):
    """도메인 오류."""


def _item_dict(row: WatchlistItem) -> dict[str, Any]:
    return {
        "watchlist_id": row.watchlist_id,
        "user_id": row.user_id,
        "market": row.market,
        "symbol": row.symbol,
        "symbol_name": row.symbol_name,
        "display_order": row.display_order,
        "memo": row.memo,
        "color": row.color,
        "alarm_enabled": bool(row.alarm_enabled),
        "news_enabled": bool(row.news_enabled),
        "disclosure_enabled": bool(row.disclosure_enabled),
        "ai_enabled": bool(row.ai_enabled),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class WatchlistService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = WatchlistRepository(session)
        self._instruments = InstrumentRepository(session)

    def list_items(self, user_id: int) -> dict[str, Any]:
        rows = self._repo.list_for_user(user_id)
        return {
            "items": [_item_dict(row) for row in rows],
            "total": len(rows),
            "max_items": MAX_WATCHLIST_ITEMS,
        }

    def add_item(
        self,
        user_id: int,
        *,
        market: str,
        symbol: str,
        symbol_name: str | None = None,
        memo: str | None = None,
        color: str | None = None,
        alarm_enabled: bool = False,
        news_enabled: bool = True,
        disclosure_enabled: bool = True,
        ai_enabled: bool = True,
    ) -> dict[str, Any]:
        market_code = (market or "").strip().upper()
        symbol_code = (symbol or "").strip().upper()
        if not market_code or not symbol_code:
            raise WatchlistError("market 과 symbol 이 필요합니다.")

        if self._repo.count_for_user(user_id) >= MAX_WATCHLIST_ITEMS:
            raise WatchlistError(
                f"관심종목은 최대 {MAX_WATCHLIST_ITEMS}개까지 등록할 수 있습니다."
            )

        if self._repo.find_by_symbol(
            user_id=user_id,
            market=market_code,
            symbol=symbol_code,
        ):
            raise WatchlistError("이미 등록된 관심종목입니다.")

        name = (symbol_name or "").strip()
        instrument = self._instruments.find(market_code, symbol_code)
        if instrument is not None:
            name = name or instrument.name
            market_code = instrument.exchange_code
            symbol_code = instrument.symbol
        if not name:
            name = symbol_code

        row = WatchlistItem(
            user_id=user_id,
            market=market_code,
            symbol=symbol_code,
            symbol_name=name[:200],
            display_order=self._repo.max_display_order(user_id) + 1,
            memo=(memo.strip()[:500] if memo else None),
            color=(color.strip()[:20] if color else None),
            alarm_enabled=alarm_enabled,
            news_enabled=news_enabled,
            disclosure_enabled=disclosure_enabled,
            ai_enabled=ai_enabled,
        )
        try:
            saved = self._repo.save(row)
        except IntegrityError as exc:
            self._session.rollback()
            raise WatchlistError("이미 등록된 관심종목입니다.") from exc
        return _item_dict(saved)

    def update_item(
        self,
        user_id: int,
        watchlist_id: int,
        *,
        memo: str | None = None,
        color: str | None = None,
        symbol_name: str | None = None,
        alarm_enabled: bool | None = None,
        news_enabled: bool | None = None,
        disclosure_enabled: bool | None = None,
        ai_enabled: bool | None = None,
        display_order: int | None = None,
        clear_memo: bool = False,
        clear_color: bool = False,
    ) -> dict[str, Any]:
        row = self._repo.get_owned(
            user_id=user_id, watchlist_id=watchlist_id
        )
        if row is None:
            raise WatchlistError("관심종목을 찾을 수 없습니다.")

        if clear_memo:
            row.memo = None
        elif memo is not None:
            row.memo = memo.strip()[:500] or None
        if clear_color:
            row.color = None
        elif color is not None:
            row.color = color.strip()[:20] or None
        if symbol_name is not None:
            name = symbol_name.strip()
            if name:
                row.symbol_name = name[:200]
        if alarm_enabled is not None:
            row.alarm_enabled = alarm_enabled
        if news_enabled is not None:
            row.news_enabled = news_enabled
        if disclosure_enabled is not None:
            row.disclosure_enabled = disclosure_enabled
        if ai_enabled is not None:
            row.ai_enabled = ai_enabled
        if display_order is not None:
            row.display_order = int(display_order)

        self._repo.commit()
        self._session.refresh(row)
        return _item_dict(row)

    def delete_item(self, user_id: int, watchlist_id: int) -> dict[str, Any]:
        row = self._repo.get_owned(
            user_id=user_id, watchlist_id=watchlist_id
        )
        if row is None:
            raise WatchlistError("관심종목을 찾을 수 없습니다.")
        payload = _item_dict(row)
        self._repo.delete(row)
        return {"deleted": True, "item": payload}

    def reorder(
        self,
        user_id: int,
        ordered_ids: list[int],
    ) -> dict[str, Any]:
        if not ordered_ids:
            raise WatchlistError("ordered_ids 가 필요합니다.")

        owned = {
            int(row.watchlist_id): row
            for row in self._repo.list_for_user(user_id)
        }
        if set(ordered_ids) != set(owned.keys()):
            # 부분 재정렬도 허용 — 전달된 ID만 순서 반영, 나머지는 뒤로
            unknown = [i for i in ordered_ids if i not in owned]
            if unknown:
                raise WatchlistError(
                    "다른 사용자의 관심종목이거나 존재하지 않는 ID입니다."
                )

        for index, watchlist_id in enumerate(ordered_ids):
            owned[watchlist_id].display_order = index + 1

        # 목록에 없던 항목은 뒤쪽에 유지
        remaining = [
            row
            for wid, row in owned.items()
            if wid not in set(ordered_ids)
        ]
        remaining.sort(key=lambda r: (r.display_order, r.watchlist_id))
        base = len(ordered_ids)
        for offset, row in enumerate(remaining):
            row.display_order = base + offset + 1

        self._repo.commit()
        return self.list_items(user_id)

    def search_symbols(
        self,
        *,
        query: str,
        market: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if len(q) < 1:
            return []
        limit = max(1, min(limit, 50))
        pattern = f"%{q.upper()}%"
        stmt = select(Instrument).where(
            Instrument.is_active.is_(True),
            or_(
                Instrument.symbol.ilike(pattern),
                Instrument.name.ilike(f"%{q}%"),
            ),
        )
        if market:
            stmt = stmt.where(
                Instrument.exchange_code == market.strip().upper()
            )
        stmt = stmt.order_by(
            Instrument.symbol.asc()
        ).limit(limit)
        rows = list(self._session.scalars(stmt))
        return [
            {
                "market": row.exchange_code,
                "symbol": row.symbol,
                "symbol_name": row.name,
                "name": row.name,
                "asset_type": row.asset_type,
                "currency": row.currency_code,
            }
            for row in rows
        ]
