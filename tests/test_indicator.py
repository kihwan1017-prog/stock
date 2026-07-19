from stock_platform.indicators.simple import sma


def test_sma() -> None:
    assert sma([1, 2, 3, 4, 5], 5) == 3
