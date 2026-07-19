from __future__ import annotations

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.auth.rbac_service import RoleView


def test_authenticated_user_permission_helpers() -> None:
    admin = AuthenticatedUser(
        user_id=1,
        username="admin",
        roles=["admin"],
        permissions=[],
    )
    assert admin.has_permission("users:delete")
    assert admin.has_any_permission("roles:read")

    operator = AuthenticatedUser(
        user_id=2,
        username="ops",
        roles=["operator"],
        permissions=["users:read", "ops:execute"],
    )
    assert operator.has_permission("users:read")
    assert not operator.has_permission("users:delete")
    assert operator.has_any_permission("ops:execute", "users:delete")

    viewer = AuthenticatedUser(
        user_id=3,
        username="view",
        roles=["viewer"],
        permissions=["menu:dashboard", "trading:read"],
    )
    assert viewer.has_permission("menu:dashboard")
    assert not viewer.has_any_permission("users:read")


def test_rbac_service_role_view_dict() -> None:
    view = RoleView(
        id=1,
        code="viewer",
        name="조회자",
        description="read only",
        is_system=True,
        permissions=["menu:dashboard", "trading:read"],
    )
    assert view.code == "viewer"
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
