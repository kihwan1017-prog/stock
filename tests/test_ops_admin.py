from __future__ import annotations


def test_ops_and_dart_routes_registered() -> None:
    from stock_platform.api.main import app
    from stock_platform.api.router import (
        collect_duplicate_operation_ids,
    )

    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/ops/db/status" in paths
    assert "/api/v1/ops/db/migration-status" in paths
    assert "/api/v1/ops/db/tables" in paths
    assert "/api/v1/ops/backup/status" in paths
    assert "/api/v1/dart/disclosures" in paths
    assert "/api/v1/dart/corps" in paths
    assert "/api/v1/ollama/status" in paths
    assert "/api/v1/jobs/history" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_ops_db_status_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from stock_platform.api.main import app

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/ops/db/status").status_code == 401
    assert (
        client.get("/api/v1/ops/db/migration-status").status_code
        == 401
    )
    assert client.get("/api/v1/ops/backup/status").status_code == 401


def test_job_history_returns_items_dict() -> None:
    from fastapi.testclient import TestClient

    from stock_platform.api.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/jobs/history", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert isinstance(payload["items"], list)
