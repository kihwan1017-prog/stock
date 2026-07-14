from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import (
    TradingCalendarService,
    TradingDayDecision,
)
from stock_platform.scheduler.daily_pipeline import (
    DailyStrategyPipeline,
)


@dataclass(frozen=True, slots=True)
class GuardedPipelineResult:
    executed: bool
    reason_code: str
    trading_day: TradingDayDecision
    pipeline_run_id: int | None
    pipeline_status_code: str | None
    steps: list[dict]


class TradingDayGuardedPipeline:
    """휴장일에는 일일 전략 파이프라인을 실행하지 않는다."""

    def __init__(self, session: Session) -> None:
        self._calendar = TradingCalendarService(
            TradingCalendarRepository(session)
        )
        self._pipeline = DailyStrategyPipeline(session)

    async def execute(
        self,
        *,
        exchange_code: str,
        as_of_date: date,
        trigger_type: str,
        retry_delay_seconds: float,
    ) -> GuardedPipelineResult:
        decision = self._calendar.evaluate(
            exchange_code=exchange_code,
            calendar_date=as_of_date,
        )

        if not decision.is_trading_day:
            return GuardedPipelineResult(
                executed=False,
                reason_code="NON_TRADING_DAY",
                trading_day=decision,
                pipeline_run_id=None,
                pipeline_status_code=None,
                steps=[],
            )

        pipeline, steps = await self._pipeline.execute(
            as_of_date=as_of_date,
            trigger_type=trigger_type,
            retry_delay_seconds=retry_delay_seconds,
        )

        return GuardedPipelineResult(
            executed=True,
            reason_code="EXECUTED",
            trading_day=decision,
            pipeline_run_id=pipeline.pipeline_run_id,
            pipeline_status_code=pipeline.status_code,
            steps=steps,
        )
