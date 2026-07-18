from fastapi import APIRouter

from stock_platform.operation.health_service import (
    SystemHealthService,
)


router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("")
async def health():
    return await SystemHealthService().build()
