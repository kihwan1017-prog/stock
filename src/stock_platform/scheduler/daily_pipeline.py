from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.settings import Settings, get_settings
from stock_platform.scheduler.pipeline_service import (
    DailyPipelineService,
    PipelineStepDefinition,
)


class DailyStrategyPipeline:
    """후보선정 → AI 분석 → 포지션 계획 파이프라인."""

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._service = DailyPipelineService(session)

    async def execute(
        self,
        *,
        as_of_date: date | None = None,
        trigger_type: str = "MANUAL",
        retry_delay_seconds: float = 5.0,
    ):
        target_date = as_of_date or date.today()
        exchange_code = (
            self._settings.scheduler_exchange_code
        ).upper()

        steps = [
            PipelineStepDefinition(
                step_order=1,
                step_name="candidate_screening",
                job_name="candidate_screening",
                payload={
                    "exchange_code": exchange_code,
                    "as_of_date": target_date.isoformat(),
                    "limit": (
                        self._settings
                        .scheduler_candidate_limit
                    ),
                    "minimum_score": (
                        self._settings
                        .scheduler_minimum_score
                    ),
                    "require_all_rules": False,
                    "run_type": "DAILY",
                },
                max_attempts=3,
                retry_delay_seconds=retry_delay_seconds,
            ),
            PipelineStepDefinition(
                step_order=2,
                step_name="ai_orchestration",
                job_name="ai_orchestration",
                payload={
                    "exchange_code": exchange_code,
                    "limit": (
                        self._settings.scheduler_ai_limit
                    ),
                    "news_limit": 20,
                    "disclosure_limit": 20,
                    "lookback_days": 90,
                },
                max_attempts=3,
                retry_delay_seconds=retry_delay_seconds,
            ),
            PipelineStepDefinition(
                step_order=3,
                step_name="position_planning",
                job_name="position_planning",
                payload={
                    "exchange_code": exchange_code,
                    "policy_id": (
                        self._settings.scheduler_policy_id
                    ),
                    "portfolio_value": (
                        self._settings
                        .scheduler_portfolio_value
                    ),
                    "available_cash": (
                        self._settings
                        .scheduler_available_cash
                    ),
                    "current_position_count": 0,
                    "limit": (
                        self._settings
                        .scheduler_position_limit
                    ),
                    "minimum_ai_score": (
                        self._settings
                        .scheduler_minimum_ai_score
                    ),
                    "minimum_confidence": (
                        self._settings
                        .scheduler_minimum_confidence
                    ),
                    "allowed_actions": [
                        "WATCH",
                        "REVIEW",
                    ],
                },
                max_attempts=3,
                retry_delay_seconds=retry_delay_seconds,
            ),
        ]

        request_payload: dict[str, Any] = {
            "exchange_code": exchange_code,
            "as_of_date": target_date.isoformat(),
            "step_count": len(steps),
        }

        return await self._service.execute(
            pipeline_name="daily_strategy_pipeline",
            trigger_type=trigger_type,
            request_payload=request_payload,
            steps=steps,
        )
