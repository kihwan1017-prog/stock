from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.markets.models import (
    ALLOWED_MINUTE_TIMEFRAMES,
    CandleMinute,
    Instrument,
    OrderbookSnapshot,
    PriceDaily,
    QuoteSnapshot,
    TradeTick,
)
from stock_platform.markets.repository import (
    CandleMinuteRepository,
    InstrumentRepository,
    OrderbookSnapshotRepository,
    PriceDailyRepository,
    QuoteSnapshotRepository,
    TradeTickRepository,
)


class InstrumentNotFoundError(LookupError):
    """요청한 종목이 없을 때."""


class InstrumentService:
    """종목 마스터 Upsert·조회."""

    def __init__(self, repository: InstrumentRepository) -> None:
        self._repository = repository

    def list(
        self,
        *,
        exchange_code: str | None = None,
        active_only: bool = True,
        limit: int = 5000,
    ) -> list[Instrument]:
        return self._repository.list(
            exchange_code=exchange_code,
            active_only=active_only,
            limit=limit,
        )

    def get(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument | None:
        return self._repository.find(
            exchange_code=exchange_code.strip().upper(),
            symbol=symbol.strip().upper(),
        )

    def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        now = datetime.now(timezone.utc)
        normalized: list[dict[str, Any]] = []

        for row in rows:
            exchange_code = str(row["exchange_code"]).strip().upper()
            symbol = str(row["symbol"]).strip().upper()

            if not exchange_code or not symbol:
                raise ValueError(
                    "exchange_code and symbol are required"
                )

            normalized.append(
                {
                    "asset_type": str(row["asset_type"]).strip().upper(),
                    "exchange_code": exchange_code,
                    "symbol": symbol,
                    "name": str(row["name"]).strip(),
                    "currency_code": str(
                        row.get("currency_code", "KRW")
                    ).strip().upper(),
                    "listed_date": row.get("listed_date"),
                    "delisted_date": row.get("delisted_date"),
                    "is_active": bool(row.get("is_active", True)),
                    "extra_data": row.get("extra_data") or {},
                    "updated_at": now,
                }
            )

        return self._repository.upsert_many(normalized)

    def ensure(
        self,
        *,
        exchange_code: str,
        symbol: str,
        name: str | None = None,
        asset_type: str = "CRYPTO",
        currency_code: str = "KRW",
    ) -> Instrument:
        """없으면 생성하고, 있으면 반환한다."""

        existing = self.get(exchange_code, symbol)
        if existing is not None:
            return existing

        self.upsert_many(
            [
                {
                    "asset_type": asset_type,
                    "exchange_code": exchange_code,
                    "symbol": symbol,
                    "name": name or symbol,
                    "currency_code": currency_code,
                    "is_active": True,
                    "extra_data": {},
                }
            ]
        )

        created = self.get(exchange_code, symbol)
        if created is None:
            raise RuntimeError(
                f"Failed to ensure instrument: "
                f"{exchange_code}/{symbol}"
            )
        return created


class PriceDailyService:
    """일봉 조회·저장. 종목이 없으면 ensure 후 저장한다."""

    def __init__(
        self,
        repository: PriceDailyRepository,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._repository = repository
        self._instrument_service = instrument_service

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

    def list_recent(
        self,
        exchange_code: str,
        symbol: str,
        *,
        limit: int = 200,
    ) -> list[PriceDaily]:
        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )

        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )

        return self._repository.list_recent(
            instrument.instrument_id,
            limit=limit,
        )

    def save_many(
        self,
        exchange_code: str,
        symbol: str,
        source: str,
        rows: list[dict],
        *,
        ensure_instrument: bool = True,
        instrument_name: str | None = None,
        asset_type: str = "CRYPTO",
    ) -> int:
        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )

        if instrument is None:
            if not ensure_instrument or self._instrument_service is None:
                raise InstrumentNotFoundError(
                    f"Instrument not found: {exchange_code}/{symbol}"
                )

            instrument = self._instrument_service.ensure(
                exchange_code=exchange_code,
                symbol=symbol,
                name=instrument_name,
                asset_type=asset_type,
            )

        now = datetime.now(timezone.utc)
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
                    "updated_at": now,
                }
            )

        return self._repository.upsert_many(normalized_rows)


