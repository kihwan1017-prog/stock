from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.disclosure.dart_client import DartClient, DartError
from stock_platform.disclosure.repository import (
    DartCorpRepository,
    DartDisclosureRepository,
)
from stock_platform.disclosure.service import DartDisclosureService


router = APIRouter(
    prefix="/api/v1/dart",
    tags=["DART"],
)


class DartSyncRequest(BaseModel):
    corp_code: str | None = Field(default=None, min_length=8, max_length=8)
    stock_code: str | None = Field(default=None, min_length=1, max_length=20)
    start_date: date
    end_date: date
    resume: bool = True


def _disclosure_dict(row) -> dict:
    return {
        "disclosure_id": row.disclosure_id,
        "receipt_no": row.receipt_no,
        "corp_code": row.corp_code,
        "corp_name": row.corp_name,
        "stock_code": row.stock_code,
        "report_name": row.report_name,
        "filer_name": row.filer_name,
        "receipt_date": row.receipt_date,
        "remark": row.remark,
        "category_code": row.category_code,
        "importance_score": (
            float(row.importance_score)
            if row.importance_score is not None
            else 0
        ),
        "is_correction": row.is_correction,
    }


@router.get("/disclosures")
def list_dart_disclosures(
    stock_code: str = Query(min_length=1, max_length=20),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    rows = DartDisclosureRepository(session).list_context(
        stock_code=stock_code.upper(),
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return {
        "items": [_disclosure_dict(row) for row in rows],
        "stock_code": stock_code.upper(),
        "limit": limit,
    }


@router.get("/corps")
def list_dart_corps(
    limit: int = Query(default=100, ge=1, le=5000),
    session: Session = Depends(get_db_session),
):
    rows = DartCorpRepository(session).list_listed(limit=limit)
    return {
        "items": [
            {
                "corp_code": row.corp_code,
                "corp_name": row.corp_name,
                "stock_code": row.stock_code,
            }
            for row in rows
        ],
        "limit": limit,
    }


@router.post("/corps/sync")
async def sync_dart_corps(
    session: Session = Depends(get_db_session),
):
    try:
        async with DartClient() as client:
            service = DartDisclosureService(
                client=client,
                repository=DartDisclosureRepository(session),
                corp_repository=DartCorpRepository(session),
            )
            saved_count = await service.sync_corp_codes()
    except (ValueError, DartError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {"saved_count": saved_count}


@router.post("/sync")
async def sync_dart_disclosures(
    request: DartSyncRequest,
    session: Session = Depends(get_db_session),
):
    if not request.corp_code and not request.stock_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="corp_code or stock_code is required",
        )

    try:
        async with DartClient() as client:
            service = DartDisclosureService(
                client=client,
                repository=DartDisclosureRepository(session),
                corp_repository=DartCorpRepository(session),
            )

            if request.stock_code:
                result = await service.sync_by_stock_code(
                    stock_code=request.stock_code.upper(),
                    start_date=request.start_date,
                    end_date=request.end_date,
                    resume=request.resume,
                )
            else:
                result = await service.sync(
                    corp_code=request.corp_code or "",
                    start_date=request.start_date,
                    end_date=request.end_date,
                    resume=request.resume,
                )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ValueError, DartError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "corp_code": result.corp_code,
        "stock_code": result.stock_code,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "fetched_count": result.fetched_count,
        "saved_count": result.saved_count,
        "resumed": result.resumed,
    }
