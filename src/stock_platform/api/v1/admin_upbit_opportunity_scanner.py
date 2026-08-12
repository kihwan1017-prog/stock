"""Admin UPBIT Opportunity Scanner API — Alert-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from stock_platform.api.deps_admin import require_admin
from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
    upbit_opportunity_scanner_scheduler,
)


router = APIRouter(
    prefix="/api/v1/admin/upbit/opportunity-scanner",
    tags=["Admin Upbit Opportunity Scanner"],
    dependencies=[Depends(require_admin)],
)


class ScannerRunRequest(BaseModel):
    notify: bool = True
    force_ai: bool = False


@router.get("/status")
def scanner_status() -> dict:
    return upbit_opportunity_scanner_scheduler.status()


@router.post("/run")
async def scanner_run_once(body: ScannerRunRequest | None = None) -> dict:
    """수동 1회 Dry Run — 주문/Runtime/LIVE 변경 없음."""

    req = body or ScannerRunRequest()
    result = await upbit_opportunity_scanner_scheduler.run_once_now(
        notify=bool(req.notify),
        force_ai=bool(req.force_ai),
    )
    return {
        "status": upbit_opportunity_scanner_scheduler.status(),
        "result": result,
    }
