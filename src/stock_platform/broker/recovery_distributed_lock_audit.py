"""STEP 8-5-6 — Distributed Lock Audit (민감정보 제외)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def audit_recovery_lock_event(
    event_type: str,
    *,
    detail: dict[str, Any],
    actor: str = "system",
) -> None:
    """
    Lock 상태 전환 감사.

    Heartbeat 성공은 기록하지 않는다.
    Secret·계좌번호 원문·전체 Owner UUID는 detail에 넣지 말 것.
    """

    safe = {
        k: v
        for k, v in detail.items()
        if k
        not in {
            "secret",
            "app_key",
            "access_key",
            "account_number",
            "owner_instance_id",
            "lease_id",
        }
    }
    try:
        from stock_platform.database.session import get_session_factory
        from stock_platform.api.deps_admin import AuditLogService

        session = get_session_factory()()
        try:
            AuditLogService(session).record(
                event_type=event_type,
                actor=actor,
                detail=safe,
            )
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.info(
                "recovery_lock_audit event=%s detail=%s",
                event_type,
                safe,
            )
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        logger.info(
            "recovery_lock_audit event=%s detail=%s",
            event_type,
            safe,
        )
