from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from stock_platform.auth.jwt_service import JwtError, JwtTokenService
from stock_platform.auth.models import AuthUser
from stock_platform.auth.password import PasswordHasher
from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.repository import AuthRepository
from stock_platform.common.settings import Settings


class AuthError(ValueError):
    """인증·인가 도메인 오류."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


@dataclass(frozen=True)
class AuthUserView:
    id: str
    username: str
    display_name: str | None
    roles: list[str]
    permissions: list[str]
    email: str | None = None
    user_status: str = "ACTIVE"
    password_change_required: bool = False
    default_route: str = "/user/dashboard"
    onboarding_completed: bool = False


def _roles_of(
    user: AuthUser,
    rbac: RbacRepository | None = None,
) -> list[str]:
    from stock_platform.auth.role_sync import resolve_role_codes

    return resolve_role_codes(user, rbac)


def _permissions_of(
    user: AuthUser,
    rbac: RbacRepository | None = None,
) -> list[str]:
    if rbac is None:
        return []
    return rbac.list_permission_codes_for_user(user.user_id)


def to_user_view(
    user: AuthUser,
    rbac: RbacRepository | None = None,
) -> AuthUserView:
    from stock_platform.auth.user_status import (
        resolve_default_route,
        resolve_user_status,
    )

    roles = _roles_of(user, rbac)
    return AuthUserView(
        id=str(user.user_id),
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
        permissions=_permissions_of(user, rbac),
        user_status=resolve_user_status(user),
        password_change_required=bool(
            getattr(user, "password_change_required", False)
        ),
        default_route=resolve_default_route(user=user, roles=roles),
        onboarding_completed=bool(
            getattr(user, "onboarding_completed_at", None)
        ),
    )


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        settings: Settings,
        jwt_service: JwtTokenService | None = None,
        rbac_repository: RbacRepository | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._jwt = jwt_service or JwtTokenService(settings)
        self._passwords = PasswordHasher()
        self._rbac = rbac_repository

    def ensure_bootstrap_admin(self) -> AuthUser | None:
        """사용자가 없고 bootstrap 자격증명이 있으면 관리자를 생성한다."""

        if self._repository.count_users() > 0:
            return None

        username = self._settings.auth_bootstrap_admin_username.strip()
        password = self._settings.auth_bootstrap_admin_password
        if not username or not password:
            return None

        user = self._repository.create_user(
            username=username,
            password_hash=self._passwords.hash(password),
            display_name="Bootstrap Admin",
            roles=["admin"],
        )
        self._sync_user_roles(user.user_id, ["admin"])
        return user

    def signup(
        self,
        *,
        name: str,
        username: str,
        email: str,
        password: str,
        password_confirm: str,
        terms_accepted: bool,
    ) -> tuple[TokenPair, AuthUserView]:
        """일반 사용자 회원가입 후 Access/Refresh 토큰을 즉시 발급한다."""

        if not terms_accepted:
            raise AuthError("약관에 동의해야 회원가입할 수 있습니다.")
        if password != password_confirm:
            raise AuthError("비밀번호와 비밀번호 확인이 일치하지 않습니다.")

        cleaned_name = name.strip()
        if not cleaned_name:
            raise AuthError("이름을 입력하세요.")

        cleaned_username = username.strip().lower()
        cleaned_email = email.strip().lower()

        if self._repository.username_exists(cleaned_username):
            raise AuthError("이미 사용 중인 아이디입니다.")
        if self._repository.email_exists(cleaned_email):
            raise AuthError("이미 사용 중인 이메일입니다.")

        user = self._repository.create_user(
            username=cleaned_username,
            password_hash=self._passwords.hash(password),
            display_name=cleaned_name,
            roles=["user"],
            email=cleaned_email,
            terms_accepted_at=datetime.now(timezone.utc),
        )
        self._sync_user_roles(user.user_id, ["user"])
        return self._issue_tokens(user), to_user_view(user, self._rbac)

    def check_username_available(self, username: str) -> bool:
        cleaned = username.strip().lower()
        if not cleaned:
            return False
        return not self._repository.username_exists(cleaned)

    def check_email_available(self, email: str) -> bool:
        cleaned = email.strip().lower()
        if not cleaned:
            return False
        return not self._repository.email_exists(cleaned)

    def login(
        self,
        *,
        username: str,
        password: str,
        session_meta: dict[str, str | None] | None = None,
    ) -> tuple[TokenPair, AuthUserView]:
        from datetime import timedelta

        from stock_platform.auth.user_status import (
            STATUS_LOCKED,
            resolve_user_status,
        )

        # 아이디 또는 이메일로 조회 — 존재 여부 노출 방지 동일 메시지
        generic = "사용자명 또는 비밀번호가 올바르지 않습니다."
        user = self._repository.get_by_username_or_email(username)
        if user is None or user.deleted_at is not None:
            raise AuthError(generic)
        if not user.is_active:
            raise AuthError(generic)

        status = resolve_user_status(user)
        if status == STATUS_LOCKED:
            raise AuthError(
                "계정이 일시 잠금되었습니다. 잠시 후 다시 시도하세요."
            )

        if not self._passwords.verify(password, user.password_hash):
            self._register_failed_login(user)
            raise AuthError(generic)

        from stock_platform.auth.role_codes import has_valid_app_role

        if self._rbac is not None:
            from stock_platform.auth.role_sync import reconcile_user_roles

            reconcile_user_roles(
                self._repository._session,
                user,
                self._rbac,
                commit=False,
            )

        roles = _roles_of(user, self._rbac)
        if not has_valid_app_role(roles):
            raise AuthError(
                "계정에 유효한 권한이 없습니다. 관리자에게 문의하세요."
            )

        # 성공: 실패 카운터 초기화
        user.failed_login_count = 0
        user.locked_until = None
        ip = None
        if session_meta:
            ip = session_meta.get("ip_address") or session_meta.get("client_ip")
        if ip:
            user.last_login_ip = str(ip)[:64]
        self._repository.mark_last_login(user)
        return (
            self._issue_tokens(user, session_meta=session_meta),
            to_user_view(user, self._rbac),
        )

    def login_with_google_identity(
        self,
        *,
        subject: str,
        email: str,
        email_verified: bool,
        session_meta: dict[str, str | None] | None = None,
    ) -> tuple[TokenPair, AuthUserView]:
        """테스트/직접 호출용 — resolve 후 즉시 JWT 발급."""

        user = self.resolve_google_user(
            subject=subject,
            email=email,
            email_verified=email_verified,
            session_meta=session_meta,
        )
        return (
            self._issue_tokens(user, session_meta=session_meta),
            to_user_view(user, self._rbac),
        )

    def resolve_google_user(
        self,
        *,
        subject: str,
        email: str,
        email_verified: bool,
        session_meta: dict[str, str | None] | None = None,
    ) -> AuthUser:
        """Google 검증 identity → 기존 DB 사용자 (자동 가입 없음)."""

        from sqlalchemy import select

        from stock_platform.auth.google_oauth import upsert_google_identity
        from stock_platform.auth.models import UserExternalIdentity
        from stock_platform.auth.role_codes import has_valid_app_role
        from stock_platform.auth.user_status import (
            STATUS_LOCKED,
            resolve_user_status,
        )

        if not email_verified:
            raise AuthError("인증되지 않은 Google 이메일은 사용할 수 없습니다.")

        cleaned_email = email.strip().lower()
        if not cleaned_email:
            raise AuthError("Google 계정 이메일을 확인할 수 없습니다.")

        linked = self._repository._session.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.provider == "google",
                UserExternalIdentity.provider_subject == subject,
            )
        )
        user = None
        if linked is not None:
            user = self._repository.get_by_id(int(linked.user_id))
        if user is None:
            user = self._repository.get_by_email(cleaned_email)

        if user is None or user.deleted_at is not None:
            raise AuthError(
                "GOOGLE_ACCOUNT_NOT_REGISTERED: "
                "등록되지 않은 Google 계정입니다. 관리자에게 계정 등록을 요청하세요."
            )
        if not user.is_active:
            raise AuthError("비활성 계정입니다. 관리자에게 문의하세요.")

        status = resolve_user_status(user)
        if status == STATUS_LOCKED:
            raise AuthError(
                "계정이 일시 잠금되었습니다. 잠시 후 다시 시도하세요."
            )

        if self._rbac is not None:
            from stock_platform.auth.role_sync import reconcile_user_roles

            reconcile_user_roles(
                self._repository._session,
                user,
                self._rbac,
                commit=False,
            )

        roles = _roles_of(user, self._rbac)
        if not has_valid_app_role(roles):
            raise AuthError(
                "계정에 유효한 권한이 없습니다. 관리자에게 문의하세요."
            )

        upsert_google_identity(
            self._repository._session,
            user_id=int(user.user_id),
            subject=subject,
            email=cleaned_email,
        )

        user.failed_login_count = 0
        user.locked_until = None
        ip = None
        if session_meta:
            ip = session_meta.get("ip_address") or session_meta.get("client_ip")
        if ip:
            user.last_login_ip = str(ip)[:64]
        if not user.email_verified:
            user.email_verified = True
        self._repository.mark_last_login(user)
        return user

    def issue_tokens_for_user_id(
        self,
        user_id: int,
        *,
        session_meta: dict[str, str | None] | None = None,
    ) -> tuple[TokenPair, AuthUserView]:
        """handoff 교환용 — 이미 인증된 user_id에 대해 JWT만 재발급."""

        from stock_platform.auth.role_codes import has_valid_app_role
        from stock_platform.auth.user_status import (
            STATUS_LOCKED,
            resolve_user_status,
        )

        user = self._repository.get_by_id(int(user_id))
        if user is None or user.deleted_at is not None or not user.is_active:
            raise AuthError("사용자를 찾을 수 없습니다.")
        if resolve_user_status(user) == STATUS_LOCKED:
            raise AuthError(
                "계정이 일시 잠금되었습니다. 잠시 후 다시 시도하세요."
            )
        if self._rbac is not None:
            from stock_platform.auth.role_sync import reconcile_user_roles

            reconcile_user_roles(
                self._repository._session,
                user,
                self._rbac,
                commit=False,
            )
        roles = _roles_of(user, self._rbac)
        if not has_valid_app_role(roles):
            raise AuthError(
                "계정에 유효한 권한이 없습니다. 관리자에게 문의하세요."
            )
        return (
            self._issue_tokens(user, session_meta=session_meta),
            to_user_view(user, self._rbac),
        )

    def _register_failed_login(self, user: AuthUser) -> None:
        self._repository.record_failed_login(
            user,
            max_fails=self._settings.auth_max_failed_logins,
            lockout_minutes=self._settings.auth_lockout_minutes,
        )

    def refresh(
        self,
        *,
        refresh_token: str,
        session_meta: dict[str, str | None] | None = None,
    ) -> tuple[TokenPair, AuthUserView]:
        try:
            payload = self._jwt.decode_refresh_token(refresh_token)
        except JwtError as exc:
            raise AuthError(str(exc)) from exc

        jti = str(payload.get("jti") or "")
        user_id = int(payload.get("sub") or 0)
        row = self._repository.get_refresh_by_jti(jti)
        if row is None:
            raise AuthError("Refresh 토큰이 유효하지 않습니다.")
        # 이미 revoke된 토큰 재사용 → 세션 전체 폐기 (theft 대응)
        if row.revoked_at is not None:
            self._repository.revoke_all_for_user(
                user_id, reason="REFRESH_REUSE"
            )
            raise AuthError(
                "Refresh 토큰이 재사용되었습니다. 모든 세션이 만료되었습니다."
            )
        if row.user_id != user_id:
            raise AuthError("Refresh 토큰이 유효하지 않습니다.")
        expected = self._jwt.hash_token(refresh_token)
        if not secrets_compare(row.token_hash, expected):
            self._repository.revoke_all_for_user(
                user_id, reason="REFRESH_HASH_MISMATCH"
            )
            raise AuthError("Refresh 토큰이 유효하지 않습니다.")

        user = self._repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthError("사용자를 찾을 수 없습니다.")

        # 회전: 기존 refresh revoke 후 재발급
        self._repository.revoke_refresh(jti, reason="ROTATED")
        return (
            self._issue_tokens(user, session_meta=session_meta),
            to_user_view(user, self._rbac),
        )

    def logout(self, *, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            payload = self._jwt.decode_refresh_token(refresh_token)
        except JwtError:
            return
        jti = str(payload.get("jti") or "")
        if jti:
            self._repository.revoke_refresh(jti, reason="LOGOUT")

    def get_user(self, user_id: int) -> AuthUserView:
        user = self._repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthError("사용자를 찾을 수 없습니다.")
        return to_user_view(user, self._rbac)

    def change_password(
        self,
        *,
        user_id: int,
        current_password: str,
        new_password: str,
        exclude_jti: str | None = None,
    ) -> None:
        user = self._repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthError("사용자를 찾을 수 없습니다.")
        if not self._passwords.verify(
            current_password,
            user.password_hash,
        ):
            raise AuthError("현재 비밀번호가 올바르지 않습니다.")
        if current_password == new_password:
            raise AuthError(
                "새 비밀번호는 현재 비밀번호와 달라야 합니다."
            )
        self._repository.update_password(
            user,
            password_hash=self._passwords.hash(new_password),
        )
        self._repository.set_password_change_required(
            user,
            required=False,
        )
        # 기본: 다른 세션 폐기. exclude_jti 있으면 현재 세션 유지
        self._repository.revoke_all_for_user(
            user_id,
            exclude_jti=exclude_jti,
            reason="PASSWORD_CHANGED",
        )

    def complete_onboarding(self, *, user_id: int) -> AuthUserView:
        user = self._repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthError("사용자를 찾을 수 없습니다.")
        self._repository.mark_onboarding_completed(user)
        return to_user_view(user, self._rbac)

    def unlock_user(self, *, user_id: int) -> AuthUserView:
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise AuthError("사용자를 찾을 수 없습니다.")
        self._repository.clear_lockout(user)
        return to_user_view(user, self._rbac)

    def _issue_tokens(
        self,
        user: AuthUser,
        *,
        session_meta: dict[str, str | None] | None = None,
    ) -> TokenPair:
        roles = _roles_of(user, self._rbac)
        access, expires_in = self._jwt.create_access_token(
            user_id=user.user_id,
            username=user.username,
            roles=roles,
        )
        refresh, jti, expires_at = self._jwt.create_refresh_token(
            user_id=user.user_id,
        )
        meta = session_meta or {}
        self._repository.save_refresh_token(
            user_id=user.user_id,
            jti=jti,
            token_hash=self._jwt.hash_token(refresh),
            expires_at=expires_at,
            device_name=meta.get("device_name"),
            browser_name=meta.get("browser_name"),
            operating_system=meta.get("operating_system"),
            ip_address=meta.get("ip_address"),
            user_agent=meta.get("user_agent"),
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
        )

    def _sync_user_roles(self, user_id: int, role_codes: list[str]) -> None:
        if self._rbac is None:
            return
        role_ids = self._rbac.get_role_ids_by_codes(role_codes)
        if role_ids:
            self._rbac.replace_user_roles(user_id, role_ids)


def secrets_compare(left: str, right: str) -> bool:
    import secrets

    return secrets.compare_digest(left, right)


def user_view_dict(view: AuthUserView) -> dict[str, Any]:
    return {
        "id": view.id,
        "username": view.username,
        "email": view.email,
        "display_name": view.display_name,
        "roles": view.roles,
        "permissions": view.permissions,
        "user_status": view.user_status,
        "password_change_required": view.password_change_required,
        "default_route": view.default_route,
        "onboarding_completed": view.onboarding_completed,
    }
