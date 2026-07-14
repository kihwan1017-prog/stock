from datetime import date
from decimal import Decimal

from stock_platform.operation.report_service import (
    DailyOperationsReportService,
)


def test_summary_text_contains_core_metrics() -> None:
    summary = DailyOperationsReportService._build_summary(
        report_date=date(2026, 7, 14),
        exchange_code="KRX",
        pipeline_status="SUCCESS",
        selected_candidate_count=30,
        ai_candidate_count=10,
        approved_position_count=5,
        total_order_amount=Decimal("5000000"),
        realized_profit_loss=Decimal("100000"),
        unrealized_profit_loss=Decimal("50000"),
    )

    assert "규칙 후보=30개" in summary
    assert "AI 후보=10개" in summary
    assert "승인 포지션 계획=5개" in summary
    assert "파이프라인=SUCCESS" in summary


def test_incident_summary() -> None:
    summary = (
        DailyOperationsReportService
        ._build_incident_summary(
            [
                {
                    "job_name": "ai_orchestration",
                    "error_message": "timeout",
                }
            ]
        )
    )

    assert summary == "ai_orchestration: timeout"


def test_no_incident_returns_none() -> None:
    assert (
        DailyOperationsReportService
        ._build_incident_summary([])
        is None
    )
