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
    limit: int = Field(default=5, ge=1, le=10)
    contexts: dict[str, SymbolContext] = Field(
        default_factory=dict
    )


def _build_service(session: Session) -> CandidateAnalysisService:
    settings = get_settings()
    return CandidateAnalysisService(
        session=session,
        ollama_client=OllamaClient(settings=settings),
        model_name=settings.ollama_model,
    )


def _serialize_run(run) -> dict[str, Any]:
    return {
        "analysis_run_id": run.analysis_run_id,
        "source_candidate_run_id": (
            run.source_candidate_run_id
        ),
        "exchange_code": run.exchange_code,
        "model": run.model_name,
        "prompt_version": run.prompt_version,
        "context_hash": run.context_hash,
        "used_fallback": run.used_fallback,
        "duration_ms": run.duration_ms,
        "error_count": run.error_count,
        "request_count": run.request_count,
        "parent_analysis_run_id": (
            run.parent_analysis_run_id
        ),
        "requested_limit": run.requested_limit,
        "selected_count": run.selected_count,
        "status_code": run.status_code,
        "metrics": run.metrics,
        "created_at": run.created_at,
    }


def _serialize_result(row) -> dict[str, Any]:
    return {
        "rank": row.rank_no,
        "symbol": row.symbol,
        "ai_score": row.ai_score,
        "action": row.action_code,
        "confidence": row.confidence,
        "reasons": row.reasons,
        "risks": row.risks,
        "context_used": row.context_used,
        "rationale": row.rationale,
    }


@router.get("/runs")
def list_ai_analysis_runs(
    exchange_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
):
    service = _build_service(session)
    runs = service.list_runs(
        exchange_code=exchange_code,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_serialize_run(run) for run in runs],
        "limit": limit,
        "offset": offset,
    }


@router.get("/metrics")
def get_ai_analysis_metrics(
    exchange_code: str | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_db_session),
):
    service = _build_service(session)
    return service.get_metrics(
        exchange_code=exchange_code,
        days=days,
    )


@router.get("/runs/{analysis_run_id}")
def get_ai_analysis_run(
    analysis_run_id: int,
    session: Session = Depends(get_db_session),
):
    service = _build_service(session)
    result = service.get_run(analysis_run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI analysis not found",
        )
    run, rows = result
    payload = _serialize_run(run)
    payload["candidates"] = [
        _serialize_result(row) for row in rows
    ]
    return payload


@router.get("/runs/{analysis_run_id}/candidates/{symbol}")
def get_ai_candidate_rationale(
    analysis_run_id: int,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    service = _build_service(session)
    result = service.get_candidate_rationale(
        analysis_run_id=analysis_run_id,
        symbol=symbol,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI candidate rationale not found",
        )
    run, row = result
    return {
        "analysis_run_id": run.analysis_run_id,
        "exchange_code": run.exchange_code,
        "model": run.model_name,
        "prompt_version": run.prompt_version,
        "context_hash": run.context_hash,
        "candidate": _serialize_result(row),
    }


@router.post("/runs/{analysis_run_id}/reproduce")
async def reproduce_ai_analysis(
    analysis_run_id: int,
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    try:
        async with OllamaClient(
            settings=settings
        ) as client:
            service = CandidateAnalysisService(
                session=session,
                ollama_client=client,
                model_name=settings.ollama_model,
            )
            payload = await service.reproduce(
                analysis_run_id=analysis_run_id
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

    baseline = payload["baseline_run"]
    reproduced = payload["reproduced_run"]
    ranking = payload["ranking"]
    return {
        "baseline": _serialize_run(baseline),
        "reproduced": _serialize_run(reproduced),
        "same_context_hash": payload["same_context_hash"],
        "comparison": payload["comparison"],
        "candidates": [
            {
                "rank": item.rank,
                "symbol": item.symbol,
                "ai_score": item.ai_score,
                "action": item.action,
                "confidence": item.confidence,
                "reasons": item.reasons,
                "risks": item.risks,
                "selection_source": item.selection_source,
            }
            for item in ranking.candidates
        ],
    }


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
        **_serialize_run(run),
        "candidates": [
            {
                "rank": item.rank,
                "symbol": item.symbol,
                "ai_score": item.ai_score,
                "action": item.action,
                "confidence": item.confidence,
                "reasons": item.reasons,
                "risks": item.risks,
                "selection_source": item.selection_source,
            }
            for item in ranking.candidates
        ],
        "used_fallback": ranking.used_fallback,
    }


@router.get("/latest/{exchange_code}")
def get_latest_ai_analysis(
    exchange_code: str,
    session: Session = Depends(get_db_session),
):
    service = _build_service(session)
    result = service.get_latest(
        exchange_code=exchange_code
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI analysis not found",
        )

    run, rows = result
    payload = _serialize_run(run)
    payload["candidates"] = [
        _serialize_result(row) for row in rows
    ]
    return payload
