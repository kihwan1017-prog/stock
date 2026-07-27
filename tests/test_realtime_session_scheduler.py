from stock_platform.common.settings import Settings
from stock_platform.realtime.session_scheduler import (
    RealtimeTradingScheduler,
)


def test_registers_realtime_session_contract_jobs() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        scheduler_timezone="Asia/Seoul",
    )

    scheduler = RealtimeTradingScheduler(settings)
    scheduler.configure()

    assert (
        scheduler.registered_job_ids()
        == set(RealtimeTradingScheduler.REGISTERED_JOB_IDS)
    )
