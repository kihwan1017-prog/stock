"""Realtime tick → timeframe bar 집계.

DB persist 없음. canonical daily SoT는 market.price_daily collector.
UPBIT 24/7 1D 경계는 Asia/Seoul 달력일 00:00.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_platform.realtime.market_event import RealtimeMarketEvent


_KST = ZoneInfo("Asia/Seoul")


def kst_trading_date(moment: datetime) -> date:
    """이벤트 시각을 KST 달력일로 변환한다."""

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_KST).date()


@dataclass(frozen=True, slots=True)
class RollingDailyBar:
    """현재 거래일의 in-memory rolling 일봉. close만 MA에 사용."""

    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    started_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DailyBarUpdate:
    """Evaluator deque에 반영할 일봉 close 갱신."""

    trade_date: date
    close: Decimal
    replaced_last: bool
    rolling: RollingDailyBar


class RealtimeTimeframeBarAggregator:
    """scope 내부 종목별 rolling 일봉. 다른 scope와 공유 금지.

    키: symbol (evaluator가 이미 scope 단위).
    같은 날 tick은 last close만 교체하고 일수를 늘리지 않는다.
    """

    def __init__(self, *, scope_key: str, timeframe: str = "1D") -> None:
        self.scope_key = scope_key
        self.timeframe = timeframe
        self._current: dict[str, RollingDailyBar] = {}

    def current_bar(self, symbol: str) -> RollingDailyBar | None:
        return self._current.get(symbol.upper())

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._current.clear()
            return
        self._current.pop(symbol.upper(), None)

    def prime(
        self,
        symbol: str,
        *,
        trade_date: date,
        close: Decimal,
        at: datetime | None = None,
    ) -> DailyBarUpdate:
        """restart bootstrap용 현재일 봉 seed. 신호 SoT가 아니다."""

        key = symbol.upper()
        now = at or datetime.now(timezone.utc)
        existing = self._current.get(key)
        replaced = existing is not None and existing.trade_date == trade_date
        if replaced and existing is not None:
            rolling = RollingDailyBar(
                trade_date=trade_date,
                open_price=existing.open_price,
                high_price=max(existing.high_price, close),
                low_price=min(existing.low_price, close),
                close_price=close,
                started_at=existing.started_at,
                updated_at=now,
            )
        else:
            rolling = RollingDailyBar(
                trade_date=trade_date,
                open_price=close,
                high_price=close,
                low_price=close,
                close_price=close,
                started_at=now,
                updated_at=now,
            )
        self._current[key] = rolling
        return DailyBarUpdate(
            trade_date=trade_date,
            close=close,
            replaced_last=replaced,
            rolling=rolling,
        )

    def ingest(self, event: RealtimeMarketEvent) -> DailyBarUpdate | None:
        """tick → 당일 rolling OHLC. volume은 MA에 쓰지 않으므로 누적하지 않는다."""

        if event.price is None:
            return None
        key = event.symbol.upper()
        price = event.price
        trade_date = kst_trading_date(event.event_time)
        existing = self._current.get(key)
        if existing is None or existing.trade_date != trade_date:
            rolling = RollingDailyBar(
                trade_date=trade_date,
                open_price=price,
                high_price=price,
                low_price=price,
                close_price=price,
                started_at=event.event_time,
                updated_at=event.event_time,
            )
            self._current[key] = rolling
            return DailyBarUpdate(
                trade_date=trade_date,
                close=price,
                replaced_last=False,
                rolling=rolling,
            )
        rolling = RollingDailyBar(
            trade_date=existing.trade_date,
            open_price=existing.open_price,
            high_price=max(existing.high_price, price),
            low_price=min(existing.low_price, price),
            close_price=price,
            started_at=existing.started_at,
            updated_at=event.event_time,
        )
        self._current[key] = rolling
        return DailyBarUpdate(
            trade_date=trade_date,
            close=price,
            replaced_last=True,
            rolling=rolling,
        )
