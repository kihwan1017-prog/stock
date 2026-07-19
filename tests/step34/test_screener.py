from dataclasses import dataclass
from decimal import Decimal

from stock_platform.screener.service import ScreenerService


@dataclass
class _LegacyIndicator:
    sma5: Decimal
    sma20: Decimal
    rsi14: Decimal


def test_filter_candidates() -> None:
    service = ScreenerService()
    selected = _LegacyIndicator(
        sma5=Decimal("71000"),
        sma20=Decimal("70000"),
        rsi14=Decimal("55"),
    )
    excluded = _LegacyIndicator(
        sma5=Decimal("120000"),
        sma20=Decimal("125000"),
        rsi14=Decimal("35"),
    )
    assert service.filter_candidates([selected, excluded]) == [
        selected
    ]
