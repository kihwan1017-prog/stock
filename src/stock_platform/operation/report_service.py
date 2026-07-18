from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.analysis_models import (
    CandidateAnalysisResult,
    CandidateAnalysisRun,
)
from stock_platform.operation.job_models import JobRunHistory
from stock_platform.operation.pipeline_models import (
    PipelineRun,
)
from stock_platform.operation.report_models import (
    DailyOperationsReport,
)
from stock_platform.operation.report_repository import (
    DailyOperationsReportRepository,
)
from stock_platform.risk.persistence_models import (
    PositionPlanEntity,
)
from stock_platform.screener.persistence_models import (
    CandidateRun,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
)


ZERO = Decimal("0")


class DailyOperationsReportService:
    """운영 이력과 전략 결과를 모아 일일 리포트를 생성한다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = (
            DailyOperationsReportRepository(session)
        )

    def generate(
        self,
        *,
        report_date: date,
        exchange_code: str,
        paper_account_id: int | None = None,
        current_prices: dict[str, Decimal] | None = None,
    ) -> DailyOperationsReport:
        exchange = exchange_code.upper()

        start_at = datetime.combine(
            report_date,
            time.min,
            tzinfo=timezone.utc,
        )
        end_at = datetime.combine(
            report_date,
            time.max,
            tzinfo=timezone.utc,
        )

        jobs = list(
            self._session.scalars(
                select(JobRunHistory).where(
                    JobRunHistory.started_at >= start_at,
                    JobRunHistory.started_at <= end_at,
                )
            )
        )

        job_success_count = sum(
            1
            for item in jobs
            if item.status_code == "SUCCESS"
        )
        job_failed_count = sum(
            1
            for item in jobs
            if item.status_code == "FAILED"
        )

        failed_jobs = [
            {
                "job_name": item.job_name,
                "error_message": item.error_message,
                "started_at": item.started_at.isoformat(),
            }
            for item in jobs
            if item.status_code == "FAILED"
        ]

        pipeline = self._session.scalar(
            select(PipelineRun)
            .where(
                PipelineRun.started_at >= start_at,
                PipelineRun.started_at <= end_at,
            )
            .order_by(
                PipelineRun.started_at.desc(),
                PipelineRun.pipeline_run_id.desc(),
            )
            .limit(1)
        )

        candidate_run = self._session.scalar(
            select(CandidateRun)
            .where(
                CandidateRun.exchange_code == exchange,
                CandidateRun.as_of_date == report_date,
            )
            .order_by(CandidateRun.run_id.desc())
            .limit(1)
        )

        analysis_run = self._session.scalar(
            select(CandidateAnalysisRun)
            .where(
                CandidateAnalysisRun.exchange_code == exchange,
                CandidateAnalysisRun.created_at >= start_at,
                CandidateAnalysisRun.created_at <= end_at,
            )
            .order_by(
                CandidateAnalysisRun.analysis_run_id.desc()
            )
            .limit(1)
        )

        ai_candidate_count = 0
        if analysis_run is not None:
            ai_candidate_count = self._session.scalar(
                select(func.count())
                .select_from(CandidateAnalysisResult)
                .where(
                    CandidateAnalysisResult.analysis_run_id
                    == analysis_run.analysis_run_id
                )
            ) or 0

        position_plans = list(
            self._session.scalars(
                select(PositionPlanEntity).where(
                    PositionPlanEntity.exchange_code == exchange,
                    PositionPlanEntity.created_at >= start_at,
                    PositionPlanEntity.created_at <= end_at,
                )
            )
        )

        approved_plans = [
            item
            for item in position_plans
            if item.approved
        ]

        total_order_amount = sum(
            (
                Decimal(item.order_amount)
                for item in approved_plans
            ),
            ZERO,
        ).quantize(Decimal("0.01"))

        realized_profit_loss = ZERO
        unrealized_profit_loss = ZERO
        valuation_details: list[dict[str, Any]] = []

        if paper_account_id is not None:
            account = self._session.get(
                PaperAccount,
                paper_account_id,
            )
            if account is not None:
                realized_profit_loss = Decimal(
                    account.realized_profit_loss
                )

                positions = list(
                    self._session.scalars(
                        select(PaperPosition).where(
                            PaperPosition.account_id
                            == paper_account_id,
                            PaperPosition.quantity > 0,
                        )
                    )
                )

                for position in positions:
                    key = (
                        f"{position.exchange_code}:"
                        f"{position.symbol}"
                    )
                    current_price = (
                        current_prices or {}
                    ).get(key)

                    if current_price is None:
                        continue

                    market_value = (
                        Decimal(position.quantity)
                        * current_price
                    )
                    cost_value = (
                        Decimal(position.quantity)
                        * Decimal(
                            position.average_entry_price
                        )
                    )
                    pnl = market_value - cost_value
                    unrealized_profit_loss += pnl

                    valuation_details.append(
                        {
                            "key": key,
                            "quantity": str(
                                position.quantity
                            ),
                            "average_entry_price": str(
                                position.average_entry_price
                            ),
                            "current_price": str(
                                current_price
                            ),
                            "unrealized_profit_loss": str(
                                pnl.quantize(
                                    Decimal("0.01")
                                )
                            ),
                        }
                    )

        unrealized_profit_loss = (
            unrealized_profit_loss.quantize(
                Decimal("0.01")
            )
        )

        pipeline_status = (
            pipeline.status_code
            if pipeline is not None
            else None
        )

        selected_candidate_count = (
            candidate_run.selected_count
            if candidate_run is not None
            else 0
        )

        summary_text = self._build_summary(
            report_date=report_date,
            exchange_code=exchange,
            pipeline_status=pipeline_status,
            selected_candidate_count=(
                selected_candidate_count
            ),
            ai_candidate_count=ai_candidate_count,
            approved_position_count=len(
                approved_plans
            ),
            total_order_amount=total_order_amount,
            realized_profit_loss=realized_profit_loss,
            unrealized_profit_loss=(
                unrealized_profit_loss
            ),
        )

        incident_summary = (
            self._build_incident_summary(failed_jobs)
        )

        report = DailyOperationsReport(
            report_date=report_date,
            exchange_code=exchange,
            pipeline_status_code=pipeline_status,
            job_success_count=job_success_count,
            job_failed_count=job_failed_count,
            selected_candidate_count=(
                selected_candidate_count
            ),
            ai_candidate_count=ai_candidate_count,
            approved_position_count=len(
                approved_plans
            ),
            total_order_amount=total_order_amount,
            realized_profit_loss=realized_profit_loss,
            unrealized_profit_loss=(
                unrealized_profit_loss
            ),
            summary_text=summary_text,
            incident_summary=incident_summary,
            details={
                "failed_jobs": failed_jobs,
                "valuation": valuation_details,
                "pipeline_run_id": (
                    pipeline.pipeline_run_id
                    if pipeline is not None
                    else None
                ),
                "candidate_run_id": (
                    candidate_run.run_id
                    if candidate_run is not None
                    else None
                ),
                "analysis_run_id": (
                    analysis_run.analysis_run_id
                    if analysis_run is not None
                    else None
                ),
                "rule_candidate_top_n": (
                    selected_candidate_count
                ),
                "ai_selected_top_n": ai_candidate_count,
                "next_trading_day_notes": [
                    "장 개시 전 Kill Switch / 계좌 sync 확인",
                    "전일 실패 Job 재실행 여부 검토",
                    "실전 전환 활성화 상태 재확인",
                    "시세 freshness와 Outbox 적체 확인",
                ],
            },
        )

        return self._repository.save(report)

    @staticmethod
    def _build_summary(
        *,
        report_date: date,
        exchange_code: str,
        pipeline_status: str | None,
        selected_candidate_count: int,
        ai_candidate_count: int,
        approved_position_count: int,
        total_order_amount: Decimal,
        realized_profit_loss: Decimal,
        unrealized_profit_loss: Decimal,
    ) -> str:
        return (
            f"{report_date} {exchange_code} 운영 요약: "
            f"파이프라인={pipeline_status or 'NOT_RUN'}, "
            f"규칙 후보={selected_candidate_count}개, "
            f"AI 후보={ai_candidate_count}개, "
            f"승인 포지션 계획={approved_position_count}개, "
            f"계획 주문금액={total_order_amount}, "
            f"실현손익={realized_profit_loss}, "
            f"미실현손익={unrealized_profit_loss}"
        )

    @staticmethod
    def _build_incident_summary(
        failed_jobs: list[dict[str, Any]],
    ) -> str | None:
        if not failed_jobs:
            return None

        messages = [
            (
                f"{item['job_name']}: "
                f"{item['error_message'] or 'unknown error'}"
            )
            for item in failed_jobs
        ]

        return " | ".join(messages)[:4000]
