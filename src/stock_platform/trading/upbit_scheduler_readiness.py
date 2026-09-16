"""Trading / Tracking / Post-fill Scheduler Readiness 공통 스냅샷."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import Settings, get_settings
from stock_platform.trading.trading_scheduler_control import (
    get_trading_scheduler_desired_state,
)


@dataclass(slots=True)
class SchedulerReadinessSnapshot:
    trading_scheduler_desired_state: str
    trading_scheduler_actual_state: str
    trading_scheduler_paused: bool
    tracking_scheduler_running: bool
    post_fill_scheduler_running: bool
    tracking_desired_state: str
    post_fill_desired_state: str
    snapshot_checked_at: str
    snapshot_stale: bool
    trading_running: bool | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_scheduler_readiness(
    settings: Settings | None = None,
    *,
    stale_after_seconds: int = 60,
) -> SchedulerReadinessSnapshot:
    """
    UI readiness / CLI preflight 공통.
    trading: in-process realtime_trading_scheduler.running 실제값 우선.
    tracking/post-fill: settings enabled (별도 in-process runner 없을 때).
    """

    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    trading_running: bool | None = None
    source = "settings_fallback"
    try:
        from stock_platform.realtime.session_runtime import (
            realtime_trading_scheduler,
        )

        trading_running = bool(realtime_trading_scheduler.scheduler.running)
        source = "realtime_trading_scheduler"
    except Exception:  # noqa: BLE001
        trading_running = None
        source = "unavailable"

    if trading_running is True:
        actual = "RUNNING"
        paused = False
    elif trading_running is False:
        actual = "PAUSED"
        paused = True
    else:
        # 프로세스 밖 CLI — settings 플래그만 참고하되 paused 단정 금지
        treat = bool(
            getattr(settings, "upbit_live_smoke_treat_scheduler_paused", False)
        )
        if treat:
            actual = "PAUSED_ASSUMED"
            paused = True
            source = "settings_treat_paused"
        else:
            actual = "UNKNOWN"
            paused = False
            source = "unknown"

    track_enabled = bool(getattr(settings, "upbit_live_track_enabled", True))
    post_fill_enabled = bool(
        getattr(settings, "post_fill_verify_enabled", True)
    )

    return SchedulerReadinessSnapshot(
        trading_scheduler_desired_state=get_trading_scheduler_desired_state(),
        trading_scheduler_actual_state=actual,
        trading_scheduler_paused=paused,
        tracking_scheduler_running=track_enabled,
        post_fill_scheduler_running=post_fill_enabled,
        tracking_desired_state="RUNNING",
        post_fill_desired_state="RUNNING",
        snapshot_checked_at=now.isoformat(),
        snapshot_stale=False,
        trading_running=trading_running,
        source=source,
    )
