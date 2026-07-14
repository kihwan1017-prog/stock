from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.analysis_service import (
    CandidateAnalysisService,
)
from stock_platform.ai.ollama_client import (
    OllamaClient,
    OllamaError,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/ai-analysis",
    tags=["AI Analysis"],
)


class SymbolContext(BaseModel):
    news: list[str] = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CandidateAnalysisRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)
    contexts: dict[str, SymbolContext] = Field(
        default_factory=dict
    )


@router.post("/{exchange_code}")
async def execute_ai_analysis(
    exchange_code: str,
    request: CandidateAnalysisRequest,
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    contexts: dict[str, dict[str, Any]] = {
        symbol.upper(): context.model_dump()
        for symbol, context in request.contexts.items()
    }

    try:
        async with OllamaClient(
            settings=settings
        ) as client:
            service = CandidateAnalysisService(
                session=session,
                ollama_client=client,
                model_name=settings.ollama_model,
            )
            run, ranking = (
                await service.execute_and_save(
                    exchange_code=exchange_code.upper(),
                    limit=request.limit,
                    contexts=contexts,
                )
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
        "analysis_run_id": run.analysis_run_id,
        "source_candidate_run_id": (
            ranking.source_run_id
        ),
        "exchange_code": ranking.exchange_code,
        "model": ranking.model,
        "selected_count": len(ranking.candidates),
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


@router.get("/latest/{exchange_code}")
def get_latest_ai_analysis(
    exchange_code: str,
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    service = CandidateAnalysisService(
        session=session,
        ollama_client=OllamaClient(settings=settings),
        model_name=settings.ollama_model,
    )
    result = service.get_latest(
        exchange_code=exchange_code
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI analysis not found",
        )

    run, rows = result

    return {
        "analysis_run_id": run.analysis_run_id,
        "source_candidate_run_id": (
            run.source_candidate_run_id
        ),
        "exchange_code": run.exchange_code,
        "model": run.model_name,
        "selected_count": run.selected_count,
        "status_code": run.status_code,
        "created_at": run.created_at,
        "candidates": [
            {
                "rank": row.rank_no,
                "symbol": row.symbol,
                "ai_score": row.ai_score,
                "action": row.action_code,
                "confidence": row.confidence,
                "reasons": row.reasons,
                "risks": row.risks,
                "context_used": row.context_used,
            }
            for row in rows
        ],
    }
