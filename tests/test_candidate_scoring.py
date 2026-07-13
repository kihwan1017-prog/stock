from datetime import date
from decimal import Decimal

from stock_platform.screener.models import CandidateInput
from stock_platform.screener.scoring import (
    CandidateScoringEngine,
)


def test_score_is_between_zero_and_one_hundred() -> None:
    item = CandidateInput(
        exchange_code="KRX",
        symbol="005930",
        trade_date=date(2026, 7, 13),
        close_price=Decimal("100"),
        volume=Decimal("300"),
        volume_ma20=Decimal("100"),
        ma5=Decimal("105"),
        ma20=Decimal("100"),
        ma60=Decimal("95"),
        rsi14=Decimal("55"),
        macd=Decimal("0.20"),
        macd_signal=Decimal("0.10"),
        atr14=Decimal("3"),
        previous_60_high=Decimal("99"),
    )

    result = CandidateScoringEngine().score(item)

    assert Decimal("0") <= result.total_score <= Decimal("100")
    assert result.breakdown.total == result.total_score
    assert result.rules.passed is True


def test_missing_indicators_receive_low_score() -> None:
    item = CandidateInput(
        exchange_code="KRX",
        symbol="000000",
        trade_date=date(2026, 7, 13),
        close_price=Decimal("100"),
        volume=Decimal("0"),
        volume_ma20=None,
        ma5=None,
        ma20=None,
        ma60=None,
        rsi14=None,
        macd=None,
        macd_signal=None,
        atr14=None,
        previous_60_high=None,
    )

    result = CandidateScoringEngine().score(item)

    assert result.total_score == Decimal("0.00")
    assert result.rules.passed is False
