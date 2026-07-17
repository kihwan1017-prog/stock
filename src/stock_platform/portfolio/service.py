from dataclasses import dataclass
from decimal import Decimal
from stock_platform.position.repository import PositionRepository

@dataclass(slots=True)
class PortfolioSummary:
    account_id: str
    position_count: int
    total_market_value: Decimal
    total_realized_pnl: Decimal
    total_unrealized_pnl: Decimal

class PortfolioService:
    def __init__(self, repository: PositionRepository) -> None:
        self.repository = repository
    def summarize(self, account_id: str) -> PortfolioSummary:
        positions = self.repository.list(account_id)
        opened = [p for p in positions if p.quantity != 0]
        return PortfolioSummary(account_id, len(opened),
            sum((p.market_value for p in opened), Decimal("0")),
            sum((p.realized_pnl for p in positions), Decimal("0")),
            sum((p.unrealized_pnl for p in opened), Decimal("0")))
