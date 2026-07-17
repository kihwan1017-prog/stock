from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import (
    OllamaClient,
    OllamaError,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.news.naver_client import (
    NaverNewsClient,
    NaverNewsError,
)
from stock_platform.news.repository import NewsRepository
from stock_platform.news.service import NewsService


router = APIRouter(
    prefix="/api/v1/news",
    tags=["News"],
)


class NewsSyncRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    query: str = Field(min_length=1, max_length=300)
    display: int = Field(default=100, ge=1, le=100)


class NewsSummarizeRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    limit: int = Field(default=20, ge=1, le=100)


async def _build_service(
    session: Session,
):
    settings = get_settings()
    naver = NaverNewsClient(settings=settings)
    ollama = OllamaClient(settings=settings)

    return (
        NewsService(
            repository=NewsRepository(session),
            naver_client=naver,
            ollama_client=ollama,
            model_name=settings.ollama_model,
        ),
        naver,
        ollama,
    )


@router.post("/sync")
async def sync_news(
    request: NewsSyncRequest,
    session: Session = Depends(get_db_session),
):
    service, naver, ollama = await _build_service(session)

    try:
        result = await service.sync_detailed(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            query=request.query,
            display=request.display,
        )
    except (ValueError, NaverNewsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    finally:
        await naver.aclose()
        await ollama.aclose()

    return {
        "exchange_code": result.exchange_code,
        "symbol": result.symbol,
        "fetched_count": result.fetched_count,
        "unique_count": result.unique_count,
        "saved_count": result.saved_count,
        "duplicate_skipped": result.duplicate_skipped,
    }


@router.get("/failures")
def list_news_failures(
    exchange_code: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db_session),
):
    rows = NewsRepository(session).list_failures(
        exchange_code=exchange_code,
        symbol=symbol,
        limit=limit,
    )
    return [
        {
            "failure_id": row.failure_id,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "query_text": row.query_text,
            "source_code": row.source_code,
            "error_message": row.error_message,
            "failed_at": row.failed_at,
        }
        for row in rows
    ]


@router.post("/summarize")
async def summarize_news(
    request: NewsSummarizeRequest,
    session: Session = Depends(get_db_session),
):
    service, naver, ollama = await _build_service(session)

    try:
        saved_count = await service.summarize(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            limit=request.limit,
        )
    except OllamaError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    finally:
        await naver.aclose()
        await ollama.aclose()

    return {"saved_count": saved_count}


@router.get("/{exchange_code}/{symbol}")
async def get_news_context(
    exchange_code: str,
    symbol: str,
    limit: int = 20,
    session: Session = Depends(get_db_session),
):
    service, naver, ollama = await _build_service(session)

    try:
        return service.build_context(
            exchange_code=exchange_code,
            symbol=symbol,
            limit=limit,
        )
    finally:
        await naver.aclose()
        await ollama.aclose()
