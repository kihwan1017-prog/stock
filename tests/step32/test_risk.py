from decimal import Decimal
from stock_platform.risk.models import RiskLimits,RiskRequest
from stock_platform.risk.service import RiskService
def test_large_order_rejected():
    s=RiskService(RiskLimits(Decimal("100"),Decimal("500"),Decimal("50"),3))
    r=s.evaluate(RiskRequest(Decimal("101"),Decimal("0"),Decimal("0"),0,True))
    assert not r.allowed and "MAX_ORDER_AMOUNT_EXCEEDED" in r.reasons
