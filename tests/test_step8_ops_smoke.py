"""STEP8 연동 스모크 — 문서 CMS + OpenAPI + (가능 시) audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.operation.document_cms_service import DocumentCmsService


@pytest.mark.integration
def test_document_cms_service_lists_and_reads() -> None:
    service = DocumentCmsService()
    items = service.list_documents()
    assert any(i.slug == "manual/관리자매뉴얼" for i in items)
    doc = service.get_document("manual/관리자매뉴얼")
    assert "JWT" in doc.content or "권한" in doc.content


@pytest.mark.integration
def test_openapi_includes_docs_and_audit() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json().get("paths", {})
    assert "/api/v1/docs" in paths
    assert "/api/v1/audit/events" in paths
    assert "/api/v1/auth/login" in paths


@pytest.mark.integration
def test_health_endpoint_alive() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
