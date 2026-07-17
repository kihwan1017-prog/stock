from datetime import date
from decimal import Decimal

from stock_platform.screener.models import CandidateInput
from stock_platform.screener.scoring import (
    CandidateScoringEngine,
)


def _base(**overrides) -> CandidateInput:
    payload = dict(
        exchange_code="KRX",
        symbol="005930",
        trade_date=date(2026, 7, 13),
        close_price=Decimal("100"),
        volume=Decimal("300"),
        trade_value=Decimal("500000000"),
        volume_ma20=Decimal("100"),
        trade_value_ma20=Decimal("2000000000"),
        ma5=Decimal("105"),
        ma20=Decimal("100"),
        ma60=Decimal("95"),
        rsi14=Decimal("55"),
        macd=Decimal("0.20"),
        macd_signal=Decimal("0.10"),
        atr14=Decimal("3"),
        previous_60_high=Decimal("99"),
        high_52w=Decimal("110"),
        low_52w=Decimal("80"),
        is_halted=False,
        is_managed=False,
        is_active=True,
    )
    payload.update(overrides)
    return CandidateInput(**payload)


def test_score_is_between_zero_and_one_hundred() -> None:
    result = CandidateScoringEngine().score(_base())
    assert Decimal("0") <= result.total_score <= Decimal("100")
    assert result.breakdown.total == result.total_score
    assert result.rules.passed is True


def test_missing_indicators_receive_low_score() -> None:
    result = CandidateScoringEngine().score(
        _base(
            volume=Decimal("0"),
            trade_value=Decimal("0"),
            volume_ma20=None,
            trade_value_ma20=None,
            ma5=None,
            ma20=None,
            ma60=None,
            rsi14=None,
            macd=None,
            macd_signal=None,
            atr14=None,
            previous_60_high=None,
            high_52w=None,
            low_52w=None,
        )
    )
    assert result.total_score == Decimal("0.00")
    assert result.rules.passed is False


def test_managed_stock_score_is_zero() -> None:
    result = CandidateScoringEngine().score(
        _base(is_managed=True)
    )
    assert result.total_score == Decimal("0.00")
    assert result.rules.tradable is False
