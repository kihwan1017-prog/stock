from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.collectors.upbit.dto import UpbitDailyPriceDTO


class UpbitDailyParseError(ValueError):
    """Raised when an Upbit candle row is invalid."""


class UpbitDailyParser:
    """Parse Upbit day-candle responses."""

    def parse(
        self,
        rows: list[dict[str, Any]],
    ) -> list[UpbitDailyPriceDTO]:
        parsed: list[UpbitDailyPriceDTO] = []

        for index, row in enumerate(rows):
            try:
                parsed.append(self._parse_row(row))
            except (
                KeyError,
                ValueError,
                TypeError,
                InvalidOperation,
            ) as exc:
                raise UpbitDailyParseError(
                    f"Invalid Upbit candle at index {index}: {exc}"
                ) from exc

        return parsed

    def _parse_row(
        self,
        row: dict[str, Any],
    ) -> UpbitDailyPriceDTO:
        trade_date = datetime.strptime(
            str(row["candle_date_time_kst"])[:10],
            "%Y-%m-%d",
        ).date()

        signed_change_rate = row.get("signed_change_rate")
        change_rate = (
            self._decimal(signed_change_rate) * Decimal("100")
            if signed_change_rate is not None
            else None
        )

        open_price = self._decimal(row["opening_price"])
        high_price = self._decimal(row["high_price"])
        low_price = self._decimal(row["low_price"])
        close_price = self._decimal(row["trade_price"])
        volume = self._decimal(row.get("candle_acc_trade_volume", 0))
        self.validate_ohlc(
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
        )

        return UpbitDailyPriceDTO(
            trade_date=trade_date,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
            trade_value=self._decimal(
                row.get("candle_acc_trade_price", 0)
            ),
            change_rate=change_rate,
        )

    @staticmethod
    def utc_cursor(row: dict[str, Any]) -> str:
        raw = str(row["candle_date_time_utc"])
        return f"{raw}Z" if not raw.endswith("Z") else raw

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return Decimal(str(value).replace(",", "").strip())

    @staticmethod
    def validate_ohlc(
        *,
        open_price: Decimal,
        high_price: Decimal,
        low_price: Decimal,
        close_price: Decimal,
        volume: Decimal,
    ) -> None:
        """완료 일봉 OHLC 계약. 0·음수·고저 역전은 거부."""

        if min(open_price, high_price, low_price, close_price) <= Decimal("0"):
            raise UpbitDailyParseError("OHLC must be greater than zero")
        if volume < Decimal("0"):
            raise UpbitDailyParseError("volume must not be negative")
        if high_price < max(open_price, close_price):
            raise UpbitDailyParseError("high must be >= max(open, close)")
        if low_price > min(open_price, close_price):
            raise UpbitDailyParseError("low must be <= min(open, close)")
