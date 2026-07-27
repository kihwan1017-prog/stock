from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.risk_event_entities import RiskEventEntity
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
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
        current_loss_amount: Decimal,
        loss_limit_amount: Decimal,
        message: str,
        detail_payload: dict,
        user_id: int | None = None,
        user_broker_account_id: int | None = None,
        paper_account_id: int | None = None,
        masked_account_ref: str | None = None,
        correlation_id: str | None = None,
        account_scope_type: str | None = None,
    ) -> RiskEventEntity:
        if user_broker_account_id is not None and paper_account_id is not None:
            raise AccountIdentityError(
                AccountIdentityErrorCode.ACCOUNT_RESOURCE_MISMATCH,
                "risk_event cannot have both UBA and paper_account_id",
            )

        if user_broker_account_id is not None:
            scope = "LIVE"
        elif paper_account_id is not None:
            scope = "PAPER"
        else:
            scope = (account_scope_type or "SYSTEM").upper()
            if scope not in {"SYSTEM", "LEGACY_ORPHAN"}:
                raise AccountIdentityError(
                    AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
                    "risk_event requires UBA or paper_account_id",
                )

        entity = RiskEventEntity(
            event_type=event_type,
            event_level=event_level,
            broker_code=broker_code.upper(),
            user_id=user_id,
            user_broker_account_id=(
                int(user_broker_account_id)
                if user_broker_account_id is not None
                else None
            ),
            paper_account_id=(
                int(paper_account_id) if paper_account_id is not None else None
            ),
            account_scope_type=scope,
            masked_account_ref=masked_account_ref,
            correlation_id=correlation_id,
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
        include_orphan: bool = False,
    ) -> list[RiskEventEntity]:
        stmt = select(RiskEventEntity)
        if not include_orphan:
            stmt = stmt.where(
                RiskEventEntity.account_scope_type != "LEGACY_ORPHAN"
            )
        return list(
            self._session.scalars(
                stmt.order_by(
                    RiskEventEntity.created_at.desc(),
                    RiskEventEntity.risk_event_id.desc(),
                ).limit(limit)
            )
        )
