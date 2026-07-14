from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import OllamaClient, OllamaError
from stock_platform.ai.orchestration_service import (
    CandidateAnalysisOrchestrator,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/ai-orchestration",
    tags=["AI Orchestration"],
)


class OrchestrationRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)
    news_limit: int = Field(default=20, ge=0, le=100)
    disclosure_limit: int = Field(default=20, ge=0, le=100)
    lookback_days: int = Field(default=90, ge=1, le=3650)


@router.post("/{exchange_code}")
async def execute_orchestration(
    exchange_code: str,
    request: OrchestrationRequest,
    session: Session = Depends(get_db_session),
):
    settings = get_settings()

    try:
        async with OllamaClient(settings=settings) as client:
            service = CandidateAnalysisOrchestrator(
                session=session,
                ollama_client=client,
                model_name=settings.ollama_model,
            )
            result = await service.execute(
                exchange_code=exchange_code,
                limit=request.limit,
                news_limit=request.news_limit,
                disclosure_limit=request.disclosure_limit,
                lookback_days=request.lookback_days,
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

    run = result["analysis_run"]
    ranking = result["ranking"]
    contexts = result["contexts"]

    return {
        "analysis_run_id": run.analysis_run_id,
        "source_candidate_run_id": ranking.source_run_id,
        "exchange_code": ranking.exchange_code,
        "model": ranking.model,
        "selected_count": len(ranking.candidates),
        "context_counts": {
            symbol: {
                "news": len(context.get("news", [])),
                "disclosures": len(
                    context.get("disclosures", [])
                ),
            }
            for symbol, context in contexts.items()
        },
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
            for item in ranking.candidates
        ],
    }
