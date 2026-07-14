import asyncio
from types import SimpleNamespace


class FakeRepository:
    def __init__(self) -> None:
        self.created = None
        self.completed = None

    def create(self, **kwargs):
        self.created = SimpleNamespace(
            job_run_id=1,
            **kwargs,
        )
        return self.created

    def complete(self, **kwargs):
        self.completed = kwargs
        entity = kwargs["entity"]
        entity.status_code = kwargs["status_code"]
        return entity


def test_successful_job_execution() -> None:
    from stock_platform.operation.job_service import (
        JobExecutionService,
    )

    repository = FakeRepository()
    service = JobExecutionService(repository)  # type: ignore[arg-type]

    history, result = asyncio.run(
        service.execute(
            job_name="test_job",
            job_group="TEST",
            trigger_type="MANUAL",
            request_payload={"value": 1},
            handler=lambda: {"ok": True},
        )
    )

    assert result == {"ok": True}
    assert history.status_code == "SUCCESS"
    assert repository.completed["status_code"] == "SUCCESS"


def test_failed_job_execution_is_recorded() -> None:
    from stock_platform.operation.job_service import (
        JobExecutionService,
    )

    repository = FakeRepository()
    service = JobExecutionService(repository)  # type: ignore[arg-type]

    async def run() -> None:
        try:
            await service.execute(
                job_name="failed_job",
                job_group="TEST",
                trigger_type="MANUAL",
                request_payload={},
                handler=lambda: (_ for _ in ()).throw(
                    RuntimeError("failure")
                ),
            )
        except RuntimeError:
            pass

    asyncio.run(run())

    assert repository.completed["status_code"] == "FAILED"
    assert repository.completed["error_message"] == "failure"
