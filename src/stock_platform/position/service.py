from decimal import Decimal
from .calculator import apply_fill
from .models import Position, Side
from .repository import PositionRepository

class PositionService:
    def __init__(self, repository: PositionRepository) -> None:
        self.repository = repository
        self._processed_execution_ids: set[str] = set()

    def apply_execution(self, *, account_id: str, market: str, symbol: str, side: Side,
                        quantity: Decimal, price: Decimal, execution_id: str) -> Position:
        if execution_id in self._processed_execution_ids:
            current = self.repository.get(account_id, market, symbol)
            if current is None:
                raise RuntimeError("processed execution has no position")
            return current
        position = self.repository.get(account_id, market, symbol) or Position(account_id, market, symbol)
        apply_fill(position, side, quantity, price)
        saved = self.repository.save(position)
        self._processed_execution_ids.add(execution_id)
        return saved
