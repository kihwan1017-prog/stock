"""Google OAuth Authorization Code + ID token 검증 (내부 JWT와 분리)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.models import (
    OAuthHandoff,
    OAuthLoginState,
    UserExternalIdentity,
)
from stock_platform.auth.service import AuthError, AuthService, AuthUserView, TokenPair
from stock_platform.common.settings import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
PROVIDER_GOOGLE = "google"


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool


class GoogleOAuthService:
    """Google = Authentication only. Authorization은 AuthService/DB RBAC."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        auth_service: AuthService,
        *,
        http_client: httpx.Client | None = None,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._auth = auth_service
        self._http = http_client
        self._jwks = jwks_client or PyJWKClient(GOOGLE_JWKS_URL)

    def is_configured(self) -> bool:
        s = self._settings
        return bool(
            s.google_oauth_enabled
            and s.google_oauth_client_id.strip()
            and s.google_oauth_client_secret.strip()
            and s.google_oauth_redirect_uri.strip()
            and s.google_oauth_frontend_complete_url.strip()
        )

    def build_authorization_url(self, *, next_path: str | None) -> str:
        if not self.is_configured():
            raise AuthError("Google 로그인이 설정되지 않았습니다.")

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(minutes=10)
        self._session.add(
            OAuthLoginState(
                state=state,
                nonce=nonce,
                next_path=_safe_next(next_path),
                expires_at=expires,
            )
        )
        self._session.flush()

        params = {
            "client_id": self._settings.google_oauth_client_id.strip(),
            "redirect_uri": self._settings.google_oauth_redirect_uri.strip(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def complete_callback(
        self,
        *,
        code: str,
        state: str,
        session_meta: dict[str, str | None] | None = None,
    ) -> str:
        """Google callback 처리 → FE handoff URL 반환 (토큰은 query에 넣지 않음)."""

        if not self.is_configured():
            raise AuthError("Google 로그인이 설정되지 않았습니다.")
        if not code.strip() or not state.strip():
            raise AuthError("잘못된 Google 로그인 응답입니다.")

        row = self._session.get(OAuthLoginState, state.strip())
        if row is None:
            raise AuthError("잘못된 또는 만료된 로그인 요청입니다.")
        now = datetime.now(timezone.utc)
        if row.expires_at <= now:
            self._session.delete(row)
            self._session.flush()
            raise AuthError("로그인 요청이 만료되었습니다. 다시 시도하세요.")

        nonce = row.nonce
        next_path = row.next_path
        self._session.delete(row)
        self._session.flush()

        id_token = self._exchange_code_for_id_token(code.strip())
        identity = self._verify_id_token(id_token, expected_nonce=nonce)
        user = self._auth.resolve_google_user(
            subject=identity.subject,
            email=identity.email,
            email_verified=identity.email_verified,
            session_meta=session_meta,
        )
        handoff_code = secrets.token_urlsafe(32)
        self._session.add(
            OAuthHandoff(
                code=handoff_code,
                user_id=int(user.user_id),
                next_path=next_path,
                expires_at=now + timedelta(minutes=2),
            )
        )
        self._session.flush()

        base = self._settings.google_oauth_frontend_complete_url.strip().rstrip("/")
        q = urlencode({"code": handoff_code})
        return f"{base}?{q}"

    def exchange_handoff(
        self,
        *,
        code: str,
        session_meta: dict[str, str | None] | None = None,
    ) -> tuple[TokenPair, AuthUserView, str | None]:
        row = self._session.get(OAuthHandoff, code.strip())
        now = datetime.now(timezone.utc)
        if row is None or row.used_at is not None or row.expires_at <= now:
            raise AuthError("로그인 세션이 만료되었거나 이미 사용되었습니다.")
        row.used_at = now
        self._session.flush()
        pair, view = self._auth.issue_tokens_for_user_id(
            row.user_id,
            session_meta=session_meta,
        )
        return pair, view, row.next_path

    def _exchange_code_for_id_token(self, code: str) -> str:
        data = {
            "code": code,
            "client_id": self._settings.google_oauth_client_id.strip(),
            "client_secret": self._settings.google_oauth_client_secret.strip(),
            "redirect_uri": self._settings.google_oauth_redirect_uri.strip(),
            "grant_type": "authorization_code",
        }
        client = self._http or httpx.Client(timeout=15.0)
        owns = self._http is None
        try:
            resp = client.post(GOOGLE_TOKEN_URL, data=data)
        finally:
            if owns:
                client.close()
        if resp.status_code >= 400:
            raise AuthError("Google 인증에 실패했습니다.")
        payload = resp.json()
        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise AuthError("Google ID 토큰을 받지 못했습니다.")
        return id_token

    def _verify_id_token(self, id_token: str, *, expected_nonce: str) -> GoogleIdentity:
        """서명·aud·iss·exp 검증 유지. 실패 stage는 로그에만 (사용자 메시지 고정)."""

        import logging

        log = logging.getLogger(__name__)
        expected_aud = self._settings.google_oauth_client_id.strip()
        stage = "ID_TOKEN_VERIFY"
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(id_token)
            stage = "ID_TOKEN_JWT_DECODE"
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=expected_aud,
                issuer=list(GOOGLE_ISSUERS),
                # HTTPS/PWA 단말 시계 오차 허용 — 서명·aud·만료 검증은 유지
                leeway=120,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except Exception as exc:  # noqa: BLE001 — 검증 실패는 동일 사용자 메시지
            # 미검증 claims는 aud fingerprint만 (시크릿/원문 금지)
            aud_fp = "unknown"
            try:
                raw = jwt.decode(
                    id_token,
                    options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
                    algorithms=["RS256"],
                )
                aud_val = raw.get("aud")
                aud_s = (
                    aud_val
                    if isinstance(aud_val, str)
                    else (",".join(aud_val) if isinstance(aud_val, list) else "")
                )
                if aud_s and len(aud_s) > 10:
                    aud_fp = f"{aud_s[:6]}…{aud_s[-4:]}(len={len(aud_s)})"
                elif aud_s:
                    aud_fp = f"len={len(aud_s)}"
            except Exception:  # noqa: BLE001
                aud_fp = "unreadable"
            exp_fp = f"{expected_aud[:6]}…{expected_aud[-4:]}(len={len(expected_aud)})" if len(expected_aud) > 10 else "EMPTY"
            log.warning(
                "GOOGLE_AUTH_FAILURE_STAGE=%s exc_type=%s token_aud=%s expected_aud=%s",
                stage,
                type(exc).__name__,
                aud_fp,
                exp_fp,
            )
            raise AuthError("Google 토큰 검증에 실패했습니다.") from exc

        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or nonce != expected_nonce:
            log.warning("GOOGLE_AUTH_FAILURE_STAGE=NONCE_MISMATCH")
            raise AuthError("Google 토큰 nonce 검증에 실패했습니다.")

        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            log.warning("GOOGLE_AUTH_FAILURE_STAGE=EMAIL_MISSING")
            raise AuthError("Google 계정 이메일을 확인할 수 없습니다.")
        email_verified = bool(claims.get("email_verified"))
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            log.warning("GOOGLE_AUTH_FAILURE_STAGE=SUBJECT_MISSING")
            raise AuthError("Google 계정 식별자를 확인할 수 없습니다.")

        return GoogleIdentity(
            subject=subject,
            email=email.strip().lower(),
            email_verified=email_verified,
        )


def _safe_next(next_path: str | None) -> str | None:
    if not next_path:
        return None
    cleaned = next_path.strip()
    if not cleaned.startswith("/") or cleaned.startswith("//"):
        return None
    return cleaned[:512]


def upsert_google_identity(
    session: Session,
    *,
    user_id: int,
    subject: str,
    email: str,
) -> UserExternalIdentity:
    existing = session.scalar(
        select(UserExternalIdentity).where(
            UserExternalIdentity.provider == PROVIDER_GOOGLE,
            UserExternalIdentity.provider_subject == subject,
        )
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        if int(existing.user_id) != int(user_id):
            raise AuthError("이 Google 계정은 다른 사용자에 이미 연결되어 있습니다.")
        existing.email_snapshot = email
        existing.last_login_at = now
        return existing
    row = UserExternalIdentity(
        user_id=user_id,
        provider=PROVIDER_GOOGLE,
        provider_subject=subject,
        email_snapshot=email,
        last_login_at=now,
    )
    session.add(row)
    session.flush()
    return row
