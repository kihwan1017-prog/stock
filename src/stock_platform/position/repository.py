from typing import Protocol
from .models import Position

class PositionRepository(Protocol):
    def get(self, account_id: str, market: str, symbol: str) -> Position | None: ...
    def save(self, position: Position) -> Position: ...
    def list(self, account_id: str | None = None) -> list[Position]: ...

class InMemoryPositionRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], Position] = {}
    def get(self, account_id: str, market: str, symbol: str) -> Position | None:
        return self._items.get((account_id, market, symbol))
    def save(self, position: Position) -> Position:
        self._items[(position.account_id, position.market, position.symbol)] = position
        return position
    def list(self, account_id: str | None = None) -> list[Position]:
        values = list(self._items.values())
        return values if account_id is None else [p for p in values if p.account_id == account_id]
