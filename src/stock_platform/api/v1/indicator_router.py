from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/indicator", tags=["indicator"])

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/screen")
def screen() -> dict[str, str]:
    return {"status": "ready", "message": "Connect IndicatorRepository and ScreenerService here."}
