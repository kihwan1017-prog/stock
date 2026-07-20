"""사용자 Self Profile / Session / Connections — STEP73.

관리자 `/api/v1/users` 와 분리. JWT user_id 만 사용.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from stock_platform.auth.jwt_service import JwtError, JwtTokenService
from stock_platform.auth.password import PasswordHasher
from stock_platform.auth.repository import AuthRepository
from stock_platform.common.security_mask import (
    mask_chat_id,
    mask_email,
    mask_ip,
)
from stock_platform.common.settings import get_settings
from stock_platform.trading.user_account_service import UserAccountService


logger = logging.getLogger(__name__)

_HTML_RE = re.compile(r"[<>]")
_NICKNAME_RE = re.compile(r"^[\w.\-가-힣]+$", re.UNICODE)


class UserProfileError(ValueError):
    pass


class UserProfileService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = AuthRepository(session)
        self._passwords = PasswordHasher()
        self._jwt = JwtTokenService(get_settings())
        self._accounts = UserAccountService(session)

    def get_profile(self, user_id: int) -> dict[str, Any]:
        user = self._require_user(user_id)
        email = user.email or ""
        return {
            "user_id": user.user_id,
            "username": user.username,
            "email": mask_email(email) if email else None,
            "email_full": email or None,
            "display_name": user.display_name,
            "nickname": user.nickname,
            "profile_image_url": user.profile_image_url,
            "bio": user.bio,
            "locale": user.locale or "KO",
            "status": "ACTIVE" if user.is_active else "INACTIVE",
            "email_verified": bool(user.email_verified),
            "last_login_at": user.last_login_at,
            "last_password_changed_at": user.password_changed_at,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            # 2FA 확장 자리 (미구현)
            "two_factor_enabled": False,
            "two_factor_method": None,
            "two_factor_enrolled_at": None,
        }

    def update_profile(
        self, user_id: int, patch: dict[str, Any]
    ) -> dict[str, Any]:
        user = self._require_user(user_id)
        allowed = {
            "display_name",
            "nickname",
            "profile_image_url",
            "bio",
            "locale",
        }
        unknown = set(patch.keys()) - allowed
        if unknown:
            raise UserProfileError(
                f"수정할 수 없는 필드: {', '.join(sorted(unknown))}"
            )
        if not patch:
            raise UserProfileError("변경할 필드가 없습니다.")

        if "display_name" in patch:
            user.display_name = self._clean_text(
                patch["display_name"],
                field="display_name",
                max_len=100,
                allow_empty=True,
            )
        if "nickname" in patch:
            nick = self._clean_text(
                patch["nickname"],
                field="nickname",
                max_len=50,
                allow_empty=True,
            )
            if nick and not _NICKNAME_RE.match(nick):
                raise UserProfileError(
                    "nickname은 한글·영문·숫자·._- 만 사용할 수 있습니다."
                )
            user.nickname = nick
        if "bio" in patch:
            user.bio = self._clean_text(
                patch["bio"],
                field="bio",
                max_len=500,
                allow_empty=True,
            )
        if "profile_image_url" in patch:
            user.profile_image_url = self._validate_image_url(
                patch["profile_image_url"]
            )
        if "locale" in patch:
            locale = str(patch["locale"] or "").strip().upper()
            if locale not in {"KO", "EN"}:
                raise UserProfileError("locale은 KO|EN 만 허용됩니다.")
            user.locale = locale

        user.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        logger.info(
            "user_profile_updated user_id=%s fields=%s",
            user_id,
            sorted(patch.keys()),
        )
        return self.get_profile(user_id)

    def change_password(
        self,
        user_id: int,
        *,
        current_password: str,
        new_password: str,
        new_password_confirmation: str,
        current_refresh_token: str | None = None,
    ) -> dict[str, Any]:
        user = self._require_user(user_id)
        if new_password != new_password_confirmation:
            raise UserProfileError(
                "새 비밀번호와 확인 비밀번호가 일치하지 않습니다."
            )
        self._validate_password_policy(new_password, email=user.email)

        if not self._passwords.verify(current_password, user.password_hash):
            logger.info(
                "user_password_change_failed user_id=%s reason=bad_current",
                user_id,
            )
            raise UserProfileError("현재 비밀번호가 올바르지 않습니다.")
        if current_password == new_password:
            raise UserProfileError(
                "새 비밀번호는 현재 비밀번호와 달라야 합니다."
            )

        exclude_jti = self._jti_from_refresh(current_refresh_token)
        self._repo.update_password(
            user,
            password_hash=self._passwords.hash(new_password),
        )
        revoked = self._repo.revoke_all_for_user(
            user_id,
            exclude_jti=exclude_jti,
            reason="PASSWORD_CHANGED",
        )
        self._session.flush()
        logger.info(
            "user_password_changed user_id=%s revoked_sessions=%s "
            "kept_current=%s",
            user_id,
            revoked,
            bool(exclude_jti),
        )
        return {
            "changed": True,
            "revoked_session_count": revoked,
            "current_session_kept": bool(exclude_jti),
            "last_password_changed_at": user.password_changed_at,
        }

    def list_sessions(
        self, user_id: int, *, current_refresh_token: str | None = None
    ) -> dict[str, Any]:
        current_jti = self._jti_from_refresh(current_refresh_token)
        items = []
        for row in self._repo.list_active_sessions(user_id):
            items.append(
                {
                    "session_id": row.session_public_id,
                    "device_name": row.device_name or "Unknown device",
                    "browser_name": row.browser_name,
                    "operating_system": row.operating_system,
                    "ip_address_masked": mask_ip(row.ip_address),
                    "created_at": row.created_at,
                    "last_used_at": row.last_used_at or row.created_at,
                    "expires_at": row.expires_at,
                    "is_current": bool(
                        current_jti and row.jti == current_jti
                    ),
                }
            )
        return {"items": items, "total": len(items)}

    def revoke_session(
        self,
        user_id: int,
        session_public_id: str,
        *,
        current_refresh_token: str | None = None,
    ) -> dict[str, Any]:
        row = self._repo.get_refresh_by_public_id(
            user_id=user_id, session_public_id=session_public_id
        )
        if row is None:
            raise UserProfileError("세션을 찾을 수 없습니다.")
        current_jti = self._jti_from_refresh(current_refresh_token)
        is_current = bool(current_jti and row.jti == current_jti)
        if row.revoked_at is None:
            self._repo.revoke_refresh(row.jti, reason="USER_REVOKE")
        logger.info(
            "user_session_revoked user_id=%s session=%s is_current=%s",
            user_id,
            session_public_id,
            is_current,
        )
        return {
            "revoked": True,
            "session_id": session_public_id,
            "was_current": is_current,
        }

    def revoke_sessions(
        self,
        user_id: int,
        *,
        exclude_current: bool = True,
        current_refresh_token: str | None = None,
    ) -> dict[str, Any]:
        exclude_jti = (
            self._jti_from_refresh(current_refresh_token)
            if exclude_current
            else None
        )
        count = self._repo.revoke_all_for_user(
            user_id,
            exclude_jti=exclude_jti,
            reason=(
                "REVOKE_OTHERS" if exclude_current else "REVOKE_ALL"
            ),
        )
        logger.info(
            "user_sessions_revoked user_id=%s count=%s exclude_current=%s",
            user_id,
            count,
            exclude_current,
        )
        return {
            "revoked_count": count,
            "exclude_current": exclude_current,
            "current_session_kept": bool(exclude_jti),
        }

    def accounts_summary(self, user_id: int) -> dict[str, Any]:
        items = self._accounts.list_accounts(user_id=user_id)
        paper = [a for a in items if a.account_type.upper() == "PAPER"]
        kiwoom = [a for a in items if a.broker_code.upper() == "KIWOOM"]
        upbit = [a for a in items if a.broker_code.upper() == "UPBIT"]
        default = next((a for a in items if a.is_default), None)
        return {
            "paper_accounts": {
                "count": len(paper),
                "default_account_id": (
                    default.account_id
                    if default and default.account_type.upper() == "PAPER"
                    else (paper[0].account_id if paper else None)
                ),
            },
            "kiwoom_accounts": {
                "count": len(kiwoom),
                "connected": any(
                    a.connection_status.upper() == "CONNECTED" for a in kiwoom
                ),
            },
            "upbit_accounts": {
                "count": len(upbit),
                "connected": any(
                    a.connection_status.upper() == "CONNECTED" for a in upbit
                ),
            },
            "total_accounts": len(items),
            "default_account_id": default.account_id if default else None,
        }

    def list_connections(self, user_id: int) -> dict[str, Any]:
        summary = self.accounts_summary(user_id)
        items = self._accounts.list_accounts(user_id=user_id)

        def _broker_card(code: str, display: str) -> dict[str, Any]:
            rows = [a for a in items if a.broker_code.upper() == code]
            connected = [
                a
                for a in rows
                if a.connection_status.upper() == "CONNECTED"
            ]
            primary = connected[0] if connected else (rows[0] if rows else None)
            status = "NOT_CONNECTED"
            if primary:
                status = (
                    "CONNECTED"
                    if primary.connection_status.upper() == "CONNECTED"
                    else primary.connection_status.upper()
                )
            return {
                "connection_type": code,
                "status": status,
                "display_name": display,
                "account_masked": (
                    primary.masked_account_number if primary else None
                ),
                "mode": (
                    "PAPER"
                    if primary and primary.account_type.upper() == "PAPER"
                    else ("LIVE" if primary else None)
                ),
                "last_verified_at": (
                    primary.last_synced_at if primary else None
                ),
                "last_success_at": (
                    primary.last_synced_at if primary else None
                ),
                "last_error_code": None,
                "can_disconnect": bool(connected),
                "manage_path": "/user/account",
            }

        telegram = self._repo.get_connection(
            user_id=user_id, connection_type="TELEGRAM"
        )
        if telegram and telegram.status == "CONNECTED":
            tg = {
                "connection_type": "TELEGRAM",
                "status": "CONNECTED",
                "display_name": "Telegram",
                "account_masked": telegram.external_ref_masked,
                "mode": None,
                "last_verified_at": telegram.last_verified_at,
                "last_success_at": telegram.last_success_at,
                "last_error_code": telegram.last_error_code,
                "can_disconnect": True,
                "manage_path": "/user/notifications",
            }
        else:
            tg = {
                "connection_type": "TELEGRAM",
                "status": "NOT_CONNECTED",
                "display_name": "Telegram",
                "account_masked": None,
                "mode": None,
                "last_verified_at": None,
                "last_success_at": None,
                "last_error_code": None,
                "can_disconnect": False,
                "manage_path": "/user/notifications",
                "note": (
                    "일회용 연결 코드 흐름은 후속 STEP에서 구현합니다. "
                    "알림 채널 구독은 알림 센터에서 관리합니다."
                ),
            }

        return {
            "connections": [
                _broker_card("KIWOOM", "키움증권"),
                _broker_card("UPBIT", "업비트"),
                tg,
            ],
            "accounts_summary": summary,
        }

    def disconnect_telegram(self, user_id: int) -> dict[str, Any]:
        deleted = self._repo.delete_connection(
            user_id=user_id, connection_type="TELEGRAM"
        )
        logger.info(
            "user_telegram_disconnected user_id=%s deleted=%s",
            user_id,
            deleted,
        )
        return {"disconnected": True, "connection_type": "TELEGRAM"}

    def _require_user(self, user_id: int):
        user = self._repo.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UserProfileError("사용자를 찾을 수 없습니다.")
        return user

    def _jti_from_refresh(self, refresh_token: str | None) -> str | None:
        if not refresh_token:
            return None
        try:
            payload = self._jwt.decode_refresh_token(refresh_token)
        except JwtError:
            return None
        jti = str(payload.get("jti") or "")
        return jti or None

    @staticmethod
    def _clean_text(
        value: Any,
        *,
        field: str,
        max_len: int,
        allow_empty: bool,
    ) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            if allow_empty:
                return None
            raise UserProfileError(f"{field}가 비어 있습니다.")
        if _HTML_RE.search(text):
            raise UserProfileError(f"{field}에 HTML 문자를 사용할 수 없습니다.")
        if len(text) > max_len:
            raise UserProfileError(
                f"{field}는 최대 {max_len}자까지 가능합니다."
            )
        return text

    @staticmethod
    def _validate_image_url(value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        text = str(value).strip()
        if len(text) > 500:
            raise UserProfileError("profile_image_url이 너무 깁니다.")
        parsed = urlparse(text)
        if parsed.scheme not in {"https", "http"}:
            raise UserProfileError(
                "profile_image_url은 http(s) URL만 허용됩니다."
            )
        if _HTML_RE.search(text):
            raise UserProfileError("profile_image_url이 올바르지 않습니다.")
        return text

    @staticmethod
    def _validate_password_policy(
        password: str, *, email: str | None
    ) -> None:
        if len(password) < 8:
            raise UserProfileError("비밀번호는 최소 8자 이상이어야 합니다.")
        if len(password) > 128:
            raise UserProfileError("비밀번호가 너무 깁니다.")
        if password.lower() in {"password", "12345678", "qwerty123"}:
            raise UserProfileError("너무 단순한 비밀번호입니다.")
        if email and password.lower() == email.strip().lower():
            raise UserProfileError(
                "이메일과 동일한 비밀번호는 사용할 수 없습니다."
            )
        classes = 0
        if re.search(r"[a-z]", password):
            classes += 1
        if re.search(r"[A-Z]", password):
            classes += 1
        if re.search(r"\d", password):
            classes += 1
        if re.search(r"[^A-Za-z0-9]", password):
            classes += 1
        if classes < 2:
            raise UserProfileError(
                "비밀번호는 영문·숫자·특수문자 중 2종류 이상 포함해야 합니다."
            )


def hash_external_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mask_external_chat(value: str) -> str:
    return mask_chat_id(value)
