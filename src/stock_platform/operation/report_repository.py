from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.report_models import (
    DailyOperationsReport,
)


class DailyOperationsReportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        report: DailyOperationsReport,
    ) -> DailyOperationsReport:
        existing = self._session.scalar(
            select(DailyOperationsReport).where(
                DailyOperationsReport.report_date
                == report.report_date,
                DailyOperationsReport.exchange_code
                == report.exchange_code,
            )
        )

        if existing is None:
            self._session.add(report)
            target = report
        else:
            existing.pipeline_status_code = (
                report.pipeline_status_code
            )
            existing.job_success_count = (
                report.job_success_count
            )
            existing.job_failed_count = (
                report.job_failed_count
            )
            existing.selected_candidate_count = (
                report.selected_candidate_count
            )
            existing.ai_candidate_count = (
                report.ai_candidate_count
            )
            existing.approved_position_count = (
                report.approved_position_count
            )
            existing.total_order_amount = (
                report.total_order_amount
            )
            existing.realized_profit_loss = (
                report.realized_profit_loss
            )
            existing.unrealized_profit_loss = (
                report.unrealized_profit_loss
            )
            existing.summary_text = report.summary_text
            existing.incident_summary = (
                report.incident_summary
            )
            existing.details = report.details
            target = existing

        self._session.commit()
        self._session.refresh(target)
        return target

    def get(
        self,
        *,
        report_date: date,
        exchange_code: str,
    ) -> DailyOperationsReport | None:
        return self._session.scalar(
            select(DailyOperationsReport).where(
                DailyOperationsReport.report_date
                == report_date,
                DailyOperationsReport.exchange_code
                == exchange_code.upper(),
            )
        )

    def list_recent(
        self,
        *,
        exchange_code: str | None = None,
        limit: int = 30,
    ) -> list[DailyOperationsReport]:
        stmt = select(DailyOperationsReport)

        if exchange_code:
            stmt = stmt.where(
                DailyOperationsReport.exchange_code
                == exchange_code.upper()
            )

        stmt = stmt.order_by(
            DailyOperationsReport.report_date.desc(),
            DailyOperationsReport.report_id.desc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))
