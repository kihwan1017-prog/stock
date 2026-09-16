"""Kiwoom credential REAL/MOCK verify path — explicit is_mock precedence."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from stock_platform.api.v1.user_broker_credentials import CredentialUpsertRequest
from stock_platform.broker.credential_vault_service import (
    ERR_OWNERSHIP,
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
    _validate_payload,
    kiwoom_oauth_base_url,
    resolve_kiwoom_is_mock,
)
from stock_platform.common.security_mask import redact_mapping


def test_kiwoom_oauth_base_url_mock_and_real() -> None:
    assert kiwoom_oauth_base_url(is_mock=True) == "https://mockapi.kiwoom.com"
    assert kiwoom_oauth_base_url(is_mock=False) == "https://api.kiwoom.com"


def test_resolve_explicit_is_mock_over_legacy() -> None:
    # A/C: explicit false beats global true
    assert (
        resolve_kiwoom_is_mock({"is_mock": False}, legacy_kiwoom_use_mock=True)
        is False
    )
    # B/D: explicit true beats global false
    assert (
        resolve_kiwoom_is_mock({"is_mock": True}, legacy_kiwoom_use_mock=False)
        is True
    )
    # legacy fallback only when missing
    assert (
        resolve_kiwoom_is_mock({}, legacy_kiwoom_use_mock=True) is True
    )
    assert (
        resolve_kiwoom_is_mock(None, legacy_kiwoom_use_mock=False) is False
    )


def test_validate_payload_persists_explicit_is_mock() -> None:
    cleaned = _validate_payload(
        "KIWOOM",
        {
            "app_key": "fake-app",
            "secret_key": "fake-secret",
            "account_number": "1234145",
            "is_mock": False,
        },
    )
    assert cleaned["is_mock"] is False
    assert "fake-secret" in cleaned["secret_key"]


def test_user_request_requires_is_mock_for_kiwoom() -> None:
    with pytest.raises(ValidationError):
        CredentialUpsertRequest(
            app_key="a",
            secret_key="b",
            account_number="c",
        )
    ok = CredentialUpsertRequest(
        app_key="a",
        secret_key="b",
        account_number="c",
        is_mock=False,
    )
    assert ok.as_payload()["is_mock"] is False


def test_user_request_upbit_does_not_require_is_mock() -> None:
    # UPBIT 계약 유지 — is_mock 불필요
    body = CredentialUpsertRequest(access_key="ak", secret_key="sk")
    payload = body.as_payload()
    assert "is_mock" not in payload
    assert payload["access_key"] == "ak"


def _capture_verify_base_url(
    *,
    payload: dict[str, Any],
    settings_use_mock: bool,
) -> str:
    """_verify_kiwoom이 고른 OAuth base_url을 캡처 (실 token 발급 없음)."""

    service = BrokerCredentialVaultService(MagicMock())
    captured: dict[str, Any] = {}

    class _FakeSettings:
        kiwoom_use_mock = settings_use_mock
        kiwoom_http_timeout_seconds = 5.0

    class _FakeTokenClient:
        def __init__(self, config: Any, client: Any = None) -> None:
            captured["base_url"] = config.base_url
            captured["use_mock"] = config.use_mock

        def issue(self) -> None:
            return None

    with (
        patch(
            "stock_platform.common.settings.get_settings",
            return_value=_FakeSettings(),
        ),
        patch(
            "stock_platform.broker.kiwoom.token_client.KiwoomTokenClient",
            _FakeTokenClient,
        ),
    ):
        service._verify_kiwoom(payload)
    return str(captured["base_url"])


def test_verify_is_mock_true_uses_mockapi() -> None:
    url = _capture_verify_base_url(
        payload={
            "app_key": "fake",
            "secret_key": "fake",
            "account_number": "1",
            "is_mock": True,
        },
        settings_use_mock=False,
    )
    assert url == "https://mockapi.kiwoom.com"


def test_verify_is_mock_false_uses_real_api() -> None:
    url = _capture_verify_base_url(
        payload={
            "app_key": "fake",
            "secret_key": "fake",
            "account_number": "1",
            "is_mock": False,
        },
        settings_use_mock=True,
    )
    assert url == "https://api.kiwoom.com"


def test_verify_global_true_explicit_false_uses_real() -> None:
    url = _capture_verify_base_url(
        payload={
            "app_key": "fake",
            "secret_key": "fake",
            "account_number": "1",
            "is_mock": False,
        },
        settings_use_mock=True,
    )
    assert url.startswith("https://api.kiwoom.com")


def test_verify_global_false_explicit_true_uses_mock() -> None:
    url = _capture_verify_base_url(
        payload={
            "app_key": "fake",
            "secret_key": "fake",
            "account_number": "1",
            "is_mock": True,
        },
        settings_use_mock=False,
    )
    assert url.startswith("https://mockapi.kiwoom.com")


def test_status_as_dict_has_no_secrets() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.broker_code = "KIWOOM"
    session.get.return_value = uba
    session.scalars.return_value.first.return_value = None
    view = BrokerCredentialVaultService(session).status(1381)
    data = view.as_dict()
    blob = str(data)
    assert "secret" not in blob.lower() or "secret" not in "".join(
        k for k in data if "secret" in k.lower()
    )
    for banned in ("app_key", "secret_key", "access_key"):
        assert banned not in data
    redacted = redact_mapping(
        {"app_key": "REALSECRET", "secret_key": "TOPSECRET"}
    )
    assert "REALSECRET" not in str(redacted)
    assert "TOPSECRET" not in str(redacted)


def test_ownership_blocks_other_user() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.user_id = 61
    uba.is_active = True
    session.get.return_value = uba
    service = BrokerCredentialVaultService(session)
    with pytest.raises(BrokerCredentialVaultError) as exc:
        service.require_owned_uba(
            user_broker_account_id=1381,
            owner_user_id=999,
        )
    assert exc.value.code == ERR_OWNERSHIP


def test_upbit_validate_payload_unchanged() -> None:
    cleaned = _validate_payload(
        "UPBIT",
        {"access_key": "ak", "secret_key": "sk"},
    )
    assert cleaned == {"access_key": "ak", "secret_key": "sk"}
    assert "is_mock" not in cleaned
