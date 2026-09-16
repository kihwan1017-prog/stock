"""Market data collection reliability tests."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from stock_platform.markets.gap_detection_service import MarketDataGapDetectionService
from stock_platform.operation.calendar_service import TradingCalendarService
from stock_platform.scheduler.automatic import AutomaticScheduler
from stock_platform.scheduler.factory import build_job_registry


def test_job_registry_includes_daily_collectors() -> None:
    registry = build_job_registry(MagicMock())
    names = {job.name for job in registry.list_jobs()}
    assert "upbit_krw_daily_sync" in names
    assert "kiwoom_krx_daily_sync" in names


def test_automatic_scheduler_registers_market_data_cron() -> None:
    scheduler = AutomaticScheduler()
    scheduler.configure()
    ids = scheduler.registered_job_ids()
    assert "upbit_krw_daily_sync_daily" in ids
    assert "kiwoom_krx_daily_sync_daily" in ids


def test_krx_gap_detection_skips_weekends(monkeypatch) -> None:
    service = MarketDataGapDetectionService(MagicMock())

    monkeypatch.setattr(
        TradingCalendarService,
        "is_trading_day",
        lambda self, exchange_code, calendar_date: calendar_date.weekday() < 5,
    )

    start = date(2026, 8, 10)
    end = date(2026, 8, 14)
    dates = service._expected_dates("KRX", start, end)
    assert len(dates) == 5


def test_upbit_gap_uses_calendar_days() -> None:
    service = MarketDataGapDetectionService(MagicMock())
    start = date(2026, 8, 1)
    end = date(2026, 8, 3)
    dates = service._expected_dates("UPBIT", start, end)
    assert dates == [start, start + timedelta(days=1), end]


def test_quality_status_labels() -> None:
    from stock_platform.markets.collection_status_service import (
        QUALITY_NOT_COLLECTED,
        _status_label,
    )

    assert "미수집" in _status_label(QUALITY_NOT_COLLECTED)
