from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from stock_platform.realtime.session_models import (
    TradingSessionPhase,
)
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)


router = APIRouter(
    prefix="/api/v1/realtime-sessions",
    tags=["Realtime Sessions"],
)


@router.post("/start-scheduler")
def start_realtime_session_scheduler():
    if realtime_trading_scheduler.scheduler.running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Realtime scheduler is already running",
        )

    realtime_trading_scheduler.start()

    return {
        "running": True,
        "jobs": [
            {
                "id": job.id,
                "next_run_time": job.next_run_time,
            }
            for job in (
                realtime_trading_scheduler
                .scheduler.get_jobs()
            )
        ],
    }


@router.post("/stop-scheduler")
async def stop_realtime_session_scheduler():
    await realtime_trading_scheduler.shutdown()
    return {"running": False}


@router.post("/run-now/{phase}")
async def run_session_phase_now(
    phase: TradingSessionPhase,
):
    return await (
        realtime_trading_scheduler.run_phase_now(
            phase
        )
    )


@router.get("/status")
def get_realtime_session_status():
    scheduler = (
        realtime_trading_scheduler.scheduler
    )

    return {
        "running": scheduler.running,
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time,
            }
            for job in scheduler.get_jobs()
        ],
    }
