from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.job_models import JobRunHistory
from stock_platform.realtime.dashboard_models import (
    DashboardAccountSummary,
    DashboardTradingSummary,
    RealtimeDashboardSnapshot,
)
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_safety_guard,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    PaperTrade,
)
from stock_platform.trading.models import PaperOrder


ZERO = Decimal("0")


class RealtimeDashboardService:
    """실시간 자동매매 운영 상태를 하나의 스냅샷으로 집계한다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()

    async def build(
        self,
        *,
        account_id: int = 1,
        recent_limit: int = 20,
    ) -> RealtimeDashboardSnapshot:
        if account_id <= 0:
            raise ValueError(
                "account_id must be greater than zero"
            )

        if recent_limit <= 0 or recent_limit > 100:
            raise ValueError(
                "recent_limit must be between 1 and 100"
            )

        infrastructure = {
            "database": self._database_status(),
            "ollama": {
                "base_url": (
                    self._settings.ollama_base_url
                ),
                "model": self._settings.ollama_model,
            },
            "scheduler": self._scheduler_status(),
        }

        realtime_status = {
            "market_data": (
                await realtime_manager.status()
            ),
            "strategy": (
                realtime_strategy_runner.status()
            ),
            "execution": (
                realtime_execution_runner.status()
            ),
            "safety": {
                "daily_realized_loss": str(
                    realtime_safety_guard
                    .daily_realized_loss
                ),
            },
        }

        account = self._account_summary(
            account_id=account_id
        )

        trading = self._trading_summary(
            account_id=account_id,
            recent_limit=recent_limit,
        )

        return RealtimeDashboardSnapshot(
            generated_at=datetime.now(timezone.utc),
            application={
                "name": self._settings.app_name,
                "environment": self._settings.app_env,
                "timezone": (
                    self._settings.app_timezone
                ),
            },
            infrastructure=infrastructure,
            realtime=realtime_status,
            account=account,
            trading=trading,
            ai={
                "model": self._settings.ollama_model,
                "base_url": (
                    self._settings.ollama_base_url
                ),
                "latest_ai_job": (
                    self._latest_ai_job()
                ),
            },
            recent_errors=self._recent_errors(
                limit=recent_limit
            ),
        )

    def _database_status(self) -> dict[str, Any]:
        try:
            result = self._session.execute(
                text("SELECT 1")
            ).scalar_one()

            return {
                "status": "UP",
                "result": result,
            }
        except Exception as exc:
            self._session.rollback()
            return {
                "status": "DOWN",
                "error": str(exc),
            }

    @staticmethod
    def _scheduler_status() -> dict[str, Any]:
        scheduler = (
            realtime_trading_scheduler.scheduler
        )

        return {
            "running": scheduler.running,
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": (
                        job.next_run_time
                        if scheduler.running
                        else None
                    ),
                }
                for job in scheduler.get_jobs()
            ],
        }

    def _account_summary(
        self,
        *,
        account_id: int,
    ) -> DashboardAccountSummary | None:
        account = self._session.get(
            PaperAccount,
            account_id,
        )

        if account is None:
            return None

        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id
                    == account_id,
                    PaperPosition.quantity > 0,
                )
            )
        )

        total_position_value = sum(
            (
                Decimal(position.quantity)
                * Decimal(
                    position.average_entry_price
                )
                for position in positions
            ),
            ZERO,
        ).quantize(Decimal("0.01"))

        return DashboardAccountSummary(
            account_id=account_id,
            cash_balance=Decimal(
                account.available_cash
            ),
            realized_profit_loss=Decimal(
                account.realized_profit_loss
            ),
            open_position_count=len(positions),
            total_position_value=(
                total_position_value
            ),
        )

    def _trading_summary(
        self,
        *,
        account_id: int,
        recent_limit: int,
    ) -> DashboardTradingSummary:
        today = date.today()
        start_at = datetime.combine(
            today,
            time.min,
            tzinfo=timezone.utc,
        )
        end_at = datetime.combine(
            today,
            time.max,
            tzinfo=timezone.utc,
        )

        today_order_count = self._session.scalar(
            select(func.count())
            .select_from(PaperOrder)
            .where(
                PaperOrder.created_at >= start_at,
                PaperOrder.created_at <= end_at,
            )
        ) or 0

        today_trade_count = self._session.scalar(
            select(func.count())
            .select_from(PaperTrade)
            .where(
                PaperTrade.account_id == account_id,
                PaperTrade.traded_at >= start_at,
                PaperTrade.traded_at <= end_at,
            )
        ) or 0

        orders = list(
            self._session.scalars(
                select(PaperOrder)
                .order_by(
                    PaperOrder.created_at.desc(),
                    PaperOrder.order_id.desc(),
                )
                .limit(recent_limit)
            )
        )

        trades = list(
            self._session.scalars(
                select(PaperTrade)
                .where(
                    PaperTrade.account_id
                    == account_id
                )
                .order_by(
                    PaperTrade.traded_at.desc(),
                    PaperTrade.trade_id.desc(),
                )
                .limit(recent_limit)
            )
        )

        return DashboardTradingSummary(
            today_order_count=int(
                today_order_count
            ),
            today_trade_count=int(
                today_trade_count
            ),
            recent_orders=[
                {
                    "order_id": item.order_id,
                    "exchange_code": (
                        item.exchange_code
                    ),
                    "symbol": item.symbol,
                    "side": item.side,
                    "order_type": (
                        item.order_type
                    ),
                    "status_code": (
                        item.status_code
                    ),
                    "requested_quantity": str(
                        item.requested_quantity
                    ),
                    "requested_price": (
                        str(item.requested_price)
                        if item.requested_price
                        is not None
                        else None
                    ),
                    "filled_quantity": str(
                        item.filled_quantity
                    ),
                    "created_at": (
                        item.created_at
                    ),
                }
                for item in orders
            ],
            recent_trades=[
                {
                    "trade_id": item.trade_id,
                    "order_id": item.order_id,
                    "exchange_code": (
                        item.exchange_code
                    ),
                    "symbol": item.symbol,
                    "side": item.side,
                    "quantity": str(
                        item.quantity
                    ),
                    "fill_price": str(
                        item.fill_price
                    ),
                    "trade_amount": str(
                        item.trade_amount
                    ),
                    "realized_profit_loss": str(
                        item.realized_profit_loss
                    ),
                    "traded_at": item.traded_at,
                }
                for item in trades
            ],
        )

    def _latest_ai_job(self) -> dict[str, Any] | None:
        job = self._session.scalar(
            select(JobRunHistory)
            .where(
                JobRunHistory.job_name.in_(
                    [
                        "ai_orchestration",
                        "realtime_ai_review",
                    ]
                )
            )
            .order_by(
                JobRunHistory.started_at.desc(),
                JobRunHistory.job_run_id.desc(),
            )
            .limit(1)
        )

        if job is None:
            return None

        return {
            "job_run_id": job.job_run_id,
            "job_name": job.job_name,
            "status_code": job.status_code,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error_message": job.error_message,
            "result_payload": job.result_payload,
        }

    def _recent_errors(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(JobRunHistory)
                .where(
                    JobRunHistory.status_code
                    == "FAILED"
                )
                .order_by(
                    JobRunHistory.started_at.desc(),
                    JobRunHistory.job_run_id.desc(),
                )
                .limit(limit)
            )
        )

        errors = [
            {
                "source": "JOB",
                "job_run_id": row.job_run_id,
                "job_name": row.job_name,
                "error_message": (
                    row.error_message
                ),
                "occurred_at": row.started_at,
            }
            for row in rows
        ]

        execution_error = (
            realtime_execution_runner
            .status()
            .get("last_error")
        )
        strategy_error = (
            realtime_strategy_runner
            .status()
            .get("last_error")
        )

        if execution_error:
            errors.insert(
                0,
                {
                    "source": "REALTIME_EXECUTION",
                    "error_message": execution_error,
                    "occurred_at": None,
                },
            )

        if strategy_error:
            errors.insert(
                0,
                {
                    "source": "REALTIME_STRATEGY",
                    "error_message": strategy_error,
                    "occurred_at": None,
                },
            )

        return errors[:limit]
