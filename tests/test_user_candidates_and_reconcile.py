"""USER candidates 읽기 wrapper 및 paper-orders account 필터."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stock_platform.api.main import app


def test_user_candidates_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.get("/api/v1/user/candidates/latest/KRX").status_code == 401
    )
    assert (
        client.get(
            "/api/v1/user/candidates/top/KRX",
            params={"as_of_date": "2026-07-01"},
        ).status_code
        == 401
    )


def test_upbit_reconcile_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.post(
            "/api/v1/broker/upbit/account/reconcile-orders"
        ).status_code
        == 401
    )


def test_user_candidates_paths_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/candidates/latest/{exchange_code}" in paths
    assert "/api/v1/user/candidates/top/{exchange_code}" in paths
    assert "/api/v1/broker/upbit/account/reconcile-orders" in paths
