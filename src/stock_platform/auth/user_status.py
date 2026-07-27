"""사용자 상태·기본 라우트 판정 (DB 기준, JWT claim 비신뢰)."""

from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.auth.models import AuthUser
from stock_platform.auth.role_codes import (
    ALLOWED_ROLES,
    normalize_role_codes,
)


STATUS_ACTIVE = "ACTIVE"
STATUS_INACTIVE = "INACTIVE"
STATUS_LOCKED = "LOCKED"
STATUS_PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
STATUS_DELETED = "DELETED"


def resolve_user_status(user: AuthUser) -> str:
    if user.deleted_at is not None:
        return STATUS_DELETED
    if not user.is_active:
        return STATUS_INACTIVE
    locked_until = getattr(user, "locked_until", None)
    if locked_until is not None:
        now = datetime.now(timezone.utc)
        until = locked_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until > now:
            return STATUS_LOCKED
    if getattr(user, "password_change_required", False):
        return STATUS_PASSWORD_CHANGE_REQUIRED
    return STATUS_ACTIVE


def resolve_default_route(
    *,
    user: AuthUser,
    roles: list[str],
) -> str:
    """
    로그인 후 권장 초기 경로 (편의용).
    실제 인가·관리자 판정은 DB RBAC 재검증을 사용한다.
    """

    status = resolve_user_status(user)
    if status in {STATUS_INACTIVE, STATUS_DELETED, STATUS_LOCKED}:
        return "/login"
    if status == STATUS_PASSWORD_CHANGE_REQUIRED:
        return "/change-password"

    role_set = set(normalize_role_codes(list(roles)))
    if not role_set.intersection(ALLOWED_ROLES):
        # Role 없음·잘못된 Role — 접근 차단
        return "/forbidden"

    if getattr(user, "onboarding_completed_at", None) is None:
        # 관리자는 온보딩 스킵
        if "admin" not in role_set:
            return "/onboarding"
    if "admin" in role_set:
        return "/admin/dashboard"
    return "/user/dashboard"
