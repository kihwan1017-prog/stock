"""K-CRED — Kiwoom credential/UBA alignment (no secrets · no LIVE)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stock_platform.broker.kiwoom.credential_alignment import (
    assert_kiwoom_real_credential_ready,
    classify_kiwoom_alignment,
    mask_kiwoom_credential_fields,
)


def _uba(
    *,
    uba_id: int = 1381,
    user_id: int = 61,
    active: bool = True,
    connection: str = "DISCONNECTED",
) -> SimpleNamespace:
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=user_id,
        broker_code="KIWOOM",
        is_active=active,
        connection_status=connection,
    )


def _cred(
    *,
    verified: str = "VERIFIED",
    active: bool = True,
    revoked: bool = False,
    masked: str = "KW***12",
) -> SimpleNamespace:
    return SimpleNamespace(
        is_active=active,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
        verification_status=verified,
        masked_identifier=masked,
        last_verified_at=datetime.now(timezone.utc),
    )


def test_a_mock_uba_no_real_credential_mock_ready():
    view = classify_kiwoom_alignment(
        uba=_uba(connection="DISCONNECTED"),
        credential=None,
        kiwoom_use_mock=True,
    )
    assert view.mock_ready is True
    assert view.real_credential_ready is False
    assert "NO_CREDENTIAL_ROW" in view.mismatches


def test_b_real_uba_credential_missing_not_ready():
    view = classify_kiwoom_alignment(
        uba=_uba(connection="DISCONNECTED"),
        credential=None,
        kiwoom_use_mock=False,
    )
    assert view.mock_ready is False
    assert view.real_credential_ready is False
    assert "NO_CREDENTIAL_ROW" in view.mismatches


def test_c_credential_exists_unverified_not_ready():
    view = classify_kiwoom_alignment(
        uba=_uba(connection="CREDENTIAL_PENDING"),
        credential=_cred(verified="PENDING"),
        kiwoom_use_mock=False,
    )
    assert view.real_credential_ready is False
    assert "CREDENTIAL_NOT_VERIFIED" in view.mismatches


def test_d_verified_but_uba_stale_connected_without_cred():
    view = classify_kiwoom_alignment(
        uba=_uba(connection="CONNECTED"),
        credential=None,
        kiwoom_use_mock=False,
    )
    assert "UBA_CONNECTION_STALE" in view.mismatches
    assert view.recommended_connection_status == "DISCONNECTED"
    assert view.real_credential_ready is False


def test_d2_mock_connected_without_cred_flagged():
    view = classify_kiwoom_alignment(
        uba=_uba(uba_id=1381, connection="CONNECTED"),
        credential=None,
        kiwoom_use_mock=True,
    )
    assert "MOCK_CONNECTION_WITHOUT_CREDENTIAL" in view.mismatches
    assert view.mock_ready is True  # mock flag still allows mock path
    assert view.real_credential_ready is False


def test_e_verified_active_connected_pass():
    view = classify_kiwoom_alignment(
        uba=_uba(connection="CONNECTED"),
        credential=_cred(verified="VERIFIED"),
        kiwoom_use_mock=False,
    )
    assert view.real_credential_ready is True
    assert view.mismatches == ()
    assert_kiwoom_real_credential_ready(view)


def test_f_wrong_ownership_uba_missing():
    view = classify_kiwoom_alignment(
        uba=None,
        credential=None,
        kiwoom_use_mock=False,
    )
    assert "UBA_MISSING" in view.mismatches
    with pytest.raises(ValueError, match="KIWOOM_REAL_CREDENTIAL_NOT_READY"):
        assert_kiwoom_real_credential_ready(view)


def test_g_verification_failure_no_connected_ready():
    view = classify_kiwoom_alignment(
        uba=_uba(connection="CREDENTIAL_FAILED"),
        credential=_cred(verified="FAILED"),
        kiwoom_use_mock=False,
    )
    assert view.real_credential_ready is False
    assert view.recommended_connection_status == "CREDENTIAL_FAILED"


def test_h_secrets_not_in_masked_output():
    masked = mask_kiwoom_credential_fields(
        {
            "app_key": "ABCDEFGH1234",
            "secret_key": "SUPERSECRETVALUE",
            "account_alias": "main",
        }
    )
    assert "SUPERSECRET" not in str(masked["secret_key"])
    assert masked["secret_key"].startswith("SU")
    assert masked["app_key"].endswith("34")
    assert masked["account_alias"] == "main"


def test_i_inactive_uba_blocks_real():
    view = classify_kiwoom_alignment(
        uba=_uba(active=False, connection="CONNECTED"),
        credential=_cred(),
        kiwoom_use_mock=False,
    )
    assert view.real_credential_ready is False
    assert "UBA_INACTIVE" in view.mismatches
