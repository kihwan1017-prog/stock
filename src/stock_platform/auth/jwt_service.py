from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from stock_platform.common.settings import (
    Settings,
    format_jwt_secret_missing_message,
)


class JwtError(ValueError):
    """JWT 발급·검증 오류."""


class JwtTokenService:
    """Access / Refresh JWT 발급·검증."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        secret = settings.jwt_secret.strip()
        if not secret:
            raise JwtError(format_jwt_secret_missing_message())
        self._secret = secret
        self._algorithm = settings.jwt_algorithm

    def create_access_token(
        self,
        *,
        user_id: int,
        username: str,
        roles: list[str],
    ) -> tuple[str, int]:
        expire_minutes = self._settings.jwt_access_token_expire_minutes
        expires_delta = timedelta(minutes=expire_minutes)
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "username": username,
            "roles": roles,
            "type": "access",
            "iat": now,
            "exp": now + expires_delta,
        }
        token = jwt.encode(
            payload,
            self._secret,
            algorithm=self._algorithm,
        )
        return token, int(expires_delta.total_seconds())

    def create_refresh_token(
        self,
        *,
        user_id: int,
    ) -> tuple[str, str, datetime]:
        """returns (raw_token, jti, expires_at)"""

        expire_days = self._settings.jwt_refresh_token_expire_days
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=expire_days
        )
        jti = secrets.token_urlsafe(24)
        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "jti": jti,
            "iat": datetime.now(timezone.utc),
            "exp": expires_at,
        }
        token = jwt.encode(
            payload,
            self._secret,
            algorithm=self._algorithm,
        )
        return token, jti, expires_at

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
            )
        except jwt.ExpiredSignatureError as exc:
            raise JwtError("토큰이 만료되었습니다.") from exc
        except jwt.InvalidTokenError as exc:
            raise JwtError("유효하지 않은 토큰입니다.") from exc
        if not isinstance(payload, dict):
            raise JwtError("유효하지 않은 토큰입니다.")
        return payload

    def decode_access_token(self, token: str) -> dict[str, Any]:
        payload = self.decode_token(token)
        if payload.get("type") != "access":
            raise JwtError("Access 토큰이 아닙니다.")
        return payload

    def decode_refresh_token(self, token: str) -> dict[str, Any]:
        payload = self.decode_token(token)
        if payload.get("type") != "refresh":
            raise JwtError("Refresh 토큰이 아닙니다.")
        return payload

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()
