from __future__ import annotations

from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids


def test_auth_router_registered_without_duplicate_ids() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/signup" in paths
    assert "/api/v1/auth/check-username" in paths
    assert "/api/v1/auth/check-email" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/auth/change-password" in paths
    assert "/api/v1/users" in paths
    assert "/api/v1/users/{user_id}" in paths
    assert "/api/v1/roles" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_me_requires_bearer() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
