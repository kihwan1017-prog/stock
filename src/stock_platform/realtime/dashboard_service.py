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
        account_id: int | None = None,
        recent_limit: int = 20,
    ) -> RealtimeDashboardSnapshot:
        # 미지정 시 설정 기본 계좌 (하드코딩 1 제거)
        resolved_account_id = (
            account_id
            if account_id is not None
            else self._settings.realtime_paper_account_id
        )
        if resolved_account_id <= 0:
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
            "auto_start_flags": {
                "master": bool(
                    getattr(
                        self._settings,
                        "realtime_execution_auto_start_enabled",
                        False,
                    )
                ),
                "paper": bool(
                    getattr(
                        self._settings,
                        "realtime_paper_auto_start_enabled",
                        False,
                    )
                ),
                "live": bool(
                    getattr(
                        self._settings,
                        "realtime_live_auto_start_enabled",
                        False,
                    )
                ),
                "kiwoom_live_order": bool(
                    getattr(
                        self._settings,
                        "kiwoom_live_order_enabled",
                        False,
                    )
                ),
                "upbit_live_order": bool(
                    getattr(
                        self._settings,
                        "upbit_live_order_enabled",
                        False,
                    )
                ),
                "paper_outbox_auto_fill": bool(
                    getattr(
                        self._settings,
                        "paper_outbox_auto_fill",
                        False,
                    )
                ),
                "paper_outbox_worker_enabled": bool(
                    getattr(
                        self._settings,
                        "paper_outbox_worker_enabled",
                        False,
                    )
                ),
                "paper_fill_recovery_enabled": bool(
                    getattr(
                        self._settings,
                        "paper_fill_recovery_enabled",
                        False,
                    )
                ),
                "paper_price_feed_enabled": bool(
                    getattr(
                        self._settings,
                        "paper_price_feed_enabled",
                        False,
                    )
                ),
            },
            "paper_unattended": self._paper_unattended_status(),
            "live_autotrading": self._live_autotrading_status(),
            "safety": {
                "daily_realized_loss": str(
                    realtime_safety_guard
                    .daily_realized_loss
                ),
            },
        }

        account = self._account_summary(
            account_id=resolved_account_id
        )

        trading = self._trading_summary(
            account_id=resolved_account_id,
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

    def _live_autotrading_status(self) -> dict[str, Any]:
        """LIVE Runtime / Order / Recovery / Broker WS 요약."""

        from stock_platform.realtime.execution_models import (
            RealtimeExecutionMode,
        )
        from stock_platform.realtime.live_runtime_control import (
            live_auto_start_allowed,
            live_order_flags_ready,
        )

        mode = str(realtime_execution_runner._config.mode)
        uba = getattr(
            realtime_execution_runner._config,
            "user_broker_account_id",
            None,
        )
        gate = live_auto_start_allowed(allow_live=True)
        kiwoom_ws: dict[str, Any] = {"running": False}
        try:
            from stock_platform.broker.kiwoom.ws_manager import (
                kiwoom_order_websocket_manager,
            )

            kiwoom_ws = kiwoom_order_websocket_manager.status()
        except Exception:  # noqa: BLE001
            pass

        live_orders = 0
        live_stalled = 0
        try:
            live_orders = int(
                self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.trading_order
                        WHERE metadata_payload->>'environment' = 'LIVE'
                          AND created_at >= NOW() - INTERVAL '1 day'
                        """
                    )
                ).scalar_one()
            )
            live_stalled = int(
                self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.trading_order
                        WHERE metadata_payload->>'environment' = 'LIVE'
                          AND status_code IN ('ACCEPTED', 'PENDING', 'SUBMITTING')
                          AND updated_at < NOW() - INTERVAL '5 minutes'
                        """
                    )
                ).scalar_one()
            )
        except Exception:  # noqa: BLE001
            pass

        recovery_paused = 0
        try:
            recovery_paused = int(
                self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM operation.broker_recovery_account_state
                        WHERE trading_paused IS TRUE
                        """
                    )
                ).scalar_one()
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "execution_mode": mode,
            "is_live_mode": mode == RealtimeExecutionMode.LIVE.value,
            "runner_running": bool(
                realtime_execution_runner.status().get("running")
            ),
            "user_broker_account_id": uba,
            "order_flags_ready": live_order_flags_ready(self._settings),
            "auto_start_gate": gate,
            "kiwoom_order_ws": {
                "running": bool(kiwoom_ws.get("running")),
                "connected": bool(kiwoom_ws.get("connected")),
            },
            "live_orders_24h": live_orders,
            "live_stalled_orders": live_stalled,
            "recovery_paused_accounts": recovery_paused,
            "shadow_mode_enabled": bool(
                getattr(self._settings, "live_shadow_mode_enabled", False)
            ),
            "dry_run_mode_enabled": bool(
                getattr(self._settings, "live_order_dry_run_enabled", False)
            ),
            "upbit": self._upbit_live_ops_slice(),
        }

    def _upbit_live_ops_slice(self) -> dict[str, Any]:
        """Upbit 시세 WS·원장·Recovery 요약 (실주문 호출 없음)."""

        quote_ws: dict[str, Any] = {"running": False}
        try:
            clients = getattr(realtime_manager, "_clients", {}) or {}
            upbit_obj = clients.get("UPBIT")
            upbit = upbit_obj.status() if upbit_obj is not None else {}
            quote_ws = {
                "running": bool(upbit_obj),
                "connected": bool(upbit.get("connected")),
                "received_count": upbit.get("received_count"),
                "reconnect_count": upbit.get("reconnect_count"),
                "last_error": upbit.get("last_error"),
            }
        except Exception:  # noqa: BLE001
            pass

        pipeline: dict[str, Any] = {}
        try:
            from stock_platform.trading.upbit_live_pipeline_readiness import (
                UpbitLivePipelineReadinessService,
            )

            pipeline = UpbitLivePipelineReadinessService(
                self._session
            ).evaluate()
        except Exception as exc:  # noqa: BLE001
            pipeline = {"error": type(exc).__name__}

        return {
            "quote_ws": quote_ws,
            "pipeline_ops_ready": bool(pipeline.get("ops_ready")),
            "pipeline_blockers": pipeline.get("blockers") or [],
            "pipeline_warnings": pipeline.get("warnings") or [],
            "candidate_path": (
                (pipeline.get("checks") or {})
                .get("modes", {})
                .get("candidate_path")
            ),
            "hooks": (pipeline.get("checks") or {}).get("hooks"),
            "recent_candidates_24h": (
                (pipeline.get("checks") or {}).get("recent_candidates_24h")
            ),
        }

    def _paper_unattended_status(self) -> dict[str, Any]:
        from stock_platform.order.paper_unattended_runtime import (
            paper_fill_recovery_scheduler,
            paper_outbox_worker_runtime,
        )
        from stock_platform.realtime.paper_price_feed import paper_price_feed

        pending = 0
        stalled = 0
        try:
            pending = int(
                self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.order_outbox o
                        WHERE o.status_code IN ('PENDING', 'RETRY')
                          AND o.user_broker_account_id IS NULL
                          AND COALESCE(
                            o.payload_json->>'environment', 'PAPER'
                          ) <> 'LIVE'
                        """
                    )
                ).scalar_one()
            )
            stalled = int(
                self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.trading_order t
                        WHERE t.status_code = 'ACCEPTED'
                          AND t.user_broker_account_id IS NULL
                          AND COALESCE(
                            t.metadata_payload->>'environment', 'PAPER'
                          ) <> 'LIVE'
                        """
                    )
                ).scalar_one()
            )
        except Exception:  # noqa: BLE001
            self._session.rollback()

        return {
            "runner": realtime_execution_runner.status(),
            "outbox_worker": paper_outbox_worker_runtime.status(),
            "fill_recovery": paper_fill_recovery_scheduler.status(),
            "price_feed": paper_price_feed.status(),
            "pending_outbox_count": pending,
            "stalled_accepted_count": stalled,
        }

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
