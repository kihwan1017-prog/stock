from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_ranker import (
    OllamaCandidateRanker,
)
from stock_platform.ai.ollama_client import (
    OllamaClient,
    OllamaError,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/ai/candidates",
    tags=["AI Candidates"],
)


@router.post("/rank/{exchange_code}")
async def rank_candidates(
    exchange_code: str,
    limit: int = Query(default=10, ge=1, le=30),
    session: Session = Depends(get_db_session),
):
    settings = get_settings()

    try:
        async with OllamaClient(settings=settings) as client:
            ranker = OllamaCandidateRanker(
                session=session,
                ollama_client=client,
                model_name=settings.ollama_model,
            )

            result = await ranker.rank_latest(
                exchange_code=exchange_code,
                limit=limit,
            )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except OllamaError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "exchange_code": result.exchange_code,
        "source_run_id": result.source_run_id,
        "model": result.model,
        "candidate_count": len(result.candidates),
        "candidates": [
            {
                "rank": item.rank,
                "symbol": item.symbol,
                "ai_score": item.ai_score,
                "action": item.action,
                "confidence": item.confidence,
                "reasons": item.reasons,
                "risks": item.risks,
            }
            for item in result.candidates
        ],
    }
