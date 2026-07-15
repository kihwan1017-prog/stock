from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.position_limit_entities import (
    PositionLimitEntity,
)


class PositionLimitRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(
        self,
        *,
        broker_code: str,
        account_number: str,
        exchange_code: str,
        symbol: str,
    ) -> PositionLimitEntity | None:
        return self._session.scalar(
            select(PositionLimitEntity).where(
                PositionLimitEntity.broker_code
                == broker_code.upper(),
                PositionLimitEntity.account_number
                == account_number,
                PositionLimitEntity.exchange_code
                == exchange_code.upper(),
                PositionLimitEntity.symbol
                == symbol.upper(),
                PositionLimitEntity.enabled.is_(True),
            )
        )

    def upsert(
        self,
        *,
        broker_code: str,
        account_number: str,
        exchange_code: str,
        symbol: str,
        max_quantity,
        max_position_amount,
        max_position_weight,
        enabled: bool,
    ) -> PositionLimitEntity:
        entity = self.get(
            broker_code=broker_code,
            account_number=account_number,
            exchange_code=exchange_code,
            symbol=symbol,
        )

        if entity is None:
            entity = PositionLimitEntity(
                broker_code=broker_code.upper(),
                account_number=account_number,
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

        self._session.commit()
        self._session.refresh(entity)
        return entity
