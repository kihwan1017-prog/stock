import asyncio
from types import SimpleNamespace

from stock_platform.scheduler.pipeline_service import (
    DailyPipelineService,
    PipelineStepDefinition,
)


class FakeRepository:
    def __init__(self):
        self.pipeline = SimpleNamespace(
            pipeline_run_id=1,
            pipeline_name="test",
            status_code="RUNNING",
        )
        self.steps = []
        self.completed = None

    def create_pipeline(self, **kwargs):
        return self.pipeline

    def create_step(self, **kwargs):
        step = SimpleNamespace(
            pipeline_step_run_id=len(self.steps) + 1,
            **kwargs,
        )
        self.steps.append(step)
        return step

    def update_step(self, **kwargs):
        return kwargs["entity"]

    def complete_pipeline(self, **kwargs):
        self.completed = kwargs
        entity = kwargs["entity"]
        entity.status_code = kwargs["status_code"]
        return entity


class FakeScheduler:
    def __init__(self):
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return (
            SimpleNamespace(
                job_run_id=self.calls,
                status_code="SUCCESS",
            ),
            {"ok": True},
        )


def test_pipeline_runs_steps_in_order() -> None:
    service = DailyPipelineService.__new__(
        DailyPipelineService
    )
    service._repository = FakeRepository()
    service._scheduler = FakeScheduler()

    pipeline, steps = asyncio.run(
        service.execute(
            pipeline_name="test",
            trigger_type="MANUAL",
            request_payload={},
            steps=[
                PipelineStepDefinition(
                    step_order=2,
                    step_name="second",
                    job_name="job2",
                    payload={},
                    retry_delay_seconds=0,
                ),
                PipelineStepDefinition(
                    step_order=1,
                    step_name="first",
                    job_name="job1",
                    payload={},
                    retry_delay_seconds=0,
                ),
            ],
        )
    )

    assert pipeline.status_code == "SUCCESS"
    assert [step["step_name"] for step in steps] == [
        "first",
        "second",
    ]


def test_step_retries_then_succeeds() -> None:
    class RetryScheduler:
        def __init__(self):
            self.calls = 0

        async def execute(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("temporary")
            return (
                SimpleNamespace(
                    job_run_id=3,
                    status_code="SUCCESS",
                ),
                {"ok": True},
            )

    service = DailyPipelineService.__new__(
        DailyPipelineService
    )
    service._repository = FakeRepository()
    service._scheduler = RetryScheduler()

    pipeline, steps = asyncio.run(
        service.execute(
            pipeline_name="test",
            trigger_type="MANUAL",
            request_payload={},
            steps=[
                PipelineStepDefinition(
                    step_order=1,
                    step_name="retry",
                    job_name="job",
                    payload={},
                    max_attempts=3,
                    retry_delay_seconds=0,
                )
            ],
        )
    )

    assert pipeline.status_code == "SUCCESS"
    assert steps[0]["attempt_count"] == 3
