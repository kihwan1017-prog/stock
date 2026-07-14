from stock_platform.common.settings import Settings
from stock_platform.scheduler.automatic import (
    AutomaticScheduler,
)


def test_scheduler_registers_three_jobs() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        scheduler_enabled=True,
    )

    scheduler = AutomaticScheduler(settings)
    scheduler.configure()

    job_ids = {
        job.id
        for job in scheduler.scheduler.get_jobs()
    }

    assert job_ids == {
        "candidate_screening_daily",
        "ai_orchestration_daily",
        "position_planning_daily",
    }
