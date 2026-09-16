"""STEP73 — My Profile / Security / Sessions / Connections 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.auth.profile_service import (
    UserProfileError,
    UserProfileService,
)
from stock_platform.common.security_mask import mask_chat_id, mask_email, mask_ip


def test_user_profile_openapi() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/profile" in paths
    assert "/api/v1/user/profile/change-password" in paths
    assert "/api/v1/user/profile/sessions" in paths
    assert "/api/v1/user/profile/sessions/{session_id}" in paths
    assert "/api/v1/user/profile/accounts-summary" in paths
    assert "/api/v1/user/profile/connections" in paths
    assert "/api/v1/user/profile/connections/telegram" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_user_profile_requires_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/profile").status_code == 401
    assert client.patch("/api/v1/user/profile", json={}).status_code == 401
    assert (
        client.post(
            "/api/v1/user/profile/change-password",
            json={
                "current_password": "x",
                "new_password": "Newpass1!",
                "new_password_confirmation": "Newpass1!",
            },
        ).status_code
        == 401
    )
    assert client.get("/api/v1/user/profile/sessions").status_code == 401
    assert client.get("/api/v1/user/profile/connections").status_code == 401


def test_masking_helpers() -> None:
    assert mask_email("kihwan@example.com").startswith("ki")
    assert "***" in mask_email("kihwan@example.com")
    assert mask_ip("121.123.45.67") == "121.***.***.67"
    assert "***" in mask_chat_id("123456789")


def test_get_profile_masks_and_hides_secrets() -> None:
    service = UserProfileService(MagicMock())
    user = SimpleNamespace(
        user_id=10,
        username="alice",
        email="alice@example.com",
        display_name="Alice",
        nickname="ali",
        profile_image_url=None,
        bio=None,
        locale="KO",
        is_active=True,
        email_verified=True,
        last_login_at=None,
        password_changed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        password_hash="SHOULD_NOT_APPEAR",
    )
    service._repo = MagicMock()
    service._repo.get_by_id.return_value = user
    payload = service.get_profile(10)
    assert payload["user_id"] == 10
    assert payload["email"] == mask_email("alice@example.com")
    assert payload["email_full"] == "alice@example.com"
    assert "password" not in str(payload).lower() or "password_changed" in str(
        payload
    )
    assert "password_hash" not in payload
    assert payload["two_factor_enabled"] is False


def test_update_profile_blocks_role_fields() -> None:
    service = UserProfileService(MagicMock())
    service._repo = MagicMock()
    service._repo.get_by_id.return_value = SimpleNamespace(
        user_id=1,
        is_active=True,
        display_name="A",
        nickname=None,
        profile_image_url=None,
        bio=None,
        locale="KO",
        email="a@b.com",
        username="a",
        email_verified=False,
        last_login_at=None,
        password_changed_at=None,
        created_at=None,
        updated_at=None,
    )
    with pytest.raises(UserProfileError, match="수정할 수 없는"):
        service.update_profile(1, {"roles": ["admin"]})


def test_update_profile_blocks_html() -> None:
    service = UserProfileService(MagicMock())
    service._repo = MagicMock()
    service._repo.get_by_id.return_value = SimpleNamespace(
        user_id=1,
        is_active=True,
        display_name="A",
        nickname=None,
        profile_image_url=None,
        bio=None,
        locale="KO",
        email=None,
        username="a",
        email_verified=False,
        last_login_at=None,
        password_changed_at=None,
        created_at=None,
        updated_at=None,
    )
    with pytest.raises(UserProfileError, match="HTML"):
        service.update_profile(1, {"display_name": "<script>x</script>"})


def test_password_confirmation_and_policy() -> None:
    service = UserProfileService(MagicMock())
    service._repo = MagicMock()
    service._repo.get_by_id.return_value = SimpleNamespace(
        user_id=1,
        is_active=True,
        email="user@example.com",
        password_hash="hash",
    )
    with pytest.raises(UserProfileError, match="확인"):
        service.change_password(
            1,
            current_password="old",
            new_password="Newpass1!",
            new_password_confirmation="Other1!",
        )
    with pytest.raises(UserProfileError, match="단순한|최소|2종류"):
        service.change_password(
            1,
            current_password="old",
            new_password="password",
            new_password_confirmation="password",
        )


def test_revoke_session_other_user_not_found() -> None:
    service = UserProfileService(MagicMock())
    service._repo = MagicMock()
    service._repo.get_refresh_by_public_id.return_value = None
    with pytest.raises(UserProfileError, match="찾을 수 없"):
        service.revoke_session(1, "missing-id")


def test_list_sessions_masks_ip_and_hides_hash() -> None:
    service = UserProfileService(MagicMock())
    service._repo = MagicMock()
    service._repo.list_active_sessions.return_value = [
        SimpleNamespace(
            session_public_id="pub-1",
            device_name="Windows · Chrome",
            browser_name="Chrome",
            operating_system="Windows",
            ip_address="10.20.30.40",
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
            expires_at=datetime.now(timezone.utc),
            jti="jti-1",
            token_hash="SECRET",
        )
    ]
    service._jti_from_refresh = MagicMock(return_value="jti-1")
    result = service.list_sessions(1, current_refresh_token="x")
    item = result["items"][0]
    assert item["session_id"] == "pub-1"
    assert item["is_current"] is True
    assert item["ip_address_masked"] == "10.***.***.40"
    assert "token_hash" not in item
    assert "jti" not in item


def test_accounts_summary_uses_owned_only() -> None:
    service = UserProfileService(MagicMock())
    service._accounts = MagicMock()
    service._accounts.list_accounts.return_value = [
        SimpleNamespace(
            account_type="PAPER",
            broker_code="PAPER",
            account_id=1,
            is_default=True,
            connection_status="N/A",
        ),
        SimpleNamespace(
            account_type="KIWOOM",
            broker_code="KIWOOM",
            account_id=2,
            is_default=False,
            connection_status="CONNECTED",
        ),
    ]
    summary = service.accounts_summary(9)
    assert summary["paper_accounts"]["count"] == 1
    assert summary["kiwoom_accounts"]["connected"] is True
    assert summary["total_accounts"] == 2
    service._accounts.list_accounts.assert_called_once_with(user_id=9)
