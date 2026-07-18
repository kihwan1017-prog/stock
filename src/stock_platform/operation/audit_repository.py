from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.audit_models import AuditEvent


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        event_type: str,
        actor: str,
        request_id: str | None,
        run_id: str | None,
        strategy_id: str | None,
        account_hash: str | None,
        order_id: int | None,
        client_order_id: str | None,
        symbol: str | None,
        detail: dict[str, Any],
        created_at: datetime,
    ) -> AuditEvent:
        entity = AuditEvent(
            event_type=event_type,
            actor=actor,
            request_id=request_id,
            run_id=run_id,
            strategy_id=strategy_id,
            account_hash=account_hash,
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            detail=detail,
            created_at=created_at,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def list_recent(
        self,
        *,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent)
        if event_type:
            stmt = stmt.where(
                AuditEvent.event_type == event_type
            )
        stmt = stmt.order_by(
            AuditEvent.audit_event_id.desc()
        ).limit(max(1, min(limit, 200)))
        return list(self._session.scalars(stmt))
