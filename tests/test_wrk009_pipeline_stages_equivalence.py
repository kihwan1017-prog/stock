"""Equivalence + smoke for WRK-009 daily report pipeline aggregation."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from stock_platform.database.session import get_session_factory
from stock_platform.operation.autotrading_daily_report_service import (
    _kst_day_bounds,
    _pipeline_unique_stages,
)


def test_pipeline_unique_stages_matches_legacy_per_stage_counts() -> None:
    """FILTER 1회 집계 == 기존 stage별 COUNT DISTINCT."""

    session = get_session_factory()()
    try:
        kst = ZoneInfo("Asia/Seoul")
        rd = datetime.now(kst).date()
        start_utc, end_utc = _kst_day_bounds(rd)
        uba = 1380
        optimized = _pipeline_unique_stages(
            session, uba_id=uba, start_utc=start_utc, end_utc=end_utc
        )
        mapping = {
            "CANDIDATE": ("ENTRY_PASS",),
            "AI_ALLOW": ("ENTRY_PASS",),
            "TECHNICAL_PASS": ("ENTRY_PASS",),
            "SIGNAL_EMITTED": ("SIGNAL_EMITTED",),
            "EXECUTOR_RECEIVED": ("EXECUTOR_RECEIVED",),
            "BEGIN_ENTRY_ACCEPTED": ("BEGIN_ENTRY_ACCEPTED",),
            "ORDER": ("ORDER_CREATED", "ADMISSION_PASS"),
            "FILL": ("FILL", "ORDER_FILLED"),
        }
        for key, stages in mapping.items():
            stage_list = ", ".join(f"'{s}'" for s in stages)
            n = session.scalar(
                text(
                    f"""
                    SELECT COUNT(DISTINCT selection_id)
                    FROM operation.upbit_entry_execution_trace
                    WHERE user_broker_account_id = :uba
                      AND created_at >= :start_utc AND created_at < :end_utc
                      AND selection_id IS NOT NULL
                      AND stage IN ({stage_list})
                    """
                ),
                {"uba": uba, "start_utc": start_utc, "end_utc": end_utc},
            )
            assert optimized[key] == int(n or 0), key
    finally:
        session.close()
