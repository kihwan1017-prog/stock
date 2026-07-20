from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from stock_platform.api.deps_admin import require_admin
from stock_platform.brokers.kiwoom.auth import KiwoomTokenManager
from stock_platform.brokers.kiwoom.exceptions import KiwoomError
from stock_platform.common.settings import get_settings


router = APIRouter(
    prefix="/api/v1/kiwoom",
    tags=["Kiwoom"],
    dependencies=[Depends(require_admin)],
)


class KiwoomConfigurationResponse(BaseModel):
    environment: str
    base_url: str
    credentials_configured: bool


class KiwoomTokenTestResponse(BaseModel):
    status: str
    token_type: str
    expires_at: str


@router.get(
    "/configuration",
    response_model=KiwoomConfigurationResponse,
)
def get_kiwoom_configuration() -> KiwoomConfigurationResponse:
    settings = get_settings()

    configured = bool(
        settings.kiwoom_app_key.strip()
        and settings.kiwoom_secret_key.strip()
    )

    return KiwoomConfigurationResponse(
        environment="mock" if settings.kiwoom_use_mock else "real",
        base_url=settings.kiwoom_base_url,
        credentials_configured=configured,
    )


@router.post(
    "/token/test",
    response_model=KiwoomTokenTestResponse,
)
async def test_kiwoom_token() -> KiwoomTokenTestResponse:
    if get_settings().is_production_env:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="token/test is disabled in production",
        )
    try:
        async with KiwoomTokenManager() as manager:
            token = await manager.get_token(force_refresh=True)
    except KiwoomError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return KiwoomTokenTestResponse(
        status="UP",
        token_type=token.token_type,
        expires_at=token.expires_at.isoformat(),
    )
