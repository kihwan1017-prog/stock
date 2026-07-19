import pytest

from stock_platform.indicators.simple import ema, rsi, sma


def test_sma() -> None:
    assert sma([1, 2, 3, 4, 5], 5) == 3


def test_ema_requires_enough_values() -> None:
    assert ema([1, 2], 3) is None


def test_rsi_all_gains_is_100() -> None:
    assert rsi(list(range(1, 17)), 14) == 100.0


def test_invalid_period() -> None:
    with pytest.raises(ValueError):
        sma([1, 2, 3], 0)
