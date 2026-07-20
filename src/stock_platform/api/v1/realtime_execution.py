from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from stock_platform.api.deps_admin import require_admin
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
)


router = APIRouter(
    prefix="/api/v1/realtime-execution",
    tags=["Realtime Execution"],
    dependencies=[Depends(require_admin)],
)


@router.post("/start")
async def start_realtime_execution():
    try:
        return await realtime_execution_runner.start()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/stop")
async def stop_realtime_execution():
    await realtime_execution_runner.stop()
    return {"stopped": True}


@router.get("/status")
def get_realtime_execution_status():
    return realtime_execution_runner.status()


@router.get("/history")
def get_realtime_execution_history():
    return realtime_execution_runner.history()
