"""STEP 8-5-2 — Credential Vault ownership / status / masking."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_platform.broker.credential_adapter_factory import (
    is_system_shared_credential_ref,
    parse_user_broker_credential_ref,
)
from stock_platform.broker.credential_vault_service import (
    ERR_OWNERSHIP,
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.common.security_mask import redact_mapping


def test_parse_user_broker_credential_ref() -> None:
    assert parse_user_broker_credential_ref("USER_BROKER_ACCOUNT:12") == 12
    assert parse_user_broker_credential_ref("SYSTEM_SHARED:KIWOOM") is None
    assert parse_user_broker_credential_ref(None) is None


def test_system_shared_ref_detection() -> None:
    assert is_system_shared_credential_ref("SYSTEM_SHARED:UPBIT")
    assert not is_system_shared_credential_ref("USER_BROKER_ACCOUNT:1")


def test_redact_masks_credential_keys() -> None:
    redacted = redact_mapping(
        {
            "app_key": "ABCDEFGH",
            "access_key": "XYZ12345",
            "encrypted_payload": "cipher-text",
            "credential": "secret-blob",
            "account_number": "1234567890",
        }
    )
    assert "ABCDEFGH" not in str(redacted["app_key"])
    assert "XYZ12345" not in str(redacted["access_key"])
    assert "cipher-text" not in str(redacted["encrypted_payload"])
    assert "1234567890" not in str(redacted["account_number"])


def test_ownership_denied_for_other_user() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.user_id = 10
    uba.is_active = True
    session.get.return_value = uba
    service = BrokerCredentialVaultService(session)
    with pytest.raises(BrokerCredentialVaultError) as exc:
        service.require_owned_uba(
            user_broker_account_id=1,
            owner_user_id=99,
        )
    assert exc.value.code == ERR_OWNERSHIP


def test_status_without_credential() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.broker_code = "KIWOOM"
    session.get.return_value = uba
    session.scalars.return_value.first.return_value = None
    view = BrokerCredentialVaultService(session).status(7)
    assert view.connected is False
    assert view.user_broker_account_id == 7
    assert "secret" not in view.as_dict()
