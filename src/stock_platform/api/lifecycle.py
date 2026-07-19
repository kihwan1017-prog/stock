from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text

from stock_platform.broker.kiwoom.ws_manager import (
    kiwoom_order_websocket_manager,
)
from stock_platform.broker.recovery_runtime import (
    broker_recovery_manager,
)
from stock_platform.common.logger import (
    configure_logging,
    logger,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.outbox_runtime import (
    order_outbox_scheduler,
)
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.persistence import (
    market_data_persistence_worker,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)
from stock_platform.risk_engine.daily_loss_scheduler import (
    daily_loss_monitor_scheduler,
)
from stock_platform.position.exit_monitor_scheduler import (
    position_exit_monitor_scheduler,
)
from stock_platform.notification.telegram_polling import (
    telegram_ops_scheduler,
)
from stock_platform.strategy_deployment.performance_monitor_scheduler import (
    deployment_performance_monitor_scheduler,
)
from stock_platform.strategy_deployment.pipeline_scheduler import (
    strategy_deployment_pipeline_scheduler,
)
from stock_platform.strategy_deployment.policy_scheduler import (
    strategy_approval_scheduler,
)
from stock_platform.strategy_deployment.reload_scheduler import (
    strategy_runtime_reload_scheduler,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)

StartupStep = Callable[[], Awaitable[Any]]


def validate_startup_settings() -> None:
    """필수 설정을 로드하고 기본값을 검증한다."""

    settings = get_settings()
    try:
        settings.validate_startup()
    except ValueError as exc:
        # JWT 등 설정 안내를 터미널에서 읽기 쉽게 출력
        logger.error(
            "Startup settings validation failed",
            detail=str(exc),
        )
        raise
    logger.info(
        "Startup settings loaded",
        app_env=settings.app_env,
        app_name=settings.app_name,
        kiwoom_use_mock=settings.kiwoom_use_mock,
        kiwoom_live_order_enabled=settings.kiwoom_live_order_enabled,
        jwt_secret_configured=bool(settings.jwt_secret.strip()),
    )


async def verify_database_connection() -> None:
    """PostgreSQL 연결 가능 여부를 확인한다."""

    session = get_session_factory()()

    try:
        session.execute(text("SELECT 1"))
    finally:
        session.close()


async def bootstrap_auth_admin() -> None:
    """사용자가 없을 때 env 기반 최초 관리자를 생성한다."""

    from stock_platform.auth.repository import AuthRepository
    from stock_platform.auth.service import AuthService

    settings = get_settings()
    if not settings.jwt_secret.strip():
        logger.warning(
            "JWT_SECRET 미설정 — 로그인 API는 JWT_SECRET 설정 후 사용 가능"
        )
        return

    session = get_session_factory()()
    try:
        user = AuthService(
            repository=AuthRepository(session),
            settings=settings,
        ).ensure_bootstrap_admin()
        if user is not None:
            session.commit()
            logger.info(
                "Bootstrap admin created",
                username=user.username,
            )
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class ApplicationLifecycle:
    """FastAPI lifespan 시작·종료 순서를 단일 진입점으로 관리한다."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def startup(self) -> None:
        async with self._lock:
            if self._started:
                logger.info(
                    "Application startup skipped: already started"
                )
                return

            configure_logging()
            logger.info("Application startup begin")

            await self._run_critical(
                "settings validation",
                self._startup_settings,
            )
            await self._run_critical(
                "database check",
                verify_database_connection,
            )
            await self._run_optional(
                "auth bootstrap admin",
                bootstrap_auth_admin,
            )
            await self._run_optional(
                "broker recovery",
                broker_recovery_manager.recover,
            )
            await self._run_optional(
                "strategy runtime load",
                self._startup_strategy_runtime,
            )
            await self._run_phase(
                "scheduler startup",
                self._start_schedulers,
            )
            await self._run_optional(
                "market data persistence",
                market_data_persistence_worker.start,
            )

            self._started = True
            logger.info("Application startup complete")
            await self._publish_lifecycle_event(
                "SYSTEM_START",
                "Application started",
            )

    async def shutdown(self) -> None:
        async with self._lock:
            if not self._started:
                logger.info(
                    "Application shutdown skipped: not started"
                )
                return

            logger.info("Application shutdown begin")
            await self._publish_lifecycle_event(
                "SYSTEM_STOP",
                "Application stopping",
            )

            await self._run_phase(
                "scheduler shutdown",
                self._shutdown_schedulers,
            )
            await self._run_phase(
                "strategy runtime clear",
                dynamic_strategy_runtime_manager.clear,
            )
            await self._run_phase(
                "realtime services shutdown",
                self._shutdown_realtime_services,
            )

            self._started = False
            logger.info("Application shutdown complete")

    async def _startup_settings(self) -> None:
        validate_startup_settings()

    async def _startup_strategy_runtime(self) -> None:
        settings = get_settings()

        try:
            await dynamic_strategy_runtime_manager.initialize(
                market_code=settings.realtime_strategy_market_code,
                symbol=settings.realtime_strategy_symbol_or_none,
            )
        except LookupError as exc:
            # 활성 PAPER 전략이 없으면 로컬 기동에서 흔함 — 치명 아님
            logger.warning(
                "strategy_runtime_load_skipped",
                reason=str(exc),
            )

    async def _start_schedulers(self) -> None:
        daily_loss_monitor_scheduler.start()
        position_exit_monitor_scheduler.start()
        telegram_ops_scheduler.start()
        strategy_runtime_reload_scheduler.start()
        strategy_approval_scheduler.start()
        strategy_deployment_pipeline_scheduler.start()
        deployment_performance_monitor_scheduler.start()
        order_outbox_scheduler.start()

    async def _shutdown_schedulers(self) -> None:
        await order_outbox_scheduler.shutdown()
        await deployment_performance_monitor_scheduler.shutdown()
        await strategy_deployment_pipeline_scheduler.shutdown()
        await strategy_approval_scheduler.shutdown()
        await strategy_runtime_reload_scheduler.shutdown()
        await telegram_ops_scheduler.shutdown()
        await position_exit_monitor_scheduler.shutdown()
        await daily_loss_monitor_scheduler.shutdown()

    async def _publish_lifecycle_event(
        self,
        event_type: str,
        message: str,
    ) -> None:
        try:
            from stock_platform.notification.publisher import (
                notification_publisher,
            )

            # Telegram 지연이 Startup/Shutdown을 막지 않도록 타임아웃
            await asyncio.wait_for(
                notification_publisher.publish_async(
                    event_type=event_type,
                    title=event_type.replace("_", " ").title(),
                    message=message,
                    detail={"source": "ApplicationLifecycle"},
                ),
                timeout=3.0,
            )
        except TimeoutError:
            logger.warning(
                "lifecycle_notification_timeout",
                event_type=event_type,
            )
        except Exception as exc:
            logger.warning(
                "lifecycle_notification_failed",
                event_type=event_type,
                error=str(exc),
            )

    async def _shutdown_realtime_services(self) -> None:
        await realtime_execution_runner.stop()
        await realtime_strategy_runner.stop()
        await realtime_trading_scheduler.shutdown()
        await kiwoom_order_websocket_manager.stop()
        await realtime_manager.stop_all()
        await market_data_persistence_worker.stop()

    async def _run_critical(
        self,
        phase_name: str,
        step: StartupStep,
    ) -> None:
        logger.info("Startup phase begin", phase=phase_name)

        try:
            await step()
        except Exception:
            logger.exception(
                "Startup phase failed",
                phase=phase_name,
            )
            raise

        logger.info("Startup phase complete", phase=phase_name)

    async def _run_optional(
        self,
        phase_name: str,
        step: StartupStep,
    ) -> None:
        logger.info("Startup phase begin", phase=phase_name)

        try:
            await step()
        except Exception as exc:
            # 선택 단계는 기동을 막지 않음. 전체 traceback은 debug로만.
            logger.warning(
                "Startup phase failed; continuing",
                phase=phase_name,
                error=str(exc),
            )
            logger.debug(
                "Startup phase failure detail",
                phase=phase_name,
                exc_info=True,
            )
            return

        logger.info("Startup phase complete", phase=phase_name)

    async def _run_phase(
        self,
        phase_name: str,
        step: StartupStep,
    ) -> None:
        logger.info("Lifecycle phase begin", phase=phase_name)

        try:
            await step()
        except Exception:
            logger.exception(
                "Lifecycle phase failed",
                phase=phase_name,
            )
            raise

        logger.info("Lifecycle phase complete", phase=phase_name)


application_lifecycle = ApplicationLifecycle()
