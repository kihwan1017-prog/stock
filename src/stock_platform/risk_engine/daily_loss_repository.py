from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.daily_loss_entities import (
    AccountDailyLossEntity,
)
from stock_platform.risk_engine.daily_loss_models import DailyLossSnapshot
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
)


class AccountDailyLossRepository:
    """STEP 8-5-19 — LIVE/Paper Daily Loss Upsert."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_from_snapshot(
        self,
        snapshot: DailyLossSnapshot,
        *,
        market_code: str = "KRX",
    ) -> AccountDailyLossEntity:
        uba = snapshot.user_broker_account_id
        paper = snapshot.paper_account_id
        if uba is not None and paper is not None:
            raise AccountIdentityError(
                AccountIdentityErrorCode.ACCOUNT_RESOURCE_MISMATCH,
                "daily loss cannot have both UBA and paper",
            )
        if uba is None and paper is None:
            raise AccountIdentityError(
                AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
                "daily loss requires UBA or paper_account_id",
            )

        trading_date = date.fromisoformat(snapshot.trading_date)
        currency = snapshot.currency.upper()
        market = market_code.upper()

        if uba is not None:
            entity = self._session.scalar(
                select(AccountDailyLossEntity).where(
                    AccountDailyLossEntity.user_broker_account_id == int(uba),
                    AccountDailyLossEntity.trading_date == trading_date,
                    AccountDailyLossEntity.currency_code == currency,
                    AccountDailyLossEntity.market_code == market,
                )
            )
            scope = "LIVE"
        else:
            entity = self._session.scalar(
                select(AccountDailyLossEntity).where(
                    AccountDailyLossEntity.paper_account_id == int(paper),
                    AccountDailyLossEntity.trading_date == trading_date,
                    AccountDailyLossEntity.currency_code == currency,
                    AccountDailyLossEntity.market_code == market,
                )
            )
            scope = "PAPER"

        if entity is None:
            entity = AccountDailyLossEntity(
                account_scope_type=scope,
                user_broker_account_id=int(uba) if uba is not None else None,
                paper_account_id=int(paper) if paper is not None else None,
                trading_date=trading_date,
                currency_code=currency,
                market_code=market,
            )
            self._session.add(entity)

        entity.realized_profit_loss = snapshot.realized_profit_loss
        entity.unrealized_profit_loss = snapshot.unrealized_profit_loss
        entity.combined_profit_loss = snapshot.combined_profit_loss
        entity.current_loss_amount = snapshot.current_loss_amount
        entity.loss_limit_amount = snapshot.loss_limit_amount
        entity.status_code = snapshot.status.value
        entity.checked_at = snapshot.checked_at
        self._session.flush()
        return entity
