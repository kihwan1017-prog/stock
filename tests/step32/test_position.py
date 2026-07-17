from decimal import Decimal
from stock_platform.position.calculator import apply_fill
from stock_platform.position.models import Position, Side
def test_average_cost_and_realized_pnl():
    p=Position("A1","KRX","005930")
    apply_fill(p,Side.BUY,Decimal("10"),Decimal("100")); apply_fill(p,Side.BUY,Decimal("10"),Decimal("120"))
    assert p.average_price==Decimal("110")
    apply_fill(p,Side.SELL,Decimal("5"),Decimal("130"))
    assert p.quantity==Decimal("15") and p.realized_pnl==Decimal("100")
