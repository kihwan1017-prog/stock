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
        auto_commit: bool = True,
    ) -> AuditEvent:
        """§ STEP12-19 Carry-forward(3.1) — Transaction 경계 명확화.
        `auto_commit=True`(기본값, 기존 모든 호출부의 동작을 그대로
        유지)면 이전과 동일하게 여기서 즉시 commit한다. 최상위
        Application Service가 자신의 Transaction을 직접 소유하려는
        호출부(예: Deployment/Runtime Registration Commit처럼 Audit
        저장이 다른 Domain INSERT들과 원자적으로 함께 성공/실패해야
        하는 경우)는 `auto_commit=False`로 호출해 flush까지만 수행하고,
        최종 commit/rollback은 호출자가 정확히 한 번 수행한다."""
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
        if auto_commit:
            self._session.commit()
            self._session.refresh(entity)
        else:
            self._session.flush()
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
