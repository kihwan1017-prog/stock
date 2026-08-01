"""Admin 테스트 계정 정리 Preview — 실삭제 자동 실행 금지."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service, require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.auth.models import AuthUser
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount


router = APIRouter(
    prefix="/api/v1/admin/member-cleanup",
    tags=["Admin Member Cleanup"],
    dependencies=[Depends(require_admin)],
)

PROTECTED_USERNAMES = frozenset({"admin", "kikicom"})


class CleanupExecuteBody(BaseModel):
    user_ids: list[int] = Field(default_factory=list)
    mode: str = Field(default="deactivate", description="deactivate | soft_delete")
    confirm_phrase: str = Field(
        description="Must be exactly DELETE_TEST_ACCOUNTS"
    )
    backup_confirmed: bool = False


def _is_protected(username: str | None) -> bool:
    return (username or "").strip().lower() in PROTECTED_USERNAMES


def _count_refs(session: Session, user_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["paper_accounts"] = int(
        session.scalar(
            select(func.count()).select_from(PaperAccount).where(
                PaperAccount.user_id == user_id
            )
        )
        or 0
    )
    counts["user_broker_accounts"] = int(
        session.scalar(
            select(func.count()).select_from(UserBrokerAccount).where(
                UserBrokerAccount.user_id == user_id
            )
        )
        or 0
    )
    # Best-effort optional tables
    optional_sql = {
        "trading_orders_as_user": """
            SELECT count(*) FROM trading.trading_order
            WHERE user_id = :uid
        """,
        "strategy_definitions": """
            SELECT count(*) FROM trading.strategy_definition
            WHERE user_id = :uid
        """,
        "account_strategy_links": """
            SELECT count(*) FROM trading.account_strategy_link
            WHERE user_id = :uid
        """,
        "audit_events": """
            SELECT count(*) FROM operation.audit_event
            WHERE actor = :uname
        """,
    }
    username = session.scalar(
        select(AuthUser.username).where(AuthUser.user_id == user_id)
    )
    for key, sql in optional_sql.items():
        try:
            params = {"uid": user_id, "uname": str(username or "")}
            counts[key] = int(
                session.execute(text(sql), params).scalar() or 0
            )
        except Exception:  # noqa: BLE001
            counts[key] = -1
    return counts


@router.get("/candidates")
def list_cleanup_candidates(
    include_deleted: bool = Query(default=False),
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """admin/kikicom 제외 테스트 계정 후보 + 연결 건수 (삭제 없음)."""

    stmt = select(AuthUser).order_by(AuthUser.user_id.asc())
    if not include_deleted:
        stmt = stmt.where(AuthUser.deleted_at.is_(None))
    rows = list(session.scalars(stmt))
    items: list[dict[str, Any]] = []
    for row in rows:
        username = str(row.username or "")
        protected = _is_protected(username)
        is_self = int(row.user_id) == int(user.user_id)
        refs = _count_refs(session, int(row.user_id))
        total_refs = sum(v for v in refs.values() if v > 0)
        hard_delete_allowed = (
            not protected
            and not is_self
            and total_refs == 0
            and row.deleted_at is not None
        )
        items.append(
            {
                "user_id": int(row.user_id),
                "username": username,
                "email": row.email,
                "display_name": row.display_name,
                "is_active": bool(row.is_active),
                "deleted_at": (
                    row.deleted_at.isoformat() if row.deleted_at else None
                ),
                "roles": row.roles,
                "protected": protected,
                "is_self": is_self,
                "ref_counts": refs,
                "can_deactivate": not protected and not is_self,
                "can_soft_delete": not protected and not is_self,
                "hard_delete_allowed": hard_delete_allowed,
                "recommended_action": (
                    "KEEP"
                    if protected or is_self
                    else ("DEACTIVATE" if total_refs > 0 else "SOFT_DELETE")
                ),
            }
        )
    return {
        "protected_usernames": sorted(PROTECTED_USERNAMES),
        "policy": {
            "auto_delete_disabled": True,
            "hard_delete_requires_zero_refs": True,
            "default_action": "deactivate_or_soft_delete",
            "confirm_phrase": "DELETE_TEST_ACCOUNTS",
            "backup_required": True,
        },
        "items": items,
        "candidate_count": sum(
            1 for i in items if not i["protected"] and not i["is_self"]
        ),
    }


@router.post("/preview")
def preview_cleanup(
    body: CleanupExecuteBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """실행 전 Preview — DB 변경 없음."""

    candidates = list_cleanup_candidates(
        include_deleted=True, session=session, user=user
    )
    by_id = {int(i["user_id"]): i for i in candidates["items"]}
    selected = []
    blocked = []
    for uid in body.user_ids:
        row = by_id.get(int(uid))
        if row is None:
            blocked.append({"user_id": uid, "reason": "NOT_FOUND"})
            continue
        if row["protected"]:
            blocked.append({"user_id": uid, "reason": "PROTECTED_USERNAME"})
            continue
        if row["is_self"]:
            blocked.append({"user_id": uid, "reason": "SELF_DELETE_FORBIDDEN"})
            continue
        selected.append(row)
    return {
        "mode": body.mode,
        "selected_count": len(selected),
        "blocked": blocked,
        "selected": selected,
        "would_mutate": False,
        "note": "This endpoint never mutates. Call /execute with confirmations.",
    }


@router.post("/execute")
def execute_cleanup(
    body: CleanupExecuteBody,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    """명시 확인 후에만 deactivate/soft_delete. Hard delete 금지."""

    if body.confirm_phrase != "DELETE_TEST_ACCOUNTS":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirm_phrase must be DELETE_TEST_ACCOUNTS",
        )
    if not body.backup_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="backup_confirmed must be true (DB backup acknowledgement)",
        )
    mode = (body.mode or "deactivate").strip().lower()
    if mode not in {"deactivate", "soft_delete"}:
        raise HTTPException(
            status_code=422,
            detail="mode must be deactivate or soft_delete (hard_delete forbidden)",
        )

    preview = preview_cleanup(body, session, user)
    if preview["blocked"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "blocked users present", "blocked": preview["blocked"]},
        )

    from stock_platform.auth.user_admin_service import UserAdminService

    admin_svc = UserAdminService(session)
    results = []
    for row in preview["selected"]:
        uid = int(row["user_id"])
        if mode == "deactivate":
            admin_svc.set_active(
                uid, is_active=False, actor_user_id=int(user.user_id)
            )
            action = "MEMBER_CLEANUP_DEACTIVATE"
        else:
            admin_svc.soft_delete_member(
                uid, actor_user_id=int(user.user_id)
            )
            action = "MEMBER_CLEANUP_SOFT_DELETE"
        results.append({"user_id": uid, "action": action})
        audit.record(
            event_type=action,
            actor=str(user.username),
            detail={"username": row["username"], "mode": mode, "user_id": uid},
        )
    session.commit()
    return {
        "executed": True,
        "mode": mode,
        "count": len(results),
        "results": results,
        "hard_delete_performed": False,
    }
