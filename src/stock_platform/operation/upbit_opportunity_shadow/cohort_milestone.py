"""Shadow cohort milestone watch — SAMPLE_ACCUMULATING → READY (1회 알림).

정책/threshold/Scanner 변경 없음. READ 관찰 + Audit/Telegram only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
from stock_platform.operation.upbit_opportunity_shadow.notify import (
    publish_shadow_cohort_milestone,
)

logger = structlog.get_logger(__name__)

# b8b954f LAST_KNOWN_PRICE_AT_TARGET 정책 마커
NEW_FINALIZATION_POLICY = "last_known_price_at_target_v1"
ALLOWED_SELECTION = frozenset(
    {"EXACT_TARGET_CANDLE", "LAST_KNOWN_BEFORE_TARGET"}
)

STATUS_ACCUMULATING = "SAMPLE_ACCUMULATING"
STATUS_READY = "SHADOW_COHORT_30_REVIEW_READY"
AUDIT_EVENT = "SHADOW_COHORT_30_REVIEW_READY"

VALID_COHORT_THRESHOLD = 30
NEW_POLICY_MATCH_THRESHOLD = 10


def _is_valid_cohort_row(row: UpbitOpportunityShadowEntity) -> bool:
    """성과 분석 가능 COMPLETED — 이전 REVIEW STEP의 VALID 정의와 동일."""

    if row.status != SHADOW_STATUS_COMPLETED:
        return False
    for m in (5, 15, 30, 60):
        if getattr(row, f"return_{m}m_pct", None) is None:
            return False
    if row.mfe_pct is None or row.mae_pct is None:
        return False
    if row.tp_hit is None or row.sl_hit is None:
        return False
    watch = (row.evaluation_detail or {}).get("mismatch_watch") or {}
    if watch.get("code") == "SHADOW_EVALUATION_MISMATCH":
        return False
    return True


def _is_new_policy_finalization(row: UpbitOpportunityShadowEntity) -> bool:
    """b8b954f 이후 finalization 정책으로 stamp 된 COMPLETED."""

    detail = row.evaluation_detail or {}
    if detail.get("window_finalization") == NEW_FINALIZATION_POLICY:
        return True
    windows = detail.get("windows") or {}
    # 전 window selection_type 이 신규 정책이면 인정
    ok_n = 0
    for key in ("5", "15", "30", "60"):
        w = windows.get(key) or {}
        if w.get("selection_type") in ALLOWED_SELECTION and w.get("final") is True:
            ok_n += 1
    return ok_n >= 4


def _is_match_watch(row: UpbitOpportunityShadowEntity) -> bool:
    watch = (row.evaluation_detail or {}).get("mismatch_watch") or {}
    return watch.get("code") == "MATCH" and watch.get("ok") is True


def compute_cohort_milestone_snapshot(
    session: Session,
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None)
            )
        )
    )
    completed = [r for r in rows if r.status == SHADOW_STATUS_COMPLETED]
    valid = [r for r in completed if _is_valid_cohort_row(r)]
    mismatch_count = 0
    for r in completed:
        watch = (r.evaluation_detail or {}).get("mismatch_watch") or {}
        if watch.get("code") == "SHADOW_EVALUATION_MISMATCH":
            mismatch_count += 1

    new_policy_match = [
        r
        for r in completed
        if _is_new_policy_finalization(r) and _is_match_watch(r)
    ]

    cond_valid = len(valid) >= VALID_COHORT_THRESHOLD
    cond_new_policy = len(new_policy_match) >= NEW_POLICY_MATCH_THRESHOLD
    cond_mismatch = mismatch_count == 0
    ready = cond_valid and cond_new_policy and cond_mismatch

    return {
        "status": STATUS_READY if ready else STATUS_ACCUMULATING,
        "ready": ready,
        "valid_cohort_n": len(valid),
        "valid_cohort_threshold": VALID_COHORT_THRESHOLD,
        "valid_cohort_met": cond_valid,
        "new_policy_match_n": len(new_policy_match),
        "new_policy_match_threshold": NEW_POLICY_MATCH_THRESHOLD,
        "new_policy_match_met": cond_new_policy,
        "new_policy_match_ids": [int(r.shadow_id) for r in new_policy_match],
        "mismatch_count": mismatch_count,
        "mismatch_clear_met": cond_mismatch,
        "completed_n": len(completed),
        "active_n": sum(1 for r in rows if r.status == "ACTIVE"),
        "policy_marker": NEW_FINALIZATION_POLICY,
        "policy_commit": "b8b954f",
        "orders_created": 0,
        "auto_reconcile": False,
    }


def _already_notified(session: Session) -> bool:
    try:
        from stock_platform.operation.audit_repository import (
            AuditEventRepository,
        )

        recent = AuditEventRepository(session).list_recent(
            limit=5, event_type=AUDIT_EVENT
        )
        return len(recent) > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "shadow_cohort_milestone_audit_lookup_failed",
            error=type(exc).__name__,
        )
        return False


class ShadowCohortMilestoneWatch:
    """조건 충족 시에만 Audit+Telegram 1회. 그 외 SAMPLE_ACCUMULATING."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def observe(self, *, notify: bool = True) -> dict[str, Any]:
        settings = get_settings()
        if not bool(
            getattr(
                settings,
                "upbit_scanner_shadow_cohort_milestone_watch_enabled",
                True,
            )
        ):
            return {
                "ok": True,
                "skipped": True,
                "code": "WATCH_DISABLED",
                "status": STATUS_ACCUMULATING,
                "orders_created": 0,
            }

        snap = compute_cohort_milestone_snapshot(self._session)
        out: dict[str, Any] = {
            "ok": True,
            "status": snap["status"],
            "snapshot": snap,
            "notified": False,
            "already_notified": False,
            "orders_created": 0,
            "mutated_evaluation_fields": False,
        }

        if not snap["ready"]:
            return out

        if _already_notified(self._session):
            out["already_notified"] = True
            out["code"] = "ALREADY_NOTIFIED"
            return out

        # 1회 Audit
        try:
            from stock_platform.api.deps_admin import AuditLogService

            AuditLogService(self._session).record(
                event_type=AUDIT_EVENT,
                actor="shadow_cohort_milestone_watch",
                detail={
                    "code": STATUS_READY,
                    "snapshot": snap,
                    "auto_reconcile": False,
                    "orders_created": 0,
                    "policy_unchanged": True,
                },
                auto_commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_cohort_milestone_audit_failed",
                error=type(exc).__name__,
            )
            out["ok"] = False
            out["code"] = "AUDIT_FAILED"
            out["error"] = type(exc).__name__
            return out

        if notify:
            try:
                publish_shadow_cohort_milestone(snap)
                out["notified"] = True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "shadow_cohort_milestone_notify_failed",
                    error=type(exc).__name__,
                )

        out["code"] = STATUS_READY
        out["at"] = datetime.now(timezone.utc).isoformat()
        return out
