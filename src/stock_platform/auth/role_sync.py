"""Role 해석 헬퍼 — user_role(RBAC)과 user.roles(JSONB) 정합."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.models import AuthUser
from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.role_codes import normalize_role_codes


def resolve_role_codes(
    user: AuthUser,
    rbac: RbacRepository | None = None,
) -> list[str]:
    """RBAC user_role 우선, 비어 있으면 JSONB roles 폴백."""

    if rbac is not None:
        codes = rbac.list_role_codes_for_user(int(user.user_id))
        if codes:
            return normalize_role_codes(codes)
    raw = user.roles or []
    return normalize_role_codes([str(item) for item in raw])


def reconcile_user_roles(
    session: Session,
    user: AuthUser,
    rbac: RbacRepository,
    *,
    commit: bool = False,
) -> tuple[list[str], bool]:
    """
    JSONB ↔ user_role 불일치 치유.
    - user_role이 비고 JSONB에 역할이 있으면 user_role에 적재
    - user_role이 있으면 JSONB를 동일 내용으로 맞춤

    Returns:
        (role_codes, changed)
    """

    rbac_codes = normalize_role_codes(
        rbac.list_role_codes_for_user(int(user.user_id))
    )
    jsonb_codes = normalize_role_codes(
        [str(item) for item in (user.roles or [])]
    )
    changed = False

    if rbac_codes:
        target = rbac_codes
        if jsonb_codes != target:
            user.roles = target
            session.flush()
            changed = True
    elif jsonb_codes:
        target = jsonb_codes
        role_ids = rbac.get_role_ids_by_codes(target)
        if role_ids:
            rbac.replace_user_roles(int(user.user_id), role_ids)
            user.roles = target
            session.flush()
            changed = True
        else:
            target = []
    else:
        target = []

    if commit and changed:
        session.commit()
    return target, changed


def backfill_missing_user_roles(session: Session) -> int:
    """user_role 없는 사용자를 JSONB roles로 일괄 치유. 처리 건수 반환."""

    rbac = RbacRepository(session)
    users = list(session.scalars(select(AuthUser)).all())
    healed = 0
    for user in users:
        before = rbac.list_role_codes_for_user(int(user.user_id))
        if before:
            continue
        if not (user.roles or []):
            continue
        _after, changed = reconcile_user_roles(
            session, user, rbac, commit=False
        )
        if changed:
            healed += 1
    if healed:
        session.flush()
    return healed
