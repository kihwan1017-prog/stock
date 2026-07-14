from stock_platform.common.settings import Settings
from stock_platform.realtime.session_scheduler import (
    RealtimeTradingScheduler,
)


def test_registers_four_realtime_session_jobs() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        scheduler_timezone="Asia/Seoul",
    )

    scheduler = RealtimeTradingScheduler(settings)
    scheduler.configure()

    job_ids = {
        job.id
        for job in scheduler.scheduler.get_jobs()
    }

    assert job_ids == {
        "realtime_pre_market",
        "realtime_market_open",
        "realtime_market_close",
        "realtime_after_market",
    }
