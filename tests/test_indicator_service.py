from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.indicators.service import IndicatorService


class FakePriceService:
    def get_between(
        self,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ):
        return [
            SimpleNamespace(
                trade_date=date(2026, 7, day),
                open_price=Decimal(100 + day),
                high_price=Decimal(102 + day),
                low_price=Decimal(98 + day),
                close_price=Decimal(101 + day),
                volume=Decimal(1000 + day),
            )
            for day in range(1, 11)
        ]


def test_service_filters_requested_dates() -> None:
    service = IndicatorService(
        FakePriceService()  # type: ignore[arg-type]
    )

    result = service.calculate_daily(
        exchange_code="KRX",
        symbol="005930",
        start_date=date(2026, 7, 5),
        end_date=date(2026, 7, 8),
    )

    assert [item.trade_date for item in result] == [
        date(2026, 7, 5),
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
    ]
