from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.risk_event_entities import (
    RiskEventEntity,
)


class RiskEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        event_type: str,
        event_level: str,
        broker_code: str,
        account_number: str,
        current_loss_amount: Decimal,
        loss_limit_amount: Decimal,
        message: str,
        detail_payload: dict,
    ) -> RiskEventEntity:
        entity = RiskEventEntity(
            event_type=event_type,
            event_level=event_level,
            broker_code=broker_code,
            account_number=account_number,
            current_loss_amount=current_loss_amount,
            loss_limit_amount=loss_limit_amount,
            message=message,
            detail_payload=detail_payload,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def recent(
        self,
        *,
        limit: int = 50,
    ) -> list[RiskEventEntity]:
        return list(
            self._session.scalars(
                select(RiskEventEntity)
                .order_by(
                    RiskEventEntity.created_at.desc(),
                    RiskEventEntity.risk_event_id.desc(),
                )
                .limit(limit)
            )
        )
