"""STEP 8-5-2 — UserBrokerAccount Credential Vault Service.

평문 Secret은 메모리에서만 사용하고 DB·API·로그에 남기지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from stock_platform.broker.credential_crypto import (
    KEY_VERSION_V1,
    VaultCryptoError,
    decrypt_payload,
    encrypt_payload,
    vault_available,
)
from stock_platform.broker.credential_entities import (
    BrokerAccountCredentialEntity,
)
from stock_platform.common.security_mask import (
    mask_account_number,
    mask_secret,
)
from stock_platform.trading.account_models import UserBrokerAccount


CREDENTIAL_TYPE_BROKER_API = "BROKER_API"

# 검증·주문 차단용 오류 코드
ERR_CREDENTIAL_MISSING = "credential_missing"
ERR_CREDENTIAL_INACTIVE = "credential_inactive"
ERR_CREDENTIAL_REVOKED = "credential_revoked"
ERR_CREDENTIAL_INVALID = "credential_invalid"
ERR_CREDENTIAL_DECRYPTION_FAILED = "credential_decryption_failed"
ERR_CREDENTIAL_EXPIRED = "credential_expired"
ERR_CREDENTIAL_BROKER_MISMATCH = "credential_broker_mismatch"
ERR_CREDENTIAL_UNVERIFIED = "credential_unverified"
ERR_VAULT_UNAVAILABLE = "vault_unavailable"
ERR_OWNERSHIP = "credential_ownership_denied"


class BrokerCredentialVaultError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ResolvedBrokerCredential:
    """복호화된 런타임 Credential (절대 직렬화·로그 금지)."""

    user_broker_account_id: int
    broker_code: str
    credential_id: int
    key_version: int
    payload: dict[str, Any]
    verification_status: str


@dataclass(frozen=True, slots=True)
class CredentialStatusView:
    user_broker_account_id: int
    broker_code: str
    connected: bool
    is_active: bool
    verification_status: str | None
    masked_identifier: str | None
    key_version: int | None
    last_verified_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None
    verification_message: str | None
    vault_available: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_broker_account_id": self.user_broker_account_id,
            "broker_code": self.broker_code,
            "connected": self.connected,
            "is_active": self.is_active,
            "verification_status": self.verification_status,
            "masked_identifier": self.masked_identifier,
            "key_version": self.key_version,
            "last_verified_at": (
                self.last_verified_at.isoformat()
                if self.last_verified_at
                else None
            ),
            "last_used_at": (
                self.last_used_at.isoformat()
                if self.last_used_at
                else None
            ),
            "revoked_at": (
                self.revoked_at.isoformat()
                if self.revoked_at
                else None
            ),
            "expires_at": (
                self.expires_at.isoformat()
                if self.expires_at
                else None
            ),
            "verification_message": self.verification_message,
            "vault_available": self.vault_available,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mask_identifier(broker_code: str, payload: dict[str, Any]) -> str:
    code = broker_code.upper()
    if code == "KIWOOM":
        app = str(payload.get("app_key") or "")
        acct = str(payload.get("account_number") or "")
        parts = []
        if app:
            parts.append(f"app:{mask_secret(app, visible=4)}")
        if acct:
            parts.append(f"acct:{mask_account_number(acct)}")
        return " | ".join(parts) if parts else "****"
    if code == "UPBIT":
        access = str(payload.get("access_key") or "")
        return f"access:{mask_secret(access, visible=4)}" if access else "****"
    return "****"


def _validate_payload(broker_code: str, payload: dict[str, Any]) -> dict[str, Any]:
    code = broker_code.upper()
    cleaned: dict[str, Any] = {}
    if code == "KIWOOM":
        app_key = str(payload.get("app_key") or "").strip()
        secret_key = str(payload.get("secret_key") or "").strip()
        account_number = str(payload.get("account_number") or "").strip()
        if not app_key or not secret_key or not account_number:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_INVALID,
                "Kiwoom requires app_key, secret_key, account_number",
            )
        cleaned = {
            "app_key": app_key,
            "secret_key": secret_key,
            "account_number": account_number,
        }
        product = str(payload.get("account_product_code") or "").strip()
        if product:
            cleaned["account_product_code"] = product
        if "is_mock" in payload:
            cleaned["is_mock"] = bool(payload.get("is_mock"))
        return cleaned
    if code == "UPBIT":
        access_key = str(payload.get("access_key") or "").strip()
        secret_key = str(payload.get("secret_key") or "").strip()
        if not access_key or not secret_key:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_INVALID,
                "Upbit requires access_key and secret_key",
            )
        return {
            "access_key": access_key,
            "secret_key": secret_key,
        }
    raise BrokerCredentialVaultError(
        ERR_CREDENTIAL_BROKER_MISMATCH,
        f"Unsupported broker_code: {broker_code}",
    )


class BrokerCredentialVaultService:
    """Credential 접근 단일 진입점."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_uba(
        self, user_broker_account_id: int
    ) -> UserBrokerAccount | None:
        return self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )

    def require_owned_uba(
        self,
        *,
        user_broker_account_id: int,
        owner_user_id: int,
    ) -> UserBrokerAccount:
        uba = self.get_uba(user_broker_account_id)
        if uba is None or not uba.is_active:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_MISSING,
                "User broker account not found",
            )
        if int(uba.user_id) != int(owner_user_id):
            raise BrokerCredentialVaultError(
                ERR_OWNERSHIP,
                "Broker account ownership denied",
            )
        return uba

    def get_active_entity(
        self, user_broker_account_id: int
    ) -> BrokerAccountCredentialEntity | None:
        stmt = (
            select(BrokerAccountCredentialEntity)
            .where(
                BrokerAccountCredentialEntity.user_broker_account_id
                == int(user_broker_account_id),
                BrokerAccountCredentialEntity.is_active.is_(True),
                BrokerAccountCredentialEntity.credential_type
                == CREDENTIAL_TYPE_BROKER_API,
            )
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def status(
        self,
        user_broker_account_id: int,
        *,
        broker_code: str | None = None,
    ) -> CredentialStatusView:
        uba = self.get_uba(user_broker_account_id)
        code = (
            broker_code
            or (uba.broker_code if uba else "")
            or ""
        ).upper()
        entity = self.get_active_entity(user_broker_account_id)
        if entity is None:
            return CredentialStatusView(
                user_broker_account_id=int(user_broker_account_id),
                broker_code=code,
                connected=False,
                is_active=False,
                verification_status=None,
                masked_identifier=None,
                key_version=None,
                last_verified_at=None,
                last_used_at=None,
                revoked_at=None,
                expires_at=None,
                verification_message=None,
                vault_available=vault_available(),
            )
        return CredentialStatusView(
            user_broker_account_id=int(user_broker_account_id),
            broker_code=str(entity.broker_code).upper(),
            connected=True,
            is_active=bool(entity.is_active),
            verification_status=entity.verification_status,
            masked_identifier=entity.masked_identifier,
            key_version=int(entity.key_version),
            last_verified_at=entity.last_verified_at,
            last_used_at=entity.last_used_at,
            revoked_at=entity.revoked_at,
            expires_at=entity.expires_at,
            verification_message=entity.verification_message,
            vault_available=vault_available(),
        )

    def upsert(
        self,
        *,
        user_broker_account_id: int,
        owner_user_id: int,
        plaintext: dict[str, Any],
        actor: str,
        replace: bool = False,
    ) -> CredentialStatusView:
        """등록(POST) 또는 교체(PUT). 검증 실패해도 저장 가능(FAILED)."""

        if not vault_available():
            raise BrokerCredentialVaultError(
                ERR_VAULT_UNAVAILABLE,
                "Broker vault master key is not available",
            )
        uba = self.require_owned_uba(
            user_broker_account_id=user_broker_account_id,
            owner_user_id=owner_user_id,
        )
        broker_code = str(uba.broker_code).upper()
        if broker_code not in {"KIWOOM", "UPBIT"}:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_BROKER_MISMATCH,
                "Credential vault supports KIWOOM/UPBIT only",
            )
        cleaned = _validate_payload(broker_code, plaintext)
        existing = self.get_active_entity(user_broker_account_id)
        if existing is not None and not replace:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_INVALID,
                "Active credential already exists; use replace",
            )

        blob = encrypt_payload(cleaned, key_version=KEY_VERSION_V1)
        now = _utcnow()
        if existing is not None:
            existing.is_active = False
            existing.revoked_at = now
            existing.verification_status = "REVOKED"
            existing.updated_by = actor
            existing.updated_at = now

        entity = BrokerAccountCredentialEntity(
            user_broker_account_id=int(user_broker_account_id),
            broker_code=broker_code,
            credential_type=CREDENTIAL_TYPE_BROKER_API,
            encrypted_payload=blob.ciphertext_b64,
            nonce_b64=blob.nonce_b64,
            encryption_algorithm=blob.algorithm,
            key_version=blob.key_version,
            payload_version=1,
            is_active=True,
            verification_status="PENDING",
            masked_identifier=_mask_identifier(broker_code, cleaned),
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(entity)
        # 연결 상태: Credential 등록됨 (검증 전)
        uba.connection_status = "CREDENTIAL_PENDING"
        uba.updated_at = now
        self._session.flush()

        # 외부 검증 — 실패해도 저장 유지
        try:
            self._verify_entity(entity, cleaned)
        except BrokerCredentialVaultError as exc:
            entity.verification_status = "FAILED"
            entity.verification_message = exc.message[:500]
            entity.last_verified_at = _utcnow()
            uba.connection_status = "CREDENTIAL_FAILED"
        except Exception as exc:  # noqa: BLE001
            entity.verification_status = "FAILED"
            # Secret 미포함 요약만
            entity.verification_message = (
                f"Verification error: {exc.__class__.__name__}"
            )[:500]
            entity.last_verified_at = _utcnow()
            uba.connection_status = "CREDENTIAL_FAILED"

        self._session.commit()
        return self.status(user_broker_account_id)

    def revoke(
        self,
        *,
        user_broker_account_id: int,
        owner_user_id: int | None,
        actor: str,
        admin: bool = False,
    ) -> CredentialStatusView:
        if not admin:
            if owner_user_id is None:
                raise BrokerCredentialVaultError(
                    ERR_OWNERSHIP,
                    "owner_user_id required",
                )
            uba = self.require_owned_uba(
                user_broker_account_id=user_broker_account_id,
                owner_user_id=owner_user_id,
            )
        else:
            uba = self.get_uba(user_broker_account_id)
            if uba is None:
                raise BrokerCredentialVaultError(
                    ERR_CREDENTIAL_MISSING,
                    "User broker account not found",
                )

        entity = self.get_active_entity(user_broker_account_id)
        now = _utcnow()
        if entity is not None:
            entity.is_active = False
            entity.revoked_at = now
            entity.verification_status = "REVOKED"
            entity.updated_by = actor
            entity.updated_at = now
        uba.connection_status = "DISCONNECTED"
        uba.updated_at = now
        self._session.commit()
        return self.status(user_broker_account_id)

    def verify(
        self,
        *,
        user_broker_account_id: int,
        owner_user_id: int | None,
        actor: str,
        admin: bool = False,
    ) -> CredentialStatusView:
        if not admin:
            if owner_user_id is None:
                raise BrokerCredentialVaultError(
                    ERR_OWNERSHIP,
                    "owner_user_id required",
                )
            uba = self.require_owned_uba(
                user_broker_account_id=user_broker_account_id,
                owner_user_id=owner_user_id,
            )
        else:
            uba = self.get_uba(user_broker_account_id)
            if uba is None:
                raise BrokerCredentialVaultError(
                    ERR_CREDENTIAL_MISSING,
                    "User broker account not found",
                )

        entity = self.get_active_entity(user_broker_account_id)
        if entity is None:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_MISSING,
                "No active credential",
            )
        try:
            payload = self._decrypt_entity(entity)
            self._verify_entity(entity, payload)
            uba.connection_status = "CONNECTED"
        except BrokerCredentialVaultError as exc:
            entity.verification_status = "FAILED"
            entity.verification_message = exc.message[:500]
            entity.last_verified_at = _utcnow()
            entity.updated_by = actor
            uba.connection_status = "CREDENTIAL_FAILED"
            self._session.commit()
            raise
        except VaultCryptoError as exc:
            entity.verification_status = "FAILED"
            entity.verification_message = "Decryption failed"
            entity.last_verified_at = _utcnow()
            entity.updated_by = actor
            uba.connection_status = "CREDENTIAL_FAILED"
            self._session.commit()
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_DECRYPTION_FAILED,
                "Credential decryption failed",
            ) from exc

        entity.updated_by = actor
        self._session.commit()
        return self.status(user_broker_account_id)

    def resolve_for_runtime(
        self,
        user_broker_account_id: int,
        *,
        expected_broker: str | None = None,
        require_verified: bool = True,
        touch_last_used: bool = True,
    ) -> ResolvedBrokerCredential:
        """주문·Recovery용. 실패 시 명확한 코드로 raise."""

        if not vault_available():
            raise BrokerCredentialVaultError(
                ERR_VAULT_UNAVAILABLE,
                "Broker vault master key is not available",
            )
        uba = self.get_uba(user_broker_account_id)
        if uba is None or not uba.is_active:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_MISSING,
                "User broker account not found",
            )
        entity = self.get_active_entity(user_broker_account_id)
        if entity is None:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_MISSING,
                "No active credential for account",
            )
        if entity.revoked_at is not None or not entity.is_active:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_REVOKED,
                "Credential revoked",
            )
        if (
            entity.expires_at is not None
            and entity.expires_at <= _utcnow()
        ):
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_EXPIRED,
                "Credential expired",
            )
        broker = str(entity.broker_code).upper()
        if expected_broker and broker != expected_broker.upper():
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_BROKER_MISMATCH,
                "Credential broker mismatch",
            )
        if uba.broker_code.upper() != broker:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_BROKER_MISMATCH,
                "UBA broker mismatch",
            )
        if require_verified and entity.verification_status != "VERIFIED":
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_UNVERIFIED,
                f"Credential not verified ({entity.verification_status})",
            )
        try:
            payload = self._decrypt_entity(entity)
        except VaultCryptoError as exc:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_DECRYPTION_FAILED,
                "Credential decryption failed",
            ) from exc

        if touch_last_used:
            # 호출자 세션에 row lock을 남기지 않음 — idle-in-transaction hang 방지
            self._touch_last_used_best_effort(
                int(entity.broker_account_credential_id)
            )

        return ResolvedBrokerCredential(
            user_broker_account_id=int(user_broker_account_id),
            broker_code=broker,
            credential_id=int(entity.broker_account_credential_id),
            key_version=int(entity.key_version),
            payload=payload,
            verification_status=entity.verification_status,
        )

    def _touch_last_used_best_effort(self, credential_id: int) -> None:
        """last_used_at를 별도 short txn으로 갱신.

        - SET LOCAL lock_timeout: row lock 대기 무한 hang 방지
        - 호출자 세션과 분리: flush 미커밋으로 credential row를 장시간 잠그지 않음
        - 실패 시 skip (resolve 자체는 성공 유지 — 시세/주문 SoT와 무관 감사 필드)
        """

        bind = self._session.get_bind()
        touch_session = Session(bind=bind)
        try:
            touch_session.execute(text("SET LOCAL lock_timeout = '3000'"))
            touch_session.execute(
                update(BrokerAccountCredentialEntity)
                .where(
                    BrokerAccountCredentialEntity.broker_account_credential_id
                    == int(credential_id)
                )
                .values(last_used_at=_utcnow())
            )
            touch_session.commit()
        except Exception as exc:  # noqa: BLE001
            touch_session.rollback()
            logger.warning(
                "credential_last_used_touch_skipped credential_id=%s error=%s",
                int(credential_id),
                type(exc).__name__,
            )
        finally:
            touch_session.close()

    def assert_live_order_allowed(
        self,
        user_broker_account_id: int,
        *,
        broker_code: str,
    ) -> None:
        """LIVE 주문 저장 전 Credential 가드."""

        self.resolve_for_runtime(
            user_broker_account_id,
            expected_broker=broker_code,
            require_verified=True,
            touch_last_used=False,
        )

    def _decrypt_entity(
        self, entity: BrokerAccountCredentialEntity
    ) -> dict[str, Any]:
        return decrypt_payload(
            ciphertext_b64=entity.encrypted_payload,
            nonce_b64=entity.nonce_b64,
            key_version=int(entity.key_version),
            algorithm=entity.encryption_algorithm,
        )

    def _verify_entity(
        self,
        entity: BrokerAccountCredentialEntity,
        payload: dict[str, Any],
    ) -> None:
        broker = str(entity.broker_code).upper()
        if broker == "KIWOOM":
            self._verify_kiwoom(payload)
        elif broker == "UPBIT":
            self._verify_upbit(payload)
        else:
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_BROKER_MISMATCH,
                "Unsupported broker",
            )
        entity.verification_status = "VERIFIED"
        entity.verification_message = None
        entity.last_verified_at = _utcnow()

    def _verify_kiwoom(self, payload: dict[str, Any]) -> None:
        from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
        from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient
        from stock_platform.common.settings import get_settings

        settings = get_settings()
        is_mock = payload.get("is_mock")
        if is_mock is None:
            is_mock = bool(settings.kiwoom_use_mock)
        config = KiwoomOrderConfig(
            base_url=(
                "https://mockapi.kiwoom.com"
                if is_mock
                else "https://api.kiwoom.com"
            ),
            app_key=str(payload["app_key"]),
            secret_key=str(payload["secret_key"]),
            use_mock=bool(is_mock),
            live_order_enabled=False,
            timeout_seconds=settings.kiwoom_http_timeout_seconds,
        )
        try:
            KiwoomTokenClient(config).issue()
        except Exception as exc:  # noqa: BLE001
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_INVALID,
                f"Kiwoom verification failed: {exc.__class__.__name__}",
            ) from exc

    def _verify_upbit(self, payload: dict[str, Any]) -> None:
        import asyncio

        from stock_platform.broker.upbit.private_client import (
            UpbitPrivateClient,
        )
        from stock_platform.common.settings import get_settings

        settings = get_settings()
        # 검증용 Settings 복사 — env 공용키 미사용
        verify_settings = settings.model_copy(
            update={
                "upbit_access_key": str(payload["access_key"]),
                "upbit_secret_key": str(payload["secret_key"]),
                "upbit_use_mock": False,
            }
        )
        client = UpbitPrivateClient(settings=verify_settings)

        async def _run() -> None:
            try:
                await client.list_accounts()
            finally:
                await client.aclose()

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            from stock_platform.broker.upbit.exceptions import (
                UpbitBanOrBlockError,
                UpbitRateLimitError,
            )

            # Rate Limit/418을 Credential INVALID로 오판하지 않음
            if isinstance(exc, UpbitRateLimitError):
                raise BrokerCredentialVaultError(
                    "upbit_rate_limited",
                    "Upbit rate limited during verify — retry later",
                ) from exc
            if isinstance(exc, UpbitBanOrBlockError):
                raise BrokerCredentialVaultError(
                    "upbit_blocked_418",
                    "Upbit blocked (418) during verify — admin review",
                ) from exc
            raise BrokerCredentialVaultError(
                ERR_CREDENTIAL_INVALID,
                f"Upbit verification failed: {exc.__class__.__name__}",
            ) from exc
