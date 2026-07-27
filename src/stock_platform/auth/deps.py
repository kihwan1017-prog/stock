from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from stock_platform.auth.jwt_service import JwtError, JwtTokenService
from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.repository import AuthRepository
from stock_platform.auth.service import AuthService, to_user_view
from stock_platform.common.settings import Settings, get_settings
from stock_platform.database.session import get_db_session

_bearer = HTTPBearer(auto_error=False)
_logger = logging.getLogger(__name__)

# Admin API Key 인증 시 합성 Principal (JWT 사용자와 구분)
ADMIN_API_KEY_PRINCIPAL_USER_ID = 0


@dataclass(frozen=True)
class AuthenticatedUser:
    """인증 Principal — Admin/User API 공통 계약.

    필드: user_id, username, roles, permissions (+ is_admin)
    Admin API Key 경로: user_id=0, username=ADMIN_KEY, roles=["admin"]
    """

    user_id: int
    username: str
    roles: list[str]
    permissions: list[str]
    display_name: str | None = None
    email: str | None = None

    @property
    def is_admin(self) -> bool:
        # operator 등 레거시 코드는 admin으로 정규화
        from stock_platform.auth.role_codes import normalize_role_codes

        return "admin" in normalize_role_codes(list(self.roles))

    def has_permission(self, *codes: str) -> bool:
        if self.is_admin:
            return True
        owned = set(self.permissions)
        return all(code in owned for code in codes)

    def has_any_permission(self, *codes: str) -> bool:
        if self.is_admin:
            return True
        owned = set(self.permissions)
        return any(code in owned for code in codes)


def admin_actor_label(principal: AuthenticatedUser) -> str:
    """Audit actor — 항상 admin:{user_id}. owner_user_id 와 혼동 금지."""

    if not isinstance(principal, AuthenticatedUser):
        _logger.error(
            "admin_actor_label: invalid principal type=%s",
            type(principal).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin JWT 또는 Admin API Key가 필요합니다.",
        )
    return f"admin:{int(principal.user_id)}"


def admin_api_key_principal() -> AuthenticatedUser:
    """X-Admin-API-Key 통과 시 합성 Principal."""

    return AuthenticatedUser(
        user_id=ADMIN_API_KEY_PRINCIPAL_USER_ID,
        username="ADMIN_KEY",
        roles=["admin"],
        permissions=[],
    )


def get_auth_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(
        repository=AuthRepository(session),
        settings=settings,
        rbac_repository=RbacRepository(session),
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer 토큰이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = JwtTokenService(settings).decode_access_token(
            credentials.credentials
        )
    except JwtError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = int(payload.get("sub") or 0)
    user = AuthRepository(session).get_by_id(user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from stock_platform.auth.user_status import (
        STATUS_LOCKED,
        resolve_user_status,
    )

    if resolve_user_status(user) == STATUS_LOCKED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="계정이 일시 잠금되었습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    rbac = RbacRepository(session)
    # JSONB만 admin이고 user_role이 비어 있으면 치유
    from stock_platform.auth.role_sync import reconcile_user_roles

    _roles, changed = reconcile_user_roles(
        session, user, rbac, commit=False
    )
    view = to_user_view(user, rbac)
    from stock_platform.auth.role_codes import has_valid_app_role

    if not has_valid_app_role(view.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="계정에 유효한 권한이 없습니다.",
        )
    if changed:
        session.commit()
    return AuthenticatedUser(
        user_id=user.user_id,
        username=view.username,
        roles=view.roles,
        permissions=view.permissions,
        display_name=view.display_name,
        email=view.email,
    )


def require_admin_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )
    return user


def require_permission(*permission_codes: str):
    """지정 permission을 모두 보유해야 통과 (admin은 우회)."""

    if not permission_codes:
        raise ValueError("permission_codes가 필요합니다.")

    def _dependency(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.has_permission(*permission_codes):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "권한이 없습니다: "
                + ", ".join(permission_codes)
            ),
        )

    return _dependency


def require_any_permission(*permission_codes: str):
    """지정 permission 중 하나라도 있으면 통과 (admin은 우회)."""

    if not permission_codes:
        raise ValueError("permission_codes가 필요합니다.")

    def _dependency(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.has_any_permission(*permission_codes):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "권한이 없습니다: "
                + ", ".join(permission_codes)
            ),
        )

    return _dependency


