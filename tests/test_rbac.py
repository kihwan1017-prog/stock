from __future__ import annotations

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.auth.rbac_service import RoleView
from stock_platform.auth.role_codes import (
    ALLOWED_ROLES,
    has_valid_app_role,
    normalize_role_code,
    normalize_role_codes,
)


def test_allowed_roles_are_admin_and_user_only() -> None:
    assert ALLOWED_ROLES == frozenset({"admin", "user"})


def test_normalize_legacy_role_aliases() -> None:
    assert normalize_role_code("viewer") == "user"
    assert normalize_role_code("operator") == "admin"
    assert normalize_role_code("trader") == "user"
    assert normalize_role_code("ADMIN") == "admin"
    assert normalize_role_codes(["viewer", "operator", "user"]) == [
        "user",
        "admin",
    ]


def test_has_valid_app_role() -> None:
    assert has_valid_app_role(["user"]) is True
    assert has_valid_app_role(["viewer"]) is True
    assert has_valid_app_role(["admin"]) is True
    assert has_valid_app_role([]) is False
    assert has_valid_app_role(["guest"]) is False


def test_authenticated_user_permission_helpers() -> None:
    admin = AuthenticatedUser(
        user_id=1,
        username="admin",
        roles=["admin"],
        permissions=[],
    )
    assert admin.is_admin
    assert admin.has_permission("users:delete")
    assert admin.has_any_permission("roles:read")

    # 레거시 operator 문자열은 admin으로 정규화되어 is_admin=True
    legacy_ops = AuthenticatedUser(
        user_id=2,
        username="ops",
        roles=["operator"],
        permissions=["users:read", "ops:execute"],
    )
    assert legacy_ops.is_admin

    member = AuthenticatedUser(
        user_id=3,
        username="member",
        roles=["user"],
        permissions=["menu:dashboard", "trading:read"],
    )
    assert not member.is_admin
    assert member.has_permission("menu:dashboard")
    assert not member.has_any_permission("users:read")

    legacy_viewer = AuthenticatedUser(
        user_id=4,
        username="view",
        roles=["viewer"],
        permissions=["menu:dashboard", "trading:read"],
    )
    assert not legacy_viewer.is_admin
    assert legacy_viewer.has_permission("menu:dashboard")


def test_rbac_service_role_view_dict() -> None:
    view = RoleView(
        id=1,
        code="user",
        name="일반 사용자",
        description="본인 데이터 관리",
        is_system=True,
        permissions=["menu:dashboard", "trading:read"],
    )
    assert view.code == "user"
    assert "menu:dashboard" in view.permissions


def test_roles_router_registered() -> None:
    from fastapi.testclient import TestClient

    from stock_platform.api.main import app
    from stock_platform.api.router import collect_duplicate_operation_ids

    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/roles" in paths
    assert "/api/v1/roles/permissions" in paths
    assert "/api/v1/roles/{role_id}" in paths
    assert "/api/v1/roles/{role_id}/permissions" in paths
    assert "/api/v1/roles/users/{user_id}" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_roles_require_auth() -> None:
    from fastapi.testclient import TestClient

    from stock_platform.api.main import app

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/roles").status_code == 401
    assert client.get("/api/v1/roles/permissions").status_code == 401
