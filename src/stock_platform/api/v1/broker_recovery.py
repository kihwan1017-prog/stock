from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from stock_platform.broker.recovery_runtime import (
    broker_recovery_manager,
)


router = APIRouter(
    prefix="/api/v1/broker/recovery",
    tags=["Broker Recovery"],
)


@router.post("/run")
async def run_broker_recovery():
    try:
        return await broker_recovery_manager.recover()
    except (
        ValueError,
        RuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/status")
def get_broker_recovery_status():
    return broker_recovery_manager.status()
