from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import inspect, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_platform.brokers.kiwoom.auth import KiwoomTokenManager
from stock_platform.brokers.kiwoom.client import KiwoomRestClient
from stock_platform.collectors.kiwoom.daily_collector import (
    KiwoomDailyCollector,
)
from stock_platform.collectors.kiwoom.sync_service import (
    KiwoomDailySyncService,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.markets.models import Instrument
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import PriceDailyService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Kiwoom daily collector and synchronization."
    )

    parser.add_argument(
        "--symbol",
        default="005930",
        help="Instrument symbol. Default: 005930",
    )
    parser.add_argument(
        "--exchange",
        default="KRX",
        help="Exchange code. Default: KRX",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=5,
        help="Number of calendar days to request. Default: 5",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist collected data to market.price_daily.",
    )

    return parser.parse_args()


def verify_configuration() -> None:
    settings = get_settings()

    print("[1/5] Configuration")
    print(
        "  environment:",
        "mock" if settings.kiwoom_use_mock else "real",
    )
    print("  base_url:", settings.kiwoom_base_url)
    print(
        "  credentials:",
        "configured"
        if settings.kiwoom_app_key and settings.kiwoom_secret_key
        else "missing",
    )

    settings.validate_kiwoom_credentials()


def verify_database(exchange_code: str, symbol: str) -> Instrument:
    print("[2/5] Database")

    session = get_session_factory()()

    try:
        inspector = inspect(session.bind)

        required_tables = {
            ("market", "instrument"),
            ("market", "price_daily"),
        }

        for schema_name, table_name in required_tables:
            exists = inspector.has_table(
                table_name,
                schema=schema_name,
            )
            print(
                f"  {schema_name}.{table_name}:",
                "OK" if exists else "MISSING",
            )

            if not exists:
                raise RuntimeError(
                    f"Required table is missing: "
                    f"{schema_name}.{table_name}"
                )

        stmt = select(Instrument).where(
            Instrument.exchange_code == exchange_code,
            Instrument.symbol == symbol,
        )
        instrument = session.scalar(stmt)

        if instrument is None:
            raise RuntimeError(
                f"Instrument not found: {exchange_code}/{symbol}. "
                "Insert it into market.instrument first."
            )

        print(
            "  instrument:",
            f"{instrument.exchange_code}/"
            f"{instrument.symbol} {instrument.name}",
        )

        return instrument
    finally:
        session.close()


async def verify_token() -> None:
    print("[3/5] Access token")

    async with KiwoomTokenManager() as manager:
        token = await manager.get_token(force_refresh=True)

    print("  token_type:", token.token_type)
    print("  expires_at:", token.expires_at.isoformat())
    print("  token_value: [hidden]")


async def collect_rows(
    symbol: str,
    start_date: date,
    end_date: date,
):
    print("[4/5] Daily collector")

    async with KiwoomRestClient() as client:
        collector = KiwoomDailyCollector(client)

        rows = await collector.collect(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjusted_price=True,
        )

    print("  requested:", start_date, "~", end_date)
    print("  collected:", len(rows))

    for row in rows[-5:]:
        print(
            " ",
            row.trade_date,
            "O", row.open_price,
            "H", row.high_price,
            "L", row.low_price,
            "C", row.close_price,
            "V", row.volume,
        )

    return rows


async def apply_sync(
    exchange_code: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> None:
    print("[5/5] Database synchronization")

    session = get_session_factory()()

    try:
        price_service = PriceDailyService(
            PriceDailyRepository(session)
        )

        async with KiwoomRestClient() as client:
            collector = KiwoomDailyCollector(client)
            sync_service = KiwoomDailySyncService(
                collector=collector,
                price_service=price_service,
            )

            result = await sync_service.sync(
                exchange_code=exchange_code,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjusted_price=True,
                resume=False,
            )

        print("  collected_count:", result.collected_count)
        print("  saved_count:", result.saved_count)
    finally:
        session.close()


async def main() -> None:
    args = parse_args()

    if args.days <= 0:
        raise ValueError("--days must be greater than zero")

    exchange_code = args.exchange.strip().upper()
    symbol = args.symbol.strip().upper()

    end_date = date.today()
    start_date = end_date - timedelta(days=args.days - 1)

    verify_configuration()
    verify_database(exchange_code, symbol)
    await verify_token()
    await collect_rows(symbol, start_date, end_date)

    if args.apply:
        await apply_sync(
            exchange_code,
            symbol,
            start_date,
            end_date,
        )
    else:
        print("[5/5] Database synchronization: SKIPPED")
        print("  Use --apply to save collected rows.")

    print("\nSTEP18 verification completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
