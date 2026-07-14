from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.screener.run_service import CandidateRunService

router = APIRouter(prefix="/api/v1/candidate-runs", tags=["Candidate Runs"])


class CandidateRunRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    as_of_date: date
    limit: int = Field(default=30, ge=1, le=200)
    minimum_score: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("100"))
    require_all_rules: bool = False
    run_type: str = Field(default="DAILY", max_length=20)


@router.post("")
def execute_candidate_run(request: CandidateRunRequest, session: Session = Depends(get_db_session)):
    service = CandidateRunService(session)
    try:
        run = service.execute_and_save(
            exchange_code=request.exchange_code.upper(),
            as_of_date=request.as_of_date,
            limit=request.limit,
            minimum_score=request.minimum_score,
            require_all_rules=request.require_all_rules,
            run_type=request.run_type.upper(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "run_id": run.run_id,
        "exchange_code": run.exchange_code,
        "as_of_date": run.as_of_date,
        "run_type": run.run_type,
        "requested_count": run.requested_count,
        "evaluated_count": run.evaluated_count,
        "skipped_count": run.skipped_count,
        "selected_count": run.selected_count,
        "status_code": run.status_code,
    }


@router.get("/latest/{exchange_code}")
def get_latest_candidate_run(exchange_code: str, session: Session = Depends(get_db_session)):
    service = CandidateRunService(session)
    result = service.get_latest(exchange_code=exchange_code.upper())
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate run not found")

    run, rows = result
    return {
        "run_id": run.run_id,
        "exchange_code": run.exchange_code,
        "as_of_date": run.as_of_date,
        "run_type": run.run_type,
        "selected_count": run.selected_count,
        "status_code": run.status_code,
        "candidates": [
            {
                "rank_no": row.rank_no,
                "symbol": row.symbol,
                "trade_date": row.trade_date,
                "total_score": row.total_score,
                "rules_passed_count": row.rules_passed_count,
                "all_rules_passed": row.all_rules_passed,
                "rule_result": row.rule_result,
                "score_breakdown": row.score_breakdown,
            }
            for row in rows
        ],
    }
