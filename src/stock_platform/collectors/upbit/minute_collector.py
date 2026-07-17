from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.markets.models import ALLOWED_MINUTE_TIMEFRAMES


class UpbitMinuteParseError(ValueError):
    """업비트 분봉 행 파싱 실패."""


@dataclass(frozen=True, slots=True)
class UpbitMinutePriceDTO:
    candle_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    trade_value: Decimal

    def to_price_row(self) -> dict[str, Any]:
        return {
            "candle_at": self.candle_at,
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "close_price": self.close_price,
            "volume": self.volume,
            "trade_value": self.trade_value,
        }


class UpbitMinuteParser:
    """업비트 분봉 응답을 표준 행으로 변환한다."""

    def parse(
        self,
        rows: list[dict[str, Any]],
    ) -> list[UpbitMinutePriceDTO]:
        parsed: list[UpbitMinutePriceDTO] = []
        for index, row in enumerate(rows):
            try:
                parsed.append(self._parse_row(row))
            except (
                KeyError,
                ValueError,
                TypeError,
                InvalidOperation,
            ) as exc:
                raise UpbitMinuteParseError(
                    f"Invalid minute candle at index {index}: {exc}"
                ) from exc
        return parsed

    def _parse_row(self, row: dict[str, Any]) -> UpbitMinutePriceDTO:
        raw_utc = str(row["candle_date_time_utc"])
        candle_at = datetime.fromisoformat(raw_utc).replace(
            tzinfo=timezone.utc
        )

        return UpbitMinutePriceDTO(
            candle_at=candle_at,
            open_price=self._decimal(row["opening_price"]),
            high_price=self._decimal(row["high_price"]),
            low_price=self._decimal(row["low_price"]),
            close_price=self._decimal(row["trade_price"]),
            volume=self._decimal(
                row.get("candle_acc_trade_volume", 0)
            ),
            trade_value=self._decimal(
                row.get("candle_acc_trade_price", 0)
            ),
        )

    @staticmethod
    def utc_cursor(row: dict[str, Any]) -> str:
        raw = str(row["candle_date_time_utc"])
        return f"{raw}Z" if not raw.endswith("Z") else raw

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return Decimal(str(value).replace(",", "").strip())


class UpbitMinuteCollectionError(RuntimeError):
    """분봉 페이지네이션 실패."""


class UpbitMinuteCollector:
    """업비트 분봉 REST 수집기."""

    def __init__(
        self,
        client: Any,
        parser: UpbitMinuteParser | None = None,
    ) -> None:
        self._client = client
        self._parser = parser or UpbitMinuteParser()

    async def collect(
        self,
        *,
        market: str,
        timeframe: int,
        start_at: datetime,
        end_at: datetime,
        max_pages: int = 100,
    ) -> list[UpbitMinutePriceDTO]:
        if timeframe not in ALLOWED_MINUTE_TIMEFRAMES:
            raise ValueError(
                f"timeframe must be one of {ALLOWED_MINUTE_TIMEFRAMES}"
            )

        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)

        if start_at > end_at:
            raise ValueError("start_at must not be after end_at")

        cursor: str | None = end_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows_by_at: dict[datetime, UpbitMinutePriceDTO] = {}

        for page in range(1, max_pages + 1):
            raw_rows = await self._client.list_minute_candles(
                market=market.strip().upper(),
                unit=timeframe,
                to=cursor,
                count=200,
            )
            if not raw_rows:
                break

            parsed = self._parser.parse(raw_rows)
            oldest: datetime | None = None

            for item in parsed:
                if oldest is None or item.candle_at < oldest:
                    oldest = item.candle_at
                if start_at <= item.candle_at <= end_at:
                    rows_by_at[item.candle_at] = item

            if oldest is not None and oldest <= start_at:
                break

            next_cursor = self._parser.utc_cursor(raw_rows[-1])
            if next_cursor == cursor:
                raise UpbitMinuteCollectionError(
                    "Pagination cursor did not advance"
                )
            cursor = next_cursor
        else:
            raise UpbitMinuteCollectionError(
                f"Exceeded max_pages={max_pages}"
            )

        return sorted(
            rows_by_at.values(),
            key=lambda item: item.candle_at,
        )
