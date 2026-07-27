from stock_platform.common.settings import Settings
from stock_platform.scheduler.automatic import (
    AutomaticScheduler,
)


def test_scheduler_registers_contract_jobs() -> None:
    """등록 job ID는 AutomaticScheduler.REGISTERED_JOB_IDS 계약을 따른다."""

    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        scheduler_enabled=True,
    )

    scheduler = AutomaticScheduler(settings)
    scheduler.configure()

    assert (
        scheduler.registered_job_ids()
        == set(AutomaticScheduler.REGISTERED_JOB_IDS)
    )


def test_configure_is_idempotent() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        scheduler_enabled=True,
    )
    scheduler = AutomaticScheduler(settings)
    scheduler.configure()
    scheduler.configure()
    assert len(scheduler.registered_job_ids()) == len(
        AutomaticScheduler.REGISTERED_JOB_IDS
    )
