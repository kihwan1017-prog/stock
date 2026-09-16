"""STEP 8-9C-2 — Admin Principal 정합 + UBA 생성."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import select

from stock_platform.auth.deps import (
    ADMIN_API_KEY_PRINCIPAL_USER_ID,
    AuthenticatedUser,
    admin_actor_label,
    require_admin,
)
from stock_platform.auth.jwt_service import JwtTokenService
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.trading.account_masking import hash_account_ref
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.admin_broker_account_service import (
    AdminBrokerAccountService,
)
from stock_platform.trading.user_account_service import UserAccountError


def _patch_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "stock_platform.api.lifecycle.application_lifecycle.startup",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "stock_platform.api.lifecycle.application_lifecycle.shutdown",
        AsyncMock(),
    )


def _admin_token(user_id: int = 7, username: str = "admin") -> str:
    settings = get_settings()
    token, _ = JwtTokenService(settings).create_access_token(
        user_id=user_id, username=username, roles=["admin"]
    )
    return token


def _user_token(user_id: int = 8, username: str = "member") -> str:
    settings = get_settings()
    token, _ = JwtTokenService(settings).create_access_token(
        user_id=user_id, username=username, roles=["user"]
    )
    return token


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _patch_lifecycle(monkeypatch)
    from stock_platform.api.main import create_app

    return TestClient(create_app())


def _amount_int(value: object) -> int:
    return int(float(str(value)))


def test_require_admin_returns_authenticated_user_principal() -> None:
    settings = get_settings()
    session = get_session_factory()()
    try:
        principal = require_admin(
            x_admin_api_key=None,
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=_admin_token()
            ),
            session=session,
            settings=settings,
        )
    finally:
        session.close()
    assert isinstance(principal, AuthenticatedUser)
    assert principal.user_id == 7
    assert principal.is_admin
    assert admin_actor_label(principal) == "admin:7"


def test_admin_actor_label_fail_closed_on_bad_principal() -> None:
    with pytest.raises(HTTPException) as exc:
        admin_actor_label("JWT:admin")  # type: ignore[arg-type]
    assert exc.value.status_code == 401


def test_admin_api_key_principal_has_sentinel_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_api_key", "secret-admin-key")
    principal = require_admin(
        x_admin_api_key="secret-admin-key",
        credentials=None,
        session=None,  # type: ignore[arg-type]
        settings=settings,
    )
    assert isinstance(principal, AuthenticatedUser)
    assert principal.user_id == ADMIN_API_KEY_PRINCIPAL_USER_ID
    assert principal.username == "ADMIN_KEY"
    assert principal.is_admin
    assert admin_actor_label(principal) == "admin:0"


def test_uba_create_success_and_actor_owner_separation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _admin_token(user_id=7)
    account_number = "MAIN-8-9C2"
    with _client(monkeypatch) as client:
        r = client.post(
            "/api/v1/admin/broker-accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "owner_user_id": 7,
                "broker_code": "UPBIT",
                "account_alias": "Upbit",
                "account_number": account_number,
                "apply_recommended_risk": True,
                "is_default": True,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["user_id"] == 7
        assert body["broker_code"] == "UPBIT"
        assert body["is_active"] is True
        assert body["live_order_enabled"] is False
        assert body["live_armed"] is False
        assert body["created_by"] == "admin:7"
        assert body["created_by"] != f"owner:{body['user_id']}"
        assert body["recommended_risk_applied"] is True
        risk = body.get("risk") or {}
        assert _amount_int(risk.get("max_order_amount")) == 5000
        assert int(risk.get("max_open_orders")) == 1
        assert int(risk.get("daily_order_limit")) == 1
        cred = body.get("credential") or {}
        assert cred.get("registered") is False
        uba_id = int(body["user_broker_account_id"])

        dup = client.post(
            "/api/v1/admin/broker-accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "owner_user_id": 7,
                "broker_code": "UPBIT",
                "account_alias": "Upbit",
                "account_number": account_number,
                "apply_recommended_risk": True,
                "is_default": True,
            },
        )
        assert dup.status_code == 409, dup.text

        deleted = client.delete(
            f"/api/v1/admin/broker-accounts/{uba_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deleted.status_code == 200, deleted.text


def test_uba_create_forbidden_for_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as client:
        r = client.post(
            "/api/v1/admin/broker-accounts",
            headers={"Authorization": f"Bearer {_user_token()}"},
            json={
                "owner_user_id": 7,
                "broker_code": "UPBIT",
                "account_alias": "Upbit",
                "account_number": "MAIN-FORBIDDEN",
            },
        )
        assert r.status_code == 403


def test_uba_create_unauthorized_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as client:
        r = client.post(
            "/api/v1/admin/broker-accounts",
            json={
                "owner_user_id": 7,
                "broker_code": "UPBIT",
                "account_alias": "Upbit",
                "account_number": "MAIN-UNAUTH",
            },
        )
        assert r.status_code == 401


def test_uba_create_owner_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as client:
        r = client.post(
            "/api/v1/admin/broker-accounts",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "owner_user_id": 9_999_999,
                "broker_code": "UPBIT",
                "account_alias": "Upbit",
                "account_number": "MAIN-NO-OWNER",
            },
        )
        assert r.status_code == 404


def test_risk_failure_rolls_back_uba(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = get_session_factory()()
    account_number = "MAIN-ROLLBACK-TEST"
    ref_hash = hash_account_ref(account_number)

    def _boom(*_a, **_k):
        raise RuntimeError("risk upsert failed")

    monkeypatch.setattr(
        "stock_platform.trading.admin_broker_account_service"
        ".UserRiskSettingService.upsert_account",
        _boom,
    )
    try:
        with pytest.raises(UserAccountError):
            AdminBrokerAccountService(session).create_account(
                owner_user_id=7,
                broker_code="UPBIT",
                account_alias="rollback",
                account_number=account_number,
                apply_recommended_risk=True,
                is_default=False,
                actor="admin:7",
            )
        left = session.scalar(
            select(UserBrokerAccount).where(
                UserBrokerAccount.user_id == 7,
                UserBrokerAccount.broker_code == "UPBIT",
                UserBrokerAccount.account_ref_hash == ref_hash,
            )
        )
        assert left is None
    finally:
        session.rollback()
        session.close()


def test_admin_readiness_accepts_principal_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """다른 Admin API 회귀 — require_admin Principal 로도 200."""

    with _client(monkeypatch) as client:
        r = client.get(
            "/api/v1/admin/live-ops/readiness",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
        assert r.status_code == 200, r.text


def test_create_router_does_not_attributeerror_on_str_principal() -> None:
    """문자열 Principal 이면 500 AttributeError 대신 401."""

    from stock_platform.api.v1 import admin_broker_accounts as mod

    with pytest.raises(HTTPException) as exc:
        mod.admin_actor_label("JWT:admin")  # type: ignore[arg-type]
    assert exc.value.status_code == 401
