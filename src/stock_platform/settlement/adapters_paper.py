"""STEP 8-5-16 — Paper Settlement Adapter (내부 Ledger = 진실)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.settlement.broker_adapter import (
    SettlementBrokerBundle,
    SettlementCashSnapshot,
    SettlementPositionSnapshot,
)
from stock_platform.trading.account_models import PaperAccount, PaperPosition


class PaperSettlementAdapter:
    """외부 API 없음 — PaperAccount/PaperPosition을 외부 스냅샷으로 사용."""

    broker_code = "PAPER"

    def __init__(
        self,
        session: Session,
        *,
        paper_account_id: int,
        market_type: str = "STOCK",
    ) -> None:
        self._session = session
        self._paper_account_id = int(paper_account_id)
        self._market_type = market_type.upper()

    def fetch_bundle(self) -> SettlementBrokerBundle:
        now = datetime.now(timezone.utc)
        account = self._session.get(PaperAccount, self._paper_account_id)
        if account is None:
            return SettlementBrokerBundle(
                broker_code=self.broker_code,
                fetched_at=now,
                cash=SettlementCashSnapshot(),
                sync_ok=False,
                sync_error="PAPER_ACCOUNT_NOT_FOUND",
            )

        cash_avail = Decimal(str(account.available_cash or 0))
        positions_rows = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == self._paper_account_id
                )
            )
        )
        positions: list[SettlementPositionSnapshot] = []
        eval_total = Decimal("0")
        unreal = Decimal("0")
        for row in positions_rows:
            qty = Decimal(str(row.quantity or 0))
            avg = Decimal(str(row.average_entry_price or 0))
            # Paper는 평가가를 평균가로 근사 (실시간 시세 없음)
            eval_amt = qty * avg
            eval_total += eval_amt
            positions.append(
                SettlementPositionSnapshot(
                    exchange_code=str(row.exchange_code or "KRX"),
                    symbol=str(row.symbol),
                    quantity=qty,
                    available_quantity=qty,
                    locked_quantity=Decimal("0"),
                    average_price=avg,
                    evaluation_price=avg,
                    evaluation_amount=eval_amt,
                    unrealized_pnl=Decimal("0"),
                )
            )

        equity = cash_avail + eval_total
        return SettlementBrokerBundle(
            broker_code=self.broker_code,
            fetched_at=now,
            cash=SettlementCashSnapshot(
                available=cash_avail,
                locked=Decimal("0"),
                total=cash_avail,
            ),
            positions=positions,
            equity=equity,
            meta={
                "paper_account_id": self._paper_account_id,
                "market_type": self._market_type,
                "realized_profit_loss": str(
                    account.realized_profit_loss or 0
                ),
            },
            sync_ok=True,
        )
