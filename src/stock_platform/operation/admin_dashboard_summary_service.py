from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.operation.audit_repository import (
    AuditEventRepository,
)
from stock_platform.operation.health_service import (
    SystemHealthService,
    check_database,
    check_ollama,
)
from stock_platform.operation.job_models import JobRunHistory
from stock_platform.operation.job_repository import (
    JobRunRepository,
)
from stock_platform.risk_engine.kill_switch_models import (
    KillSwitchStatus,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.strategy_deployment.entities import (
    StrategyDeploymentEntity,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    PaperTrade,
)


ZERO = Decimal("0")


class AdminDashboardSummaryService:
    """Admin Dashboard용 운영 요약 집계."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()
        self._health = SystemHealthService()
        self._prices = PriceDailyService(
            PriceDailyRepository(session)
        )

    async def build(
        self,
        *,
        account_id: int = 1,
        market_code: str = "KRX",
        mode_code: str = "PAPER",
        recent_limit: int = 10,
    ) -> dict[str, Any]:
        if account_id <= 0:
            raise ValueError("account_id must be > 0")
        if recent_limit < 1 or recent_limit > 100:
            raise ValueError(
                "recent_limit must be between 1 and 100"
            )

        health = await self._health.build()
        components = health.get("components") or {}

        kpis = self._build_kpis(account_id=account_id)
        kill = self._kill_switch_dict()
        scheduler = self._scheduler_dict(
            health_component=components.get("scheduler")
        )
        broker = self._broker_dict(
            health_component=components.get("kiwoom_rest")
        )
        ollama = self._component_status(
            components.get("ollama") or check_ollama()
        )
        database = self._component_status(
            components.get("database") or check_database()
        )

        strategy_status, execution_status = (
            self._runtime_status()
        )

        return {
            "generated_at": datetime.now(timezone.utc),
            "account_id": account_id,
            "market_code": market_code.upper(),
            "mode_code": mode_code.upper(),
            "kpis": kpis,
            "active_strategies": self._active_strategies(
                market_code=market_code,
                mode_code=mode_code,
            ),
            "scheduler": scheduler,
            "broker": broker,
            "risk": {
                "kill_switch": kill,
                "live_order_enabled": (
                    self._settings.kiwoom_live_order_enabled
                ),
                "strategy_runner": strategy_status,
                "execution_runner": execution_status,
            },
            "kill_switch": kill,
            "ollama": ollama,
            "database": database,
            "recent_errors": self._recent_errors(
                limit=recent_limit
            ),
            "recent_logs": self._recent_logs(
                limit=recent_limit
            ),
            "recent_jobs": self._recent_jobs(
                limit=recent_limit
            ),
            "health_status": health.get("status"),
        }

    def _build_kpis(self, *, account_id: int) -> dict[str, Any]:
        account = self._session.get(PaperAccount, account_id)
        if account is None:
            return {
                "total_equity": None,
                "available_cash": None,
                "today_pnl": None,
                "today_return_rate": None,
                "unrealized_pnl": None,
                "realized_pnl": None,
                "open_position_count": 0,
                "valuation_mode": "unavailable",
                "message": f"paper account {account_id} not found",
            }

        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == account_id,
                    PaperPosition.quantity > 0,
                )
            )
        )

        valuation_mode = "mark_to_market"
        market_value = ZERO
        unrealized = ZERO
        missing_prices: list[str] = []

        for position in positions:
            cost = (
                Decimal(position.quantity)
                * Decimal(position.average_entry_price)
            ).quantize(Decimal("0.01"))
            price = self._latest_close(
                exchange_code=position.exchange_code,
                symbol=position.symbol,
            )
            if price is None:
                missing_prices.append(
                    f"{position.exchange_code}:{position.symbol}"
                )
                market_value += cost
                continue
            mv = (
                Decimal(position.quantity) * price
            ).quantize(Decimal("0.01"))
            market_value += mv
            unrealized += (mv - cost).quantize(
                Decimal("0.01")
            )

        if missing_prices and positions:
            if len(missing_prices) == len(positions):
                valuation_mode = "cost_basis"
                unrealized = ZERO
            else:
                valuation_mode = "partial_mark_to_market"

        available_cash = Decimal(account.available_cash)
        total_equity = (
            available_cash + market_value
        ).quantize(Decimal("0.01"))
        realized = Decimal(account.realized_profit_loss)
        today_pnl = self._today_realized_pnl(account_id)
        prior_equity = (
            total_equity - today_pnl
        ).quantize(Decimal("0.01"))
        if prior_equity > ZERO:
            today_return_rate = (
                today_pnl / prior_equity * Decimal("100")
            ).quantize(Decimal("0.0001"))
        else:
            today_return_rate = ZERO

        return {
            "total_equity": str(total_equity),
            "available_cash": str(available_cash),
            "position_market_value": str(
                market_value.quantize(Decimal("0.01"))
            ),
            "today_pnl": str(today_pnl),
            "today_return_rate": str(today_return_rate),
            "unrealized_pnl": str(
                unrealized.quantize(Decimal("0.01"))
            ),
            "realized_pnl": str(
                realized.quantize(Decimal("0.01"))
            ),
            "open_position_count": len(positions),
            "valuation_mode": valuation_mode,
            "missing_prices": missing_prices,
        }

    def _latest_close(
        self,
        *,
        exchange_code: str,
        symbol: str,
    ) -> Decimal | None:
        try:
            row = self._prices.get_latest(
                exchange_code, symbol
            )
        except InstrumentNotFoundError:
            return None
        except Exception:
            return None
        if row is None or row.close_price is None:
            return None
        return Decimal(row.close_price)

    def _today_realized_pnl(self, account_id: int) -> Decimal:
        today = date.today()
        start_at = datetime.combine(
            today, time.min, tzinfo=timezone.utc
        )
        end_at = datetime.combine(
            today, time.max, tzinfo=timezone.utc
        )
        total = self._session.scalar(
            select(
                func.coalesce(
                    func.sum(PaperTrade.realized_profit_loss),
                    0,
                )
            ).where(
                PaperTrade.account_id == account_id,
                PaperTrade.traded_at >= start_at,
                PaperTrade.traded_at <= end_at,
            )
        )
        return Decimal(total or 0).quantize(Decimal("0.01"))

    def _active_strategies(
        self,
        *,
        market_code: str,
        mode_code: str,
    ) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(StrategyDeploymentEntity)
                .where(
                    StrategyDeploymentEntity.status_code
                    == "ACTIVE",
                    StrategyDeploymentEntity.market_code
                    == market_code.upper(),
                    StrategyDeploymentEntity.mode_code
                    == mode_code.upper(),
                )
                .order_by(
                    StrategyDeploymentEntity
                    .strategy_deployment_id.desc()
                )
                .limit(50)
            )
        )
        return [
            {
                "strategy_deployment_id": (
                    row.strategy_deployment_id
                ),
                "strategy_code": row.strategy_code,
                "market_code": row.market_code,
                "symbol": row.symbol,
                "mode_code": row.mode_code,
                "status_code": row.status_code,
                "activated_at": row.activated_at,
                "requested_by": row.requested_by,
            }
            for row in rows
        ]

    def _scheduler_dict(
        self,
        *,
        health_component: Any,
    ) -> dict[str, Any]:
        try:
            from stock_platform.realtime.session_runtime import (
                realtime_trading_scheduler,
            )

            scheduler = realtime_trading_scheduler.scheduler
            jobs = [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": (
                        job.next_run_time.isoformat()
                        if job.next_run_time is not None
                        else None
                    ),
                }
                for job in scheduler.get_jobs()
            ]
            running = bool(scheduler.running)
        except Exception as exc:
            return {
                "status": "DOWN",
                "running": False,
                "job_count": 0,
                "jobs": [],
                "message": str(exc),
                "health": health_component,
            }

        status = "UP" if running else "STOPPED"
        if isinstance(health_component, dict):
            configured = str(
                health_component.get("status", "")
            ).upper()
            if configured == "DISABLED":
                status = "DISABLED"

        return {
            "status": status,
            "running": running,
            "job_count": len(jobs),
            "jobs": jobs,
            "health": health_component,
        }

    def _broker_dict(
        self,
        *,
        health_component: Any,
    ) -> dict[str, Any]:
        settings = self._settings
        configured = bool(settings.kiwoom_app_key.strip())
        component = (
            health_component
            if isinstance(health_component, dict)
            else {}
        )
        return {
            "status": component.get(
                "status",
                "CONFIGURED" if configured else "SKIPPED",
            ),
            "provider": "KIWOOM",
            "environment": settings.app_env,
            "use_mock": settings.kiwoom_use_mock,
            "live_order_enabled": (
                settings.kiwoom_live_order_enabled
            ),
            "configured": configured,
        }

    def _kill_switch_dict(self) -> dict[str, Any]:
        state = KillSwitchService(self._session).get_state()
        payload = asdict(state)
        payload["status"] = (
            state.status.value
            if hasattr(state.status, "value")
            else str(state.status)
        )
        payload["active"] = (
            state.status == KillSwitchStatus.ACTIVE
        )
        return payload

    @staticmethod
    def _component_status(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {"status": "UNKNOWN"}
        return {
            "status": str(raw.get("status", "UNKNOWN")).upper(),
            **{
                key: value
                for key, value in raw.items()
                if key != "status"
            },
        }

    @staticmethod
    def _runtime_status() -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            from stock_platform.realtime.runtime import (
                realtime_execution_runner,
                realtime_strategy_runner,
            )

            return (
                realtime_strategy_runner.status(),
                realtime_execution_runner.status(),
            )
        except Exception as exc:
            down = {"status": "DOWN", "message": str(exc)}
            return down, down

    def _recent_errors(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(JobRunHistory)
                .where(JobRunHistory.status_code == "FAILED")
                .order_by(
                    JobRunHistory.started_at.desc(),
                    JobRunHistory.job_run_id.desc(),
                )
                .limit(limit)
            )
        )
        errors: list[dict[str, Any]] = [
            {
                "source": "JOB",
                "job_run_id": row.job_run_id,
                "job_name": row.job_name,
                "error_message": row.error_message,
                "occurred_at": row.started_at,
            }
            for row in rows
        ]

        try:
            from stock_platform.realtime.runtime import (
                realtime_execution_runner,
                realtime_strategy_runner,
            )

            execution_error = (
                realtime_execution_runner.status().get(
                    "last_error"
                )
            )
            strategy_error = (
                realtime_strategy_runner.status().get(
                    "last_error"
                )
            )
        except Exception:
            execution_error = None
            strategy_error = None

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

    def _recent_logs(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            rows = AuditEventRepository(
                self._session
            ).list_recent(limit=limit)
        except Exception:
            self._session.rollback()
            return []

        return [
            {
                "audit_event_id": row.audit_event_id,
                "event_type": row.event_type,
                "actor": row.actor,
                "detail": row.detail,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def _recent_jobs(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = JobRunRepository(self._session).list_recent(
            limit=limit
        )
        return [
            {
                "job_run_id": row.job_run_id,
                "job_name": row.job_name,
                "job_group": row.job_group,
                "status_code": row.status_code,
                "trigger_type": row.trigger_type,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "duration_ms": row.duration_ms,
                "error_message": row.error_message,
            }
            for row in rows
        ]
