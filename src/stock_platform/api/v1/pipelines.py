from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.operation.pipeline_repository import (
    PipelineRepository,
)
from stock_platform.scheduler.daily_pipeline import (
    DailyStrategyPipeline,
)


router = APIRouter(
    prefix="/api/v1/pipelines",
    tags=["Pipelines"],
)


class DailyPipelineRequest(BaseModel):
    as_of_date: date | None = None
    trigger_type: str = Field(
        default="MANUAL",
        min_length=1,
        max_length=30,
    )
    retry_delay_seconds: float = Field(
        default=5.0,
        ge=0,
        le=300,
    )


@router.post("/daily-strategy")
async def execute_daily_strategy_pipeline(
    request: DailyPipelineRequest,
    session: Session = Depends(get_db_session),
):
    pipeline, steps = await DailyStrategyPipeline(
        session
    ).execute(
        as_of_date=request.as_of_date,
        trigger_type=request.trigger_type,
        retry_delay_seconds=(
            request.retry_delay_seconds
        ),
    )

    return {
        "pipeline_run_id": pipeline.pipeline_run_id,
        "pipeline_name": pipeline.pipeline_name,
        "status_code": pipeline.status_code,
        "started_at": pipeline.started_at,
        "finished_at": pipeline.finished_at,
        "error_message": pipeline.error_message,
        "steps": steps,
    }


@router.get("/latest")
def get_latest_pipeline(
    pipeline_name: str | None = None,
    session: Session = Depends(get_db_session),
):
    repository = PipelineRepository(session)
    pipeline = repository.get_latest(
        pipeline_name=pipeline_name
    )

    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline run not found",
        )

    steps = repository.list_steps(
        pipeline.pipeline_run_id
    )

    return {
        "pipeline_run_id": pipeline.pipeline_run_id,
        "pipeline_name": pipeline.pipeline_name,
        "trigger_type": pipeline.trigger_type,
        "status_code": pipeline.status_code,
        "started_at": pipeline.started_at,
        "finished_at": pipeline.finished_at,
        "request_payload": pipeline.request_payload,
        "result_payload": pipeline.result_payload,
        "error_message": pipeline.error_message,
        "steps": steps,
    }
