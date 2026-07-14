from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.disclosure.dart_client import DartClient, DartError
from stock_platform.disclosure.repository import (
    DartDisclosureRepository,
)
from stock_platform.disclosure.service import DartDisclosureService


router = APIRouter(
    prefix="/api/v1/dart",
    tags=["DART"],
)


class DartSyncRequest(BaseModel):
    corp_code: str = Field(min_length=8, max_length=8)
    start_date: date
    end_date: date


@router.post("/sync")
async def sync_dart_disclosures(
    request: DartSyncRequest,
    session: Session = Depends(get_db_session),
):
    try:
        async with DartClient() as client:
            service = DartDisclosureService(
                client=client,
                repository=DartDisclosureRepository(session),
            )
            saved_count = await service.sync(
                corp_code=request.corp_code,
                start_date=request.start_date,
                end_date=request.end_date,
            )
    except (ValueError, DartError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "corp_code": request.corp_code,
        "saved_count": saved_count,
    }
