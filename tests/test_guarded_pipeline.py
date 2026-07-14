import asyncio
from datetime import date
from types import SimpleNamespace

from stock_platform.scheduler.guarded_pipeline import (
    TradingDayGuardedPipeline,
)


class FakeCalendar:
    def evaluate(self, **kwargs):
        return SimpleNamespace(
            exchange_code="KRX",
            calendar_date=kwargs["calendar_date"],
            is_trading_day=False,
            reason_code="WEEKEND",
            holiday_name=None,
            source_code="SYSTEM",
        )


class FakePipeline:
    async def execute(self, **kwargs):
        raise AssertionError(
            "Pipeline must not execute on closed day"
        )


def test_pipeline_is_skipped_on_non_trading_day() -> None:
    service = TradingDayGuardedPipeline.__new__(
        TradingDayGuardedPipeline
    )
    service._calendar = FakeCalendar()
    service._pipeline = FakePipeline()

    result = asyncio.run(
        service.execute(
            exchange_code="KRX",
            as_of_date=date(2026, 7, 18),
            trigger_type="MANUAL",
            retry_delay_seconds=0,
        )
    )

    assert result.executed is False
    assert result.reason_code == "NON_TRADING_DAY"
