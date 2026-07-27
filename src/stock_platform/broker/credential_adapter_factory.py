"""STEP 8-5-2 — Vault Credential → Broker Adapter/Client 빌더."""

from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
    ResolvedBrokerCredential,
)
from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.kiwoom.config import (
    KiwoomBrokerConfig,
    KiwoomOrderConfig,
)
from stock_platform.broker.kiwoom.account_client import KiwoomAccountClient
from stock_platform.broker.kiwoom.auth import KiwoomTokenProvider
from stock_platform.broker.kiwoom.client import KiwoomRestClient
from stock_platform.broker.kiwoom.http_client import (
    KiwoomRestClient as KiwoomOrderRestClient,
)
from stock_platform.broker.kiwoom.rate_limiter import KiwoomRateLimiters
from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient
from stock_platform.broker.upbit.adapter import UpbitBrokerAdapter
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.broker.upbit.private_client import UpbitPrivateClient
from stock_platform.common.settings import get_settings


def parse_user_broker_credential_ref(
    credential_ref: str | None,
) -> int | None:
    if not credential_ref:
        return None
    text = str(credential_ref).strip()
    prefix = "USER_BROKER_ACCOUNT:"
    if not text.upper().startswith(prefix):
        return None
    try:
        return int(text.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def is_system_shared_credential_ref(credential_ref: str | None) -> bool:
    if not credential_ref:
        return False
    return str(credential_ref).strip().upper().startswith("SYSTEM_SHARED:")


def resolve_uba_credential(
    session: Session,
    user_broker_account_id: int,
    *,
    expected_broker: str,
) -> ResolvedBrokerCredential:
    return BrokerCredentialVaultService(session).resolve_for_runtime(
        user_broker_account_id,
        expected_broker=expected_broker,
        require_verified=True,
        touch_last_used=True,
    )


def build_kiwoom_order_config_from_vault(
    resolved: ResolvedBrokerCredential,
) -> KiwoomOrderConfig:
    settings = get_settings()
    payload = resolved.payload
    is_mock = payload.get("is_mock")
    if is_mock is None:
        is_mock = bool(settings.kiwoom_use_mock)
    return KiwoomOrderConfig(
        base_url=(
            "https://mockapi.kiwoom.com"
            if is_mock
            else "https://api.kiwoom.com"
        ),
        app_key=str(payload["app_key"]),
        secret_key=str(payload["secret_key"]),
        use_mock=bool(is_mock),
        live_order_enabled=bool(settings.kiwoom_live_order_enabled),
        timeout_seconds=settings.kiwoom_http_timeout_seconds,
    )


def build_kiwoom_broker_config_from_vault(
    resolved: ResolvedBrokerCredential,
) -> KiwoomBrokerConfig:
    settings = get_settings()
    payload = resolved.payload
    is_mock = payload.get("is_mock")
    if is_mock is None:
        is_mock = bool(settings.kiwoom_use_mock)
    return KiwoomBrokerConfig(
        app_key=str(payload["app_key"]),
        secret_key=str(payload["secret_key"]),
        use_mock=bool(is_mock),
        live_order_enabled=bool(settings.kiwoom_live_order_enabled),
        timeout_seconds=settings.kiwoom_http_timeout_seconds,
        requests_per_second=settings.kiwoom_max_requests_per_second,
    )


def build_kiwoom_adapter_for_uba(
    session: Session,
    user_broker_account_id: int,
) -> KiwoomBrokerAdapter:
    resolved = resolve_uba_credential(
        session, user_broker_account_id, expected_broker="KIWOOM"
    )
    config = build_kiwoom_order_config_from_vault(resolved)
    token_client = KiwoomTokenClient(config)
    rest_client = KiwoomOrderRestClient(
        config=config,
        token_cache=KiwoomTokenCache(token_client),
        rate_limiters=KiwoomRateLimiters(),
    )
    return KiwoomBrokerAdapter(config=config, rest_client=rest_client)


def build_kiwoom_account_client_for_uba(
    session: Session,
    user_broker_account_id: int,
) -> tuple[KiwoomAccountClient, str]:
    """(client, account_number) — account_number는 Vault payload에서."""

    resolved = resolve_uba_credential(
        session, user_broker_account_id, expected_broker="KIWOOM"
    )
    config = build_kiwoom_broker_config_from_vault(resolved)
    config.validate()
    token_provider = KiwoomTokenProvider(config=config)
    rest_client = KiwoomRestClient(
        config=config, token_provider=token_provider
    )
    account_number = str(resolved.payload.get("account_number") or "")
    if not account_number:
        raise BrokerCredentialVaultError(
            "credential_invalid",
            "Kiwoom account_number missing in vault payload",
        )
    return KiwoomAccountClient(rest_client), account_number


def build_upbit_settings_from_vault(
    resolved: ResolvedBrokerCredential,
):
    settings = get_settings()
    payload = resolved.payload
    return settings.model_copy(
        update={
            "upbit_access_key": str(payload["access_key"]),
            "upbit_secret_key": str(payload["secret_key"]),
            # UBA 실계좌는 mock 우회 — 검증된 키로 실호출
            "upbit_use_mock": False,
        }
    )


def build_upbit_adapter_for_uba(
    session: Session,
    user_broker_account_id: int,
) -> UpbitBrokerAdapter:
    resolved = resolve_uba_credential(
        session, user_broker_account_id, expected_broker="UPBIT"
    )
    vault_settings = build_upbit_settings_from_vault(resolved)
    return UpbitBrokerAdapter(
        settings=vault_settings,
        order_client=UpbitOrderRestClient(
            settings=vault_settings,
            user_broker_account_id=int(user_broker_account_id),
        ),
    )


def build_upbit_private_client_for_uba(
    session: Session,
    user_broker_account_id: int,
) -> UpbitPrivateClient:
    resolved = resolve_uba_credential(
        session, user_broker_account_id, expected_broker="UPBIT"
    )
    vault_settings = build_upbit_settings_from_vault(resolved)
    return UpbitPrivateClient(
        settings=vault_settings,
        user_broker_account_id=int(user_broker_account_id),
    )
