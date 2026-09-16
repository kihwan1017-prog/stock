"""포트폴리오 스냅샷 Repository — STEP66."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.trading.portfolio_snapshot_models import (
    PortfolioSnapshot,
)


class PortfolioSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_account_date(
        self,
        *,
        account_id: int,
        snapshot_date: date,
        mode_code: str = "PAPER",
    ) -> PortfolioSnapshot | None:
        return self._session.scalar(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.account_id == account_id,
                PortfolioSnapshot.snapshot_date == snapshot_date,
                PortfolioSnapshot.mode_code == mode_code.upper(),
            )
        )

    def list_history(
        self,
        *,
        user_id: int,
        account_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
        mode_code: str = "PAPER",
        limit: int = 500,
    ) -> list[PortfolioSnapshot]:
        stmt = select(PortfolioSnapshot).where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.account_id == account_id,
            PortfolioSnapshot.mode_code == mode_code.upper(),
        )
        if date_from is not None:
            stmt = stmt.where(
                PortfolioSnapshot.snapshot_date >= date_from
            )
        if date_to is not None:
            stmt = stmt.where(
                PortfolioSnapshot.snapshot_date <= date_to
            )
        stmt = stmt.order_by(
            PortfolioSnapshot.snapshot_date.asc()
        ).limit(limit)
        return list(self._session.scalars(stmt))

    def save(self, row: PortfolioSnapshot) -> PortfolioSnapshot:
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def upsert(self, row: PortfolioSnapshot) -> PortfolioSnapshot:
        existing = self.get_by_account_date(
            account_id=int(row.account_id),
            snapshot_date=row.snapshot_date,
            mode_code=row.mode_code,
        )
        if existing is None:
            return self.save(row)

        for field in (
            "user_id",
            "snapshot_time",
            "cash",
            "market_value",
            "total_asset",
            "invested_amount",
            "realized_profit",
            "unrealized_profit",
            "daily_profit",
            "daily_profit_rate",
            "total_return_rate",
            "position_count",
            "valuation_mode",
        ):
            setattr(existing, field, getattr(row, field))
        self._session.commit()
        self._session.refresh(existing)
        return existing