def require_authenticated(
    x_admin_api_key: str | None = Header(
        default=None,
        alias="X-Admin-API-Key",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    로그인 사용자(일반 포함) 또는 Admin API Key.
    User Web 조회용 — 세션 유지가 필요한 읽기 API에 사용.
    """

    if not isinstance(credentials, HTTPAuthorizationCredentials):
        credentials = None
    if not isinstance(session, Session):
        session = None  # type: ignore[assignment]
    if not isinstance(settings, Settings):
        settings = get_settings()

    if (
        credentials is not None
        and credentials.scheme.lower() == "bearer"
        and session is not None
    ):
        try:
            payload = JwtTokenService(settings).decode_access_token(
                credentials.credentials
            )
            user_id = int(payload.get("sub") or 0)
            user = AuthRepository(session).get_by_id(user_id)
            if user is not None and user.is_active:
                return f"JWT:{user.username}"
        except (JwtError, ValueError, TypeError):
            pass

    expected = settings.admin_api_key.strip()
    provided = (x_admin_api_key or "").strip()
    if expected and provided:
        import secrets

        if secrets.compare_digest(provided, expected):
            return "ADMIN_KEY"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="로그인이 필요합니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(
    x_admin_api_key: str | None = Header(
        default=None,
        alias="X-Admin-API-Key",
    ),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """
    민감 운영 API 보호 — AuthenticatedUser Principal 반환.

    1) DB 기준 admin 역할 JWT → 해당 사용자 Principal
    2) X-Admin-API-Key → 합성 Principal (user_id=0, username=ADMIN_KEY)

    JWT claim roles / ops:execute 만으로는 통과하지 않는다.
    인증은 됐지만 권한 부족 → 403 (FE가 세션 폐기하지 않도록)
    미인증 → 401

    Audit actor 는 admin_actor_label(principal) 사용.
    """

    # 단위 테스트에서 함수를 직접 호출할 때 Depends 기본값 방어
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        credentials = None
    if not isinstance(session, Session):
        session = None  # type: ignore[assignment]
    if not isinstance(settings, Settings):
        settings = get_settings()

    jwt_authenticated = False

    # JWT: DB 역할 기준 admin만 허용 (user_role ↔ JSONB 정합 후 판정)
    if (
        credentials is not None
        and credentials.scheme.lower() == "bearer"
        and session is not None
    ):
        try:
            payload = JwtTokenService(settings).decode_access_token(
                credentials.credentials
            )
            user_id = int(payload.get("sub") or 0)
            user = AuthRepository(session).get_by_id(user_id)
            if user is not None and user.is_active:
                jwt_authenticated = True
                rbac = RbacRepository(session)
                from stock_platform.auth.role_codes import normalize_role_codes
                from stock_platform.auth.role_sync import (
                    reconcile_user_roles,
                    resolve_role_codes,
                )

                # 드리프트 치유 후 동일 기준으로 판정
                _codes, changed = reconcile_user_roles(
                    session, user, rbac, commit=False
                )
                role_codes = resolve_role_codes(user, rbac)
                if changed:
                    session.commit()
                if "admin" in normalize_role_codes(role_codes):
                    view = to_user_view(user, rbac)
                    return AuthenticatedUser(
                        user_id=int(user.user_id),
                        username=view.username,
                        roles=list(view.roles),
                        permissions=list(view.permissions),
                        display_name=view.display_name,
                        email=view.email,
                    )
        except (JwtError, ValueError, TypeError):
            pass

    expected = settings.admin_api_key.strip()
    provided = (x_admin_api_key or "").strip()
    if expected and provided:
        import secrets

        if secrets.compare_digest(provided, expected):
            return admin_api_key_principal()

    # 로그인된 일반 유저가 Admin API를 친 경우 — 로그아웃 루프 방지
    if jwt_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Admin JWT 또는 Admin API Key가 필요합니다. "
                "ADMIN_API_KEY가 비어 있습니다."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin JWT 또는 Admin API Key가 필요합니다.",
    )
