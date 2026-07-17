from stock_platform.indicator.calculator import sma
def test_sma():
    assert sma([1,2,3,4,5],5)==3
