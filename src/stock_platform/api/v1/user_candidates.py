"""회원용 매매 후보 조회 API — 읽기 전용.

admin 전용 candidate-runs / candidates GET을 trading:read로 재노출한다.
실행(POST)·AI 랭킹·오케스트레이션은 노출하지 않는다.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.screener.batch_service import CandidateBatchService
from stock_platform.screener.run_service import CandidateRunService


router = APIRouter(
    prefix="/api/v1/user/candidates",
    tags=["User Candidates"],
)


@router.get("/latest/{exchange_code}")
def get_latest_candidates(
    exchange_code: str,
    _: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    """저장된 최신 후보 런 조회 (부하 낮은 읽기)."""

    result = CandidateRunService(session).get_latest(
        exchange_code=exchange_code.upper(),
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate run not found",
        )

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


@router.get("/top/{exchange_code}")
def get_top_candidates(
    exchange_code: str,
    as_of_date: date = Query(...),
    limit: int = Query(default=30, ge=1, le=100),
    minimum_score: float = Query(default=0, ge=0, le=100),
    require_all_rules: bool = Query(default=False),
    _: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    """당일 스크리닝 상위 후보 (계산 가능 — 부하 주의)."""

    try:
        result = CandidateBatchService(session).screen(
            exchange_code=exchange_code.upper(),
            as_of_date=as_of_date,
            limit=limit,
            minimum_score=minimum_score,
            require_all_rules=require_all_rules,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "exchange_code": result.exchange_code,
        "as_of_date": result.as_of_date,
        "requested_count": result.requested_count,
        "evaluated_count": result.evaluated_count,
        "skipped_count": result.skipped_count,
        "selected_count": len(result.selected),
        "candidates": [
            {
                "exchange_code": score.exchange_code,
                "symbol": score.symbol,
                "trade_date": score.trade_date,
                "total_score": score.total_score,
                "rules": score.rules.to_dict(),
                "breakdown": {
                    "liquidity": score.breakdown.liquidity,
                    "trade_value": score.breakdown.trade_value,
                    "volume": score.breakdown.volume,
                    "trend": score.breakdown.trend,
                    "rsi": score.breakdown.rsi,
                    "macd": score.breakdown.macd,
                    "week52": score.breakdown.week52,
                    "breakout": score.breakdown.breakout,
                    "volatility": score.breakdown.volatility,
                    "total": score.breakdown.total,
                },
            }
            for score in result.selected
        ],
    }
