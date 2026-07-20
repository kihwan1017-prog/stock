"""STEP65 — 계좌 마스킹·소유권·API 계약 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
    assert_paper_account_access,
    assert_trading_account_access,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.trading.account_masking import (
    hash_account_ref,
    mask_account_number,
)


def test_mask_account_number_hides_prefix() -> None:
    assert mask_account_number("1234567890") == "******7890"
    assert mask_account_number("12") == "****"
    assert mask_account_number(None) is None
    assert mask_account_number("  11-22-3344  ") == "****3344"


def test_hash_account_ref_stable_and_not_plaintext() -> None:
    digest = hash_account_ref("1234-5678")
    assert len(digest) == 64
    assert "1234" not in digest
    assert digest == hash_account_ref("12345678")


def test_user_accounts_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/accounts" in paths
    assert "/api/v1/user/accounts/{account_id}" in paths
    assert "/api/v1/user/accounts/{account_id}/set-default" in paths
    assert "/api/v1/user/accounts/{account_id}/connect" in paths
    assert "/api/v1/user/accounts/{account_id}/disconnect" in paths
    assert "/api/v1/user/accounts/{account_id}/sync" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_user_accounts_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/accounts").status_code == 401
    assert (
        client.post(
            "/api/v1/user/accounts",
            json={"account_type": "PAPER", "account_name": "x"},
        ).status_code
        == 401
    )


def _user(user_id: int, *, admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}",
        roles=["admin"] if admin else ["operator"],
        permissions=["trading:read", "trading:write"],
    )


def test_assert_paper_account_access_idor() -> None:
    session = MagicMock()
    paper = MagicMock()
    paper.user_id = 10
    paper.account_id = 1

    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _session: repo,
        )
        with pytest.raises(HTTPException) as exc:
            assert_paper_account_access(_user(99), 1, session)
        assert exc.value.status_code == 403


def test_assert_paper_account_access_owner_ok() -> None:
    session = MagicMock()
    paper = MagicMock()
    paper.user_id = 10
    paper.account_id = 1

    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _session: repo,
        )
        result = assert_paper_account_access(_user(10), 1, session)
        assert result is paper


def test_assert_trading_account_access_blocks_foreign() -> None:
    session = MagicMock()
    paper = MagicMock()
    paper.user_id = 2

    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _session: repo,
        )
        with pytest.raises(HTTPException) as exc:
            assert_trading_account_access(_user(1), 99, session)
        assert exc.value.status_code == 403


def test_assert_broker_account_access_idor() -> None:
    session = MagicMock()
    row = MagicMock()
    row.user_id = 5
    session.get.return_value = row
    with pytest.raises(HTTPException) as exc:
        assert_broker_account_access(_user(7), 1, session)
    assert exc.value.status_code == 403


def test_user_account_view_never_exposes_secret_fields() -> None:
    from stock_platform.trading.user_account_service import UserAccountView
    from datetime import datetime, timezone

    view = UserAccountView(
        account_id=1,
        user_id=3,
        account_type="KIWOOM",
        broker_code="KIWOOM",
        account_name="내 키움",
        masked_account_number="******7890",
        currency_code="KRW",
        is_default=True,
        is_active=True,
        connection_status="CONNECTED",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    payload = view.as_dict()
    for forbidden in (
        "account_number",
        "password",
        "secret",
        "access_token",
        "client_secret",
        "account_ref_hash",
    ):
        assert forbidden not in payload
