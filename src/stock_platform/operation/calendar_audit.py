"""STEP 8-5-7 — Calendar Audit (조회마다 남기지 않음)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def audit_calendar_event(
    event_type: str,
    *,
    detail: dict[str, Any],
    actor: str = "system",
) -> None:
    try:
        from stock_platform.api.deps_admin import AuditLogService
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            AuditLogService(session).record(
                event_type=event_type,
                actor=actor,
                detail=detail,
            )
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.info(
                "calendar_audit event=%s detail=%s", event_type, detail
            )
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        logger.info(
            "calendar_audit event=%s detail=%s", event_type, detail
        )
