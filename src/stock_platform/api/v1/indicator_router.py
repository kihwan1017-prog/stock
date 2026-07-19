"""Deprecated `/api/v1/indicator` alias.

STEP56: 라우터 등록 해제. 본선은 `/api/v1/indicators`.
다음 릴리스에서 파일 삭제 가능.
"""

from fastapi import APIRouter

router = APIRouter(
    prefix="/api/v1/indicator",
    tags=["indicator-deprecated"],
    deprecated=True,
)


@router.get("/health", deprecated=True)
def health() -> dict[str, str]:
    return {
        "status": "gone",
        "deprecated": True,
        "preferred": "/api/v1/indicators",
        "message": "Unregistered in STEP56; use /api/v1/indicators",
    }
