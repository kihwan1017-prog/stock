from datetime import date
from decimal import Decimal

from stock_platform.screener.models import CandidateInput
from stock_platform.screener.rules import CandidateRuleEngine


def _base(**overrides) -> CandidateInput:
    payload = dict(
        exchange_code="KRX",
        symbol="005930",
        trade_date=date(2026, 7, 13),
        close_price=Decimal("100"),
        volume=Decimal("300"),
        trade_value=Decimal("300000000"),
        volume_ma20=Decimal("100"),
        trade_value_ma20=Decimal("1000000000"),
        ma5=Decimal("100"),
        ma20=Decimal("95"),
        ma60=Decimal("90"),
        rsi14=Decimal("55"),
        macd=Decimal("2"),
        macd_signal=Decimal("1"),
        atr14=Decimal("3"),
        previous_60_high=Decimal("99"),
        high_52w=Decimal("120"),
        low_52w=Decimal("80"),
        is_halted=False,
        is_managed=False,
        is_active=True,
    )
    payload.update(overrides)
    return CandidateInput(**payload)


def test_all_core_rules_pass() -> None:
    result = CandidateRuleEngine().evaluate(_base())
    assert result.passed is True
    assert result.passed_count == 8
    assert result.rejection_reasons == ()


def test_halted_stock_is_rejected() -> None:
    result = CandidateRuleEngine().evaluate(
        _base(is_halted=True)
    )
    assert result.tradable is False
    assert result.passed is False
    assert "trading_halted" in result.rejection_reasons


def test_low_week52_position_rejected() -> None:
    result = CandidateRuleEngine().evaluate(
        _base(
            close_price=Decimal("85"),
            high_52w=Decimal("120"),
            low_52w=Decimal("80"),
        )
    )
    assert result.week52_position is False
    assert "week52_position_too_low" in result.rejection_reasons
