"""Deprecated alias router for STEP33 indicator stub.

표준 지표 API는 `/api/v1/indicators` (`indicators.py`)를 사용한다.
호환성을 위해 `/api/v1/indicator` 경로를 유지한다.
"""

from fastapi import APIRouter

router = APIRouter(
    prefix="/api/v1/indicator",
    tags=["indicator-deprecated"],
)


@router.get("/health", deprecated=True)
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "deprecated": True,
        "preferred": "/api/v1/indicators",
    }


@router.get("/screen", deprecated=True)
def screen() -> dict[str, str]:
    return {
        "status": "ready",
        "deprecated": True,
        "preferred": "/api/v1/indicators",
        "message": (
            "Connect IndicatorRepository and ScreenerService "
            "via /api/v1/indicators"
        ),
    }
