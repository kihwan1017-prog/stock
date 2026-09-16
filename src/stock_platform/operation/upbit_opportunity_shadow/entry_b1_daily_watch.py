"""B1 Entry Forward Validation — KST 1일 1회 연구 summary (Telegram).

새 scheduler 금지 — existing shadow evaluator tick에 fail-open hook.
REAL 정책/주문 변경 없음.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    assign_cohorts,
    daily_research_summary,
    run_b1_forward_validation,
)
from stock_platform.operation.upbit_opportunity_shadow.notify import (
    publish_b1_forward_daily_summary,
)

logger = structlog.get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")
AUDIT_EVENT_PREFIX = "ENTRY_B1_FORWARD_DAILY_"


def _audit_event_for_day(day: str) -> str:
    return f"{AUDIT_EVENT_PREFIX}{day.replace('-', '')}"


def _already_sent_today(session: Session, day: str) -> bool:
    try:
        from stock_platform.operation.audit_repository import AuditEventRepository

        recent = AuditEventRepository(session).list_recent(
            limit=20, event_type=_audit_event_for_day(day)
        )
        return len(recent) > 0
    except Exception:  # noqa: BLE001
        return False


class EntryB1ForwardDailyWatch:
    """evaluator tick 끝에서 호출 — 실패해도 REAL tick 성공 유지."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def observe(self, *, notify: bool = True) -> dict[str, Any]:
        try:
            settings = get_settings()
            if not bool(
                getattr(
                    settings,
                    "upbit_scanner_shadow_b1_daily_report_enabled",
                    True,
                )
            ):
                return {"ok": True, "skipped": True, "code": "DISABLED"}

            day = datetime.now(KST).date().isoformat()
            if _already_sent_today(self._session, day):
                return {
                    "ok": True,
                    "skipped": True,
                    "code": "ALREADY_SENT_TODAY",
                    "day_kst": day,
                }

            completed = list(
                self._session.scalars(
                    select(UpbitOpportunityShadowEntity).where(
                        UpbitOpportunityShadowEntity.status
                        == SHADOW_STATUS_COMPLETED,
                        UpbitOpportunityShadowEntity.deleted_at.is_(None),
                    )
                )
            )
            report = run_b1_forward_validation(completed)
            summary = report.get("daily_summary") or daily_research_summary(
                assign_cohorts(completed)
            )
            summary["FINAL_VERDICT"] = report.get("FINAL_VERDICT")
            summary["PROMOTION_STATUS"] = report.get("PROMOTION_STATUS")
            summary["progress"] = report.get("progress")

            # 하루 1회 stamp (notify 실패해도 audit로 중복 방지 가능)
            try:
                from stock_platform.api.deps_admin import AuditLogService

                AuditLogService(self._session).record(
                    event_type=_audit_event_for_day(day),
                    actor="entry_b1_forward_daily_watch",
                    detail={
                        "day_kst": day,
                        "combined": report.get("combined_sample_count"),
                        "new": report.get("new_sample_count"),
                        "REAL_policy_changed": "NO",
                        "orders_created": 0,
                    },
                    auto_commit=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "b1_forward_daily_audit_failed",
                    error=type(exc).__name__,
                )

            notified = False
            if notify:
                try:
                    publish_b1_forward_daily_summary(summary)
                    notified = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "b1_forward_daily_notify_failed",
                        error=type(exc).__name__,
                    )

            return {
                "ok": True,
                "day_kst": day,
                "notified": notified,
                "summary": summary,
                "orders_created": 0,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "b1_forward_daily_watch_failed_open",
                error=type(exc).__name__,
            )
            try:
                self._session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": False,
                "research_failed_open": True,
                "error": type(exc).__name__,
                "orders_created": 0,
            }
