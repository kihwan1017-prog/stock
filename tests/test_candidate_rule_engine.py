from datetime import date
from decimal import Decimal

from stock_platform.screener.models import CandidateInput
from stock_platform.screener.rules import CandidateRuleEngine


def test_all_rules_pass() -> None:
    item = CandidateInput(
        exchange_code="KRX",
        symbol="005930",
        trade_date=date(2026, 7, 13),
        close_price=Decimal("100"),
        volume=Decimal("300"),
        volume_ma20=Decimal("100"),
        ma5=Decimal("100"),
        ma20=Decimal("95"),
        ma60=Decimal("90"),
        rsi14=Decimal("55"),
        macd=Decimal("2"),
        macd_signal=Decimal("1"),
        atr14=Decimal("3"),
        previous_60_high=Decimal("99"),
    )

    result = CandidateRuleEngine().evaluate(item)

    assert result.passed is True
    assert result.passed_count == 6
