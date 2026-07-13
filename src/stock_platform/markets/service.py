from datetime import date
from decimal import Decimal

from stock_platform.markets.models import PriceDaily
from stock_platform.markets.repository import PriceDailyRepository


class InstrumentNotFoundError(LookupError):
    """Raised when a requested instrument does not exist."""


class PriceDailyService:
    """Business logic for daily market prices."""

    def __init__(self, repository: PriceDailyRepository) -> None:
        self._repository = repository

    def get_latest(
        self,
        exchange_code: str,
        symbol: str,
    ) -> PriceDaily | None:
        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )

        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )

        return self._repository.find_latest(instrument.instrument_id)

    def get_between(
        self,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceDaily]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )

        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )

        return self._repository.find_between(
            instrument_id=instrument.instrument_id,
            start_date=start_date,
            end_date=end_date,
        )

    def save_many(
        self,
        exchange_code: str,
        symbol: str,
        source: str,
        rows: list[dict],
    ) -> int:
        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )

        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )

        normalized_rows: list[dict] = []

        for row in rows:
            normalized_rows.append(
                {
                    "instrument_id": instrument.instrument_id,
                    "trade_date": row["trade_date"],
                    "open_price": Decimal(str(row["open_price"])),
                    "high_price": Decimal(str(row["high_price"])),
                    "low_price": Decimal(str(row["low_price"])),
                    "close_price": Decimal(str(row["close_price"])),
                    "volume": Decimal(str(row.get("volume", 0))),
                    "trade_value": Decimal(str(row.get("trade_value", 0))),
                    "change_rate": (
                        Decimal(str(row["change_rate"]))
                        if row.get("change_rate") is not None
                        else None
                    ),
                    "source": source,
                }
            )

        return self._repository.upsert_many(normalized_rows)
