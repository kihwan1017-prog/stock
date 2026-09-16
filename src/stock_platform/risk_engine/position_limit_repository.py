from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.position_limit_entities import (
    PositionLimitEntity,
)
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
)


class PositionLimitRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_uba(
        self,
        *,
        user_broker_account_id: int,
        exchange_code: str,
        symbol: str,
        broker_code: str = "KIWOOM",
    ) -> PositionLimitEntity | None:
        return self._session.scalar(
            select(PositionLimitEntity).where(
                PositionLimitEntity.user_broker_account_id
                == int(user_broker_account_id),
                PositionLimitEntity.exchange_code == exchange_code.upper(),
                PositionLimitEntity.symbol == symbol.upper(),
                PositionLimitEntity.enabled.is_(True),
                PositionLimitEntity.account_scope_type == "LIVE",
            )
        )

    def get_by_paper(
        self,
        *,
        paper_account_id: int,
        exchange_code: str,
        symbol: str,
    ) -> PositionLimitEntity | None:
        return self._session.scalar(
            select(PositionLimitEntity).where(
                PositionLimitEntity.paper_account_id == int(paper_account_id),
                PositionLimitEntity.exchange_code == exchange_code.upper(),
                PositionLimitEntity.symbol == symbol.upper(),
                PositionLimitEntity.enabled.is_(True),
                PositionLimitEntity.account_scope_type == "PAPER",
            )
        )

    def upsert(
        self,
        *,
        broker_code: str,
        exchange_code: str,
        symbol: str,
        max_quantity,
        max_position_amount,
        max_position_weight,
        enabled: bool,
        user_broker_account_id: int | None = None,
        paper_account_id: int | None = None,
        masked_account_ref: str | None = None,
    ) -> PositionLimitEntity:
        if user_broker_account_id is not None and paper_account_id is not None:
            raise AccountIdentityError(
                AccountIdentityErrorCode.ACCOUNT_RESOURCE_MISMATCH,
                "cannot set both UBA and paper_account_id",
            )
        if user_broker_account_id is None and paper_account_id is None:
            raise AccountIdentityError(
                AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
                "user_broker_account_id or paper_account_id required",
            )

        if user_broker_account_id is not None:
            entity = self.get_by_uba(
                user_broker_account_id=int(user_broker_account_id),
                exchange_code=exchange_code,
                symbol=symbol,
                broker_code=broker_code,
            )
            scope = "LIVE"
        else:
            entity = self.get_by_paper(
                paper_account_id=int(paper_account_id),
                exchange_code=exchange_code,
                symbol=symbol,
            )
            scope = "PAPER"

        if entity is None:
            entity = PositionLimitEntity(
                broker_code=broker_code.upper(),
                user_broker_account_id=(
                    int(user_broker_account_id)
                    if user_broker_account_id is not None
                    else None
                ),
                paper_account_id=(
                    int(paper_account_id)
                    if paper_account_id is not None
                    else None
                ),
                account_scope_type=scope,
                masked_account_ref=masked_account_ref,
                exchange_code=exchange_code.upper(),
                symbol=symbol.upper(),
                max_quantity=max_quantity,
                max_position_amount=max_position_amount,
                max_position_weight=max_position_weight,
                enabled=enabled,
            )
            self._session.add(entity)
        else:
            entity.max_quantity = max_quantity
            entity.max_position_amount = max_position_amount
            entity.max_position_weight = max_position_weight
            entity.enabled = enabled
            if masked_account_ref:
                entity.masked_account_ref = masked_account_ref

        self._session.commit()
        self._session.refresh(entity)
        return entity
