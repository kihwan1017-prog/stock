"""Autotrading reliability SLO — 단일 설정 SoT."""

from __future__ import annotations

from dataclasses import dataclass

from stock_platform.common.settings import get_settings


@dataclass(frozen=True)
class AutotradingHealthSlo:
    """초기 SLO (audit 2026-08-27 기준). scheduler 주기에 맞춰 multiplier 적용."""

    feed_max_age_seconds: float = 30.0
    scanner_interval_seconds: float = 300.0
    scanner_max_age_multiplier: float = 2.0
    runner_heartbeat_max_age_seconds: float = 30.0
    worker_heartbeat_max_age_seconds: float = 30.0
    exit_monitor_heartbeat_max_age_seconds: float = 30.0
    exit_eval_max_age_seconds: float = 30.0
    arm_remaining_warn_seconds: float = 600.0
    binding_finalize_max_seconds: float = 60.0
    waiting_stale_hours: float = 6.0
    pipeline_stall_minutes: float = 15.0
    funnel_window_minutes: float = 15.0

    @property
    def scanner_max_age_seconds(self) -> float:
        return self.scanner_interval_seconds * self.scanner_max_age_multiplier


def load_autotrading_health_slo() -> AutotradingHealthSlo:
    settings = get_settings()
    scanner_iv = float(
        getattr(settings, "upbit_opportunity_scanner_interval_seconds", 300.0)
        or 300.0
    )
    feed_stale = float(
        getattr(settings, "autotrading_market_feed_stale_seconds", 30.0) or 30.0
    )
    return AutotradingHealthSlo(
        feed_max_age_seconds=feed_stale,
        scanner_interval_seconds=scanner_iv,
        scanner_max_age_multiplier=float(
            getattr(settings, "autotrading_scanner_slo_multiplier", 2.0) or 2.0
        ),
        runner_heartbeat_max_age_seconds=float(
            getattr(
                settings, "autotrading_runner_heartbeat_slo_seconds", 30.0
            )
            or 30.0
        ),
        worker_heartbeat_max_age_seconds=float(
            getattr(
                settings, "autotrading_worker_heartbeat_slo_seconds", 30.0
            )
            or 30.0
        ),
        exit_monitor_heartbeat_max_age_seconds=float(
            getattr(settings, "autotrading_exit_heartbeat_slo_seconds", 30.0)
            or 30.0
        ),
        exit_eval_max_age_seconds=float(
            getattr(settings, "autotrading_exit_eval_slo_seconds", 30.0) or 30.0
        ),
        pipeline_stall_minutes=float(
            getattr(settings, "autotrading_pipeline_stall_minutes", 15.0) or 15.0
        ),
        funnel_window_minutes=float(
            getattr(settings, "autotrading_funnel_window_minutes", 15.0) or 15.0
        ),
    )
