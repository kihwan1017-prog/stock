"""Kiwoom execution environment — credential is_mock SoT (Option C).

Market/WS는 settings.kiwoom_use_mock(shared) 유지.
Execution host만 UBA credential 기준으로 결정한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    resolve_kiwoom_is_mock,
)
from stock_platform.common.settings import Settings, get_settings

KIWOOM_REAL_EXECUTION_BASE = "https://api.kiwoom.com"
KIWOOM_MOCK_EXECUTION_BASE = "https://mockapi.kiwoom.com"


def kiwoom_execution_base_url(*, is_mock: bool) -> str:
    return KIWOOM_MOCK_EXECUTION_BASE if is_mock else KIWOOM_REAL_EXECUTION_BASE


def resolve_kiwoom_execution_is_mock(
    payload: dict[str, Any] | None,
    *,
    settings: Settings | None = None,
) -> bool:
    """explicit payload is_mock > legacy settings.kiwoom_use_mock."""

    s = settings or get_settings()
    return resolve_kiwoom_is_mock(
        payload,
        legacy_kiwoom_use_mock=bool(s.kiwoom_use_mock),
    )


def payload_has_explicit_is_mock(payload: dict[str, Any] | None) -> bool:
    return bool(
        payload
        and "is_mock" in payload
        and payload.get("is_mock") is not None
    )


def kiwoom_uba_execution_is_mock(
    session: Session,
    user_broker_account_id: int,
) -> tuple[bool | None, bool]:
    """(execution_is_mock, explicit_is_mock_in_payload).

    credential 없음/미검증 → (None, False) — LIVE fail-closed.
    """

    from stock_platform.broker.credential_adapter_factory import (
        resolve_uba_credential,
    )

    try:
        resolved = resolve_uba_credential(
            session,
            int(user_broker_account_id),
            expected_broker="KIWOOM",
        )
    except BrokerCredentialVaultError:
        return None, False
    payload = resolved.payload
    explicit = payload_has_explicit_is_mock(payload)
    return resolve_kiwoom_execution_is_mock(payload), explicit


def kiwoom_uba_has_explicit_real_execution(
    session: Session,
    user_broker_account_id: int,
) -> bool:
    """UBA credential에 explicit is_mock=false — global mock LIVE gate 우회."""

    is_mock, explicit = kiwoom_uba_execution_is_mock(
        session, user_broker_account_id
    )
    return explicit and is_mock is False


def kiwoom_global_mock_blocks_live_execution(
    session: Session | None,
    *,
    user_broker_account_id: int | None,
    uses_system_shared_credential: bool = False,
    credential_ref: str | None = None,
) -> bool:
    """global kiwoom_use_mock + LIVE flags가 이 dispatch를 막아야 하면 True."""

    from stock_platform.broker.credential_adapter_factory import (
        is_system_shared_credential_ref,
    )

    s = get_settings()
    if not (
        s.global_live_order_enabled
        and s.kiwoom_live_order_enabled
        and s.kiwoom_use_mock
    ):
        return False

    if uses_system_shared_credential or is_system_shared_credential_ref(
        credential_ref
    ):
        return True

    if user_broker_account_id is None or session is None:
        return True

    if kiwoom_uba_has_explicit_real_execution(
        session, int(user_broker_account_id)
    ):
        return False

    # legacy(missing is_mock) 또는 mock credential → global mock 기준 fail-closed
    is_mock, _explicit = kiwoom_uba_execution_is_mock(
        session, int(user_broker_account_id)
    )
    if is_mock is None:
        return True
    return bool(is_mock)


def kiwoom_execution_real_env_pass(
    *,
    credential_is_mock: bool | None,
) -> bool:
    """Preflight KIWOOM_REAL_ENV — execution credential만 (global mock 제외)."""

    return credential_is_mock is False


def kiwoom_market_env_is_mock(*, settings: Settings | None = None) -> bool:
    """Shared market/WS host — global kiwoom_use_mock."""

    s = settings or get_settings()
    return bool(s.kiwoom_use_mock)
