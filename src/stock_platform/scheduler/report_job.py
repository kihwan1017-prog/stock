from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.report_service import (
    DailyOperationsReportService,
)


class DailyReportJob:
    """스케줄러에서 호출할 일일 리포트 생성 작업."""

    def __init__(self, session: Session) -> None:
        self._service = DailyOperationsReportService(
            session
        )

    def execute(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        report = self._service.generate(
            report_date=date.fromisoformat(
                str(payload["report_date"])
            ),
            exchange_code=str(
                payload.get("exchange_code", "KRX")
            ),
            paper_account_id=(
                int(payload["paper_account_id"])
                if payload.get("paper_account_id")
                is not None
                else None
            ),
            current_prices={
                key.upper(): Decimal(str(value))
                for key, value in (
                    payload.get(
                        "current_prices",
                        {},
                    )
                ).items()
            },
        )

        return {
            "report_id": report.report_id,
            "report_date": (
                report.report_date.isoformat()
            ),
            "exchange_code": report.exchange_code,
            "pipeline_status_code": (
                report.pipeline_status_code
            ),
            "job_failed_count": (
                report.job_failed_count
            ),
            "summary_text": report.summary_text,
        }
