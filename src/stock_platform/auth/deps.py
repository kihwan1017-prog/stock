from __future__ import annotations

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


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    username: str
    roles: list[str]
    permissions: list[str]
    display_name: str | None = None
    email: str | None = None

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

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
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    rbac = RbacRepository(session)
    view = to_user_view(user, rbac)
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
) -> str:
    """
    민감 운영 API 보호.
    1) admin JWT 또는 ops:execute 권한 JWT
    2) X-Admin-API-Key (서버 env, 스크립트용)
    중 하나면 통과.

    인증은 됐지만 권한 부족 → 403 (FE가 세션 폐기하지 않도록)
    미인증 → 401
    """

    # 단위 테스트에서 함수를 직접 호출할 때 Depends 기본값 방어
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        credentials = None
    if not isinstance(session, Session):
        session = None  # type: ignore[assignment]
    if not isinstance(settings, Settings):
        settings = get_settings()

    jwt_authenticated = False

    # JWT: admin 역할 또는 ops:execute 권한
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
                # JWT claim roles 가 아니라 DB RBAC 재검증 (권한 강등 즉시 반영)
                rbac = RbacRepository(session)
                role_codes = rbac.list_role_codes_for_user(user_id)
                if "admin" in role_codes:
                    return f"JWT:{user.username}"
                perms = rbac.list_permission_codes_for_user(user_id)
                if "ops:execute" in perms:
                    return f"JWT:{user.username}"
        except (JwtError, ValueError, TypeError):
            pass

    expected = settings.admin_api_key.strip()
    provided = (x_admin_api_key or "").strip()
    if expected and provided:
        import secrets

        if secrets.compare_digest(provided, expected):
            return "ADMIN_KEY"

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
