from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends
from sqlalchemy.orm import Session

# JWT + API Key 통합 보호 (기존 import 경로 유지)
from stock_platform.auth.deps import require_admin  # noqa: F401
from stock_platform.database.session import get_db_session
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.operation.audit_repository import (
    AuditEventRepository,
)


def hash_account(account_number: str | None) -> str | None:
    if not account_number:
        return None
    digest = hashlib.sha256(
        account_number.strip().encode("utf-8")
    ).hexdigest()
    return digest[:12]


class AuditLogService:
    """민감 운영 행위 감사 로그."""

    def __init__(self, session: Session) -> None:
        self._repository = AuditEventRepository(session)

    def record(
        self,
        *,
        event_type: str,
        actor: str,
        request_id: str | None = None,
        run_id: str | None = None,
        strategy_id: str | None = None,
        account_hash: str | None = None,
        order_id: int | None = None,
        client_order_id: str | None = None,
        symbol: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        safe_detail = dict(detail or {})
        for key in list(safe_detail):
            lowered = key.lower()
            if any(
                secret in lowered
                for secret in (
                    "token",
                    "secret",
                    "password",
                    "api_key",
                    "authorization",
                )
            ):
                safe_detail[key] = "***"
        return self._repository.create(
            event_type=event_type,
            actor=actor,
            request_id=request_id,
            run_id=run_id,
            strategy_id=strategy_id,
            account_hash=account_hash,
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            detail=safe_detail,
            created_at=datetime.now(timezone.utc),
        )


def get_audit_service(
    session: Session = Depends(get_db_session),
) -> AuditLogService:
    return AuditLogService(session)