class CandleMinuteService:
    """분봉 조회·저장."""

    def __init__(
        self,
        repository: CandleMinuteRepository,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._repository = repository
        self._instrument_service = instrument_service

    def list_recent(
        self,
        exchange_code: str,
        symbol: str,
        timeframe: int,
        *,
        limit: int = 200,
    ) -> list[CandleMinute]:
        self._validate_timeframe(timeframe)
        instrument = self._require_instrument(exchange_code, symbol)
        return self._repository.list_recent(
            instrument.instrument_id,
            timeframe,
            limit=limit,
        )

    def get_latest(
        self,
        exchange_code: str,
        symbol: str,
        timeframe: int,
    ) -> CandleMinute | None:
        self._validate_timeframe(timeframe)
        instrument = self._require_instrument(exchange_code, symbol)
        return self._repository.find_latest(
            instrument.instrument_id,
            timeframe,
        )

    def save_many(
        self,
        exchange_code: str,
        symbol: str,
        timeframe: int,
        source: str,
        rows: list[dict[str, Any]],
        *,
        ensure_instrument: bool = True,
        instrument_name: str | None = None,
        asset_type: str = "CRYPTO",
    ) -> int:
        self._validate_timeframe(timeframe)

        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )
        if instrument is None:
            if not ensure_instrument or self._instrument_service is None:
                raise InstrumentNotFoundError(
                    f"Instrument not found: {exchange_code}/{symbol}"
                )
            instrument = self._instrument_service.ensure(
                exchange_code=exchange_code,
                symbol=symbol,
                name=instrument_name,
                asset_type=asset_type,
            )

        now = datetime.now(timezone.utc)
        normalized: list[dict[str, Any]] = []

        for row in rows:
            candle_at = row["candle_at"]
            if isinstance(candle_at, datetime) and candle_at.tzinfo is None:
                candle_at = candle_at.replace(tzinfo=timezone.utc)

            open_price = Decimal(str(row["open_price"]))
            high_price = Decimal(str(row["high_price"]))
            low_price = Decimal(str(row["low_price"]))
            close_price = Decimal(str(row["close_price"]))

            # OHLC 논리 오류는 적재 전에 거부
            if high_price < low_price:
                raise ValueError(
                    f"high_price < low_price at {candle_at}"
                )

            normalized.append(
                {
                    "instrument_id": instrument.instrument_id,
                    "timeframe": timeframe,
                    "candle_at": candle_at,
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "close_price": close_price,
                    "volume": Decimal(str(row.get("volume", 0))),
                    "trade_value": Decimal(
                        str(row.get("trade_value", 0))
                    ),
                    "source": source,
                    "updated_at": now,
                }
            )

        return self._repository.upsert_many(normalized)

    def _require_instrument(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument:
        instrument = self._repository.find_instrument(
            exchange_code=exchange_code,
            symbol=symbol,
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )
        return instrument

    @staticmethod
    def _validate_timeframe(timeframe: int) -> None:
        if timeframe not in ALLOWED_MINUTE_TIMEFRAMES:
            raise ValueError(
                "timeframe must be one of "
                f"{ALLOWED_MINUTE_TIMEFRAMES}"
            )


class QuoteSnapshotService:
    """최신 호가 스냅샷 조회·저장."""

    def __init__(
        self,
        repository: QuoteSnapshotRepository,
        instrument_service: InstrumentService,
    ) -> None:
        self._repository = repository
        self._instrument_service = instrument_service

    def get(
        self,
        exchange_code: str,
        symbol: str,
    ) -> QuoteSnapshot | None:
        instrument = self._instrument_service.get(
            exchange_code,
            symbol,
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )
        return self._repository.get(instrument.instrument_id)

    def upsert_from_quote(
        self,
        *,
        exchange_code: str,
        symbol: str,
        trade_price: Decimal,
        quoted_at: datetime,
        source: str,
        bid_price: Decimal | None = None,
        ask_price: Decimal | None = None,
        change_price: Decimal | None = None,
        change_rate: Decimal | None = None,
        volume: Decimal | None = None,
        asset_type: str = "CRYPTO",
    ) -> int:
        instrument = self._instrument_service.ensure(
            exchange_code=exchange_code,
            symbol=symbol,
            name=symbol,
            asset_type=asset_type,
        )
        if quoted_at.tzinfo is None:
            quoted_at = quoted_at.replace(tzinfo=timezone.utc)

        return self._repository.upsert(
            {
                "instrument_id": instrument.instrument_id,
                "trade_price": trade_price,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "change_price": change_price,
                "change_rate": change_rate,
                "volume": volume,
                "quoted_at": quoted_at,
                "source": source,
                "updated_at": datetime.now(timezone.utc),
            }
        )


class TradeTickService:
    """체결 틱 조회·저장."""

    def __init__(
        self,
        repository: TradeTickRepository,
        instrument_service: InstrumentService,
    ) -> None:
        self._repository = repository
        self._instrument_service = instrument_service

    def list_recent(
        self,
        exchange_code: str,
        symbol: str,
        *,
        limit: int = 100,
    ) -> list[TradeTick]:
        instrument = self._instrument_service.get(
            exchange_code,
            symbol,
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )
        return self._repository.list_recent(
            instrument.instrument_id,
            limit=limit,
        )

    def save_many(
        self,
        *,
        exchange_code: str,
        symbol: str,
        source: str,
        rows: list[dict[str, Any]],
        asset_type: str = "CRYPTO",
    ) -> int:
        instrument = self._instrument_service.ensure(
            exchange_code=exchange_code,
            symbol=symbol,
            name=symbol,
            asset_type=asset_type,
        )

        normalized: list[dict[str, Any]] = []
        for row in rows:
            traded_at = row["traded_at"]
            if isinstance(traded_at, datetime) and traded_at.tzinfo is None:
                traded_at = traded_at.replace(tzinfo=timezone.utc)

            trade_id = str(row["trade_id"]).strip()
            if not trade_id:
                raise ValueError("trade_id is required")

            normalized.append(
                {
                    "instrument_id": instrument.instrument_id,
                    "trade_id": trade_id,
                    "price": Decimal(str(row["price"])),
                    "quantity": Decimal(str(row["quantity"])),
                    "side": row.get("side"),
                    "traded_at": traded_at,
                    "source": source,
                }
            )

        return self._repository.upsert_many(normalized)


class OrderbookSnapshotService:
    """호가창 스냅샷 조회·저장."""

    def __init__(
        self,
        repository: OrderbookSnapshotRepository,
        instrument_service: InstrumentService,
    ) -> None:
        self._repository = repository
        self._instrument_service = instrument_service

    def get_latest(
        self,
        exchange_code: str,
        symbol: str,
    ) -> OrderbookSnapshot | None:
        instrument = self._instrument_service.get(
            exchange_code,
            symbol,
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )
        return self._repository.find_latest(instrument.instrument_id)

    def save(
        self,
        *,
        exchange_code: str,
        symbol: str,
        captured_at: datetime,
        bids: list[dict[str, Any]],
        asks: list[dict[str, Any]],
        source: str,
        asset_type: str = "CRYPTO",
    ) -> int:
        instrument = self._instrument_service.ensure(
            exchange_code=exchange_code,
            symbol=symbol,
            name=symbol,
            asset_type=asset_type,
        )
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)

        return self._repository.upsert(
            {
                "instrument_id": instrument.instrument_id,
                "captured_at": captured_at,
                "bids": bids,
                "asks": asks,
                "source": source,
            }
        )

