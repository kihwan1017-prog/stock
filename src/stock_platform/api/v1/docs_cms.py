"""읽기 전용 문서 CMS API — 저장소 Markdown 목록/본문."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_any_permission,
)
from stock_platform.operation.document_cms_service import (
    DocumentCmsService,
)


router = APIRouter(
    prefix="/api/v1/docs",
    tags=["Document CMS"],
)


def _service() -> DocumentCmsService:
    return DocumentCmsService()


@router.get("")
def list_documents(
    _: AuthenticatedUser = Depends(
        require_any_permission(
            "system:read",
            "menu:docs",
            "audit:read",
        )
    ),
    service: DocumentCmsService = Depends(_service),
):
    items = service.list_documents()
    return {
        "items": [
            {
                "slug": item.slug,
                "title": item.title,
                "category": item.category,
                "path": item.path,
                "size_bytes": item.size_bytes,
            }
            for item in items
        ],
        "total": len(items),
    }


@router.get("/{slug:path}")
def get_document(
    slug: str,
    _: AuthenticatedUser = Depends(
        require_any_permission(
            "system:read",
            "menu:docs",
            "audit:read",
        )
    ),
    service: DocumentCmsService = Depends(_service),
):
    doc = service.get_document(slug)
    return {
        "slug": doc.slug,
        "title": doc.title,
        "category": doc.category,
        "path": doc.path,
        "content": doc.content,
    }
