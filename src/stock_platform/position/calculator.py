from decimal import Decimal
from .models import Position, Side

class PositionCalculationError(ValueError):
    pass

def apply_fill(position: Position, side: Side, quantity: Decimal, price: Decimal) -> Position:
    if quantity <= 0 or price <= 0:
        raise PositionCalculationError("quantity and price must be positive")
    if side == Side.BUY:
        total_cost = position.quantity * position.average_price + quantity * price
        position.quantity += quantity
        position.average_price = total_cost / position.quantity
        return position
    if quantity > position.quantity:
        raise PositionCalculationError("sell quantity exceeds current position")
    position.realized_pnl += (price - position.average_price) * quantity
    position.quantity -= quantity
    if position.quantity == 0:
        position.average_price = Decimal("0")
    return position
