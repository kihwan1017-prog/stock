"""문서 CMS 단위 테스트."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from stock_platform.operation.document_cms_service import (
    DocumentCmsService,
    _REPO_ROOT,
)


def test_list_documents_includes_manuals() -> None:
    items = DocumentCmsService().list_documents()
    assert items
    slugs = {item.slug for item in items}
    assert "manual/운영매뉴얼" in slugs
    assert "manual/관리자매뉴얼" in slugs
    assert any(item.category == "manual" for item in items)


def test_get_document_returns_markdown() -> None:
    doc = DocumentCmsService().get_document("manual/운영매뉴얼")
    assert doc.title
    assert "# 운영 매뉴얼" in doc.content
    assert doc.path.endswith(".md")


def test_path_traversal_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        DocumentCmsService().get_document("../.env")
    assert exc.value.status_code == 400


def test_unknown_document_404() -> None:
    with pytest.raises(HTTPException) as exc:
        DocumentCmsService().get_document("manual/없는문서")
    assert exc.value.status_code == 404


def test_repo_root_points_to_project() -> None:
    assert (_REPO_ROOT / "docs" / "manual").is_dir()
    assert Path(_REPO_ROOT / "src" / "stock_platform").is_dir()
