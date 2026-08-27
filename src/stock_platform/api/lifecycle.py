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
from stock_platform.broker.upbit.ambiguous_resolution_scheduler import (
    upbit_ambiguous_order_resolution_scheduler,
)
from stock_platform.operation.market_session_job_scheduler import (
    market_session_job_scheduler,
)
from stock_platform.order.post_fill_verification_scheduler import (
    post_fill_verification_scheduler,
)
from stock_platform.trading.upbit_live_tracking_scheduler import (
    upbit_live_tracking_scheduler,
)
from stock_platform.settlement.upbit_daily_scheduler import (
    upbit_daily_settlement_scheduler,
)
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.persistence import (
    market_data_persistence_worker,
)
from stock_platform.realtime.runtime import (
    apply_realtime_paper_account_from_settings,
    realtime_execution_runner_manager,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)
from stock_platform.risk_engine.daily_loss_scheduler import (
    daily_loss_monitor_scheduler,
)
from stock_platform.broker.recovery_scheduler import (
    broker_recovery_scheduler,
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

    from stock_platform.auth.rbac_repository import RbacRepository
    from stock_platform.auth.repository import AuthRepository
    from stock_platform.auth.role_sync import backfill_missing_user_roles
    from stock_platform.auth.service import AuthService

    settings = get_settings()
    if not settings.jwt_secret.strip():
        logger.warning(
            "JWT_SECRET 미설정 — 로그인 API는 JWT_SECRET 설정 후 사용 가능"
        )
        return

    session = get_session_factory()()
    try:
        # 기존 JSONB-only admin 등 user_role 누락 치유
        healed = backfill_missing_user_roles(session)
        if healed:
            session.commit()
            logger.info(
                "RBAC user_role backfill completed",
                healed_users=healed,
            )

        user = AuthService(
            repository=AuthRepository(session),
            settings=settings,
            rbac_repository=RbacRepository(session),
        ).ensure_bootstrap_admin()
        if user is not None:
            session.commit()
            logger.info(
                "Bootstrap admin created",
                username=user.username,
            )
        else:
            session.commit()
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
        self._scheduler_leader_lock = None

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
                "runtime startup policy (phase 1)",
                self._startup_runtime_policy_phase1,
            )
            await self._run_optional(
                "auth bootstrap admin",
                bootstrap_auth_admin,
            )
            await self._run_optional(
                "ai provider manager bootstrap",
                self._startup_ai_provider_manager,
            )
            await self._run_optional(
                "ai execution recovery",
                self._startup_ai_execution_recovery,
            )
            await self._run_optional(
                "broker recovery",
                self._startup_broker_recovery,
            )
            await self._run_optional(
                "strategy runtime load",
                self._startup_strategy_runtime,
            )
            await self._run_optional(
                "runtime startup policy (phase 2)",
                self._startup_runtime_policy_phase2,
            )
            await self._run_optional(
                "unattended upbit lease/stack restore",
                self._startup_unattended_upbit_stack_restore,
            )
            await self._run_phase(
                "scheduler startup",
                self._start_schedulers,
            )
            await self._run_optional(
                "execution stack reconciliation",
                self._startup_execution_stack_reconciliation,
            )
            from stock_platform.operation.runtime_info import (
                mark_lifecycle_started,
            )

            mark_lifecycle_started()
            await self._run_optional(
                "market data persistence",
                market_data_persistence_worker.start,
            )
            await self._run_optional(
                "release configuration validation",
                self._startup_release_validation,
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
                "strategy runtime shutdown",
                dynamic_strategy_runtime_manager.shutdown_all,
            )
            await self._run_phase(
                "realtime services shutdown",
                self._shutdown_realtime_services,
            )

            self._started = False
            logger.info("Application shutdown complete")

    async def _startup_settings(self) -> None:
        validate_startup_settings()
        # import 시 읽지 않은 REALTIME_PAPER_ACCOUNT_ID 를 기동 시 반영
        account_id = apply_realtime_paper_account_from_settings()
        logger.info(
            "Realtime paper account applied",
            account_id=account_id,
        )

    async def _startup_runtime_policy_phase1(self) -> None:
        """STEP 10-2 — DB desired 로드 + LIVE/ARM Fail Closed."""

        session = get_session_factory()()
        try:
            from stock_platform.operation.startup_runtime_policy import (
                RuntimeStartupPolicy,
            )

            result = await RuntimeStartupPolicy(session).apply_phase1()
            session.commit()
            logger.info("runtime_startup_policy_phase1", **result)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _startup_runtime_policy_phase2(self) -> None:
        """STEP 10-2 — Runtime idle + Scheduler 조건부 복원."""

        session = get_session_factory()()
        try:
            from stock_platform.operation.startup_runtime_policy import (
                RuntimeStartupPolicy,
            )

            result = await RuntimeStartupPolicy(session).apply_phase2()
            session.commit()
            logger.info("runtime_startup_policy_phase2", **result)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _startup_unattended_upbit_stack_restore(self) -> None:
        """ACTIVE 24H lease가 있으면 LIVE/ARM 복구 후 UPBIT Runtime/Worker 복구.

        startup_forced_idle만 남기고 Worker STOPPED로 방치하는 GAP을 막는다.
        Scheduler 강제 RUN / REAL 주문 생성은 하지 않는다.
        """

        from stock_platform.trading.upbit_unattended_stack_restore import (
            restore_all_active_unattended_upbit_leases,
        )

        result = await restore_all_active_unattended_upbit_leases(
            actor="SYSTEM_UNATTENDED_STARTUP_RESTORE",
        )
        logger.info("unattended_upbit_stack_restore_startup", **result)

    async def _startup_execution_stack_reconciliation(self) -> None:
        """Scheduler 기동 후 canonical desired-state reconciliation.

        unattended restore는 scanner/feed보다 먼저 실행되므로
        startup 완료 시점에 heartbeat verify까지 수행한다.
        """

        from stock_platform.trading.autotrading_reliability_watchdog import (
            reset_startup_restore_backoff,
        )
        from stock_platform.trading.execution_stack_reconciliation import (
            reconcile_all_active_unattended_leases,
        )

        reset_startup_restore_backoff()
        result = await reconcile_all_active_unattended_leases(
            actor="STARTUP_EXECUTION_STACK_RECONCILE",
        )
        logger.info("execution_stack_reconciliation_startup", **result)

    async def _startup_release_validation(self) -> None:
        """Release v1.2 — Configuration / Fail-Closed / Lifecycle 검증."""

        from stock_platform.operation.release_operation_readiness import (
            run_startup_configuration_validation,
        )

        result = run_startup_configuration_validation()
        logger.info(
            "release_configuration_validation",
            overall=result.get("overall"),
            fail_count=result.get("fail_count"),
            warn_count=result.get("warn_count"),
            failed_checks=result.get("failed_checks"),
            live_submit_blocked=result.get("fail_closed", {}).get(
                "live_submit_blocked"
            ),
            lifecycle=result.get("lifecycle", {}).get("status"),
        )

    async def _startup_ai_execution_recovery(self) -> None:
        """STEP 11-5 — stale RUNNING/QUEUED → ABANDONED (자동 외부 재호출 0)."""

        from stock_platform.ai.execution.recovery import recover_stale_executions

        session = get_session_factory()()
        try:
            result = recover_stale_executions(session, actor="STARTUP")
            logger.info("ai_execution_recovery", **result)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "ai_execution_recovery_failed",
                error=type(exc).__name__,
            )
        finally:
            session.close()

    async def _startup_ai_provider_manager(self) -> None:
        """STEP 11-3 — DB SoT로 AIManager 부트스트랩 (외부 AI 자동 호출 없음)."""

        from stock_platform.ai.providers.registry_loader import (
            bootstrap_ai_manager_from_db,
        )

        source = bootstrap_ai_manager_from_db()
        logger.info("ai_provider_manager_startup", source=source)

    async def _startup_broker_recovery(self) -> None:
        """Startup — broker recover_all 금지 · orphan account_state만 local finalize.

        Scheduler cooldown 기준점(_startup_finished_at)은 성공·실패 공통 설정.
        """

        import asyncio
        from datetime import datetime, timezone

        try:
            await asyncio.wait_for(
                broker_recovery_manager.recover_startup_state_only(
                    actor="STARTUP",
                ),
                timeout=30.0,
            )
        except TimeoutError:
            logger.warning(
                "broker_recovery_startup_timeout",
                message=(
                    "Startup orphan-state finalization timed out; "
                    "continuing without recover_all"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "broker_recovery_startup_state_only_failed",
                error=type(exc).__name__,
            )
        finally:
            # Scheduler Cooldown 기준점 (성공·타임아웃 공통)
            broker_recovery_manager._startup_finished_at = (
                datetime.now(timezone.utc)
            )

    async def _startup_strategy_runtime(self) -> None:
        # STEP 8-5-5 — account_strategy_link 기반 Scope Runtime만 생성
        # STEP 8-5-9 — Hub dispatch 선행 (Consumer는 bootstrap 중 등록)
        try:
            from stock_platform.common.settings import get_settings
            from stock_platform.realtime.market_data_hub import (
                get_realtime_market_data_hub,
            )

            if bool(getattr(get_settings(), "realtime_hub_enabled", True)):
                hub = get_realtime_market_data_hub()
                if bool(
                    getattr(get_settings(), "realtime_auto_connect", True)
                ):
                    await hub.start_dispatch()
                    logger.info("realtime_hub_dispatch_started")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "realtime_hub_startup_error",
                error=str(exc),
            )

        try:
            result = await dynamic_strategy_runtime_manager.initialize()
            logger.info(
                "strategy_runtime_bootstrap",
                **{
                    k: result.get(k)
                    for k in (
                        "link_count",
                        "created_running",
                        "created_paused",
                        "global_krx_runtime_created",
                    )
                    if k in result
                },
                failed_count=len(result.get("failed") or []),
            )
        except LookupError as exc:
            logger.warning(
                "strategy_runtime_load_skipped",
                reason=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strategy_runtime_bootstrap_error",
                error=str(exc),
            )

        # Hub에 등록된 UPBIT subscription만 공개 시세 복구 (LIVE/Runtime RUN 없음)
        # AI Gate watch와도 분리 — Feed만 복구
        try:
            from stock_platform.realtime.upbit_quote_feed_restore import (
                ensure_upbit_quote_feed_from_hub,
            )

            feed_restore = await ensure_upbit_quote_feed_from_hub(
                source="LIFECYCLE_STARTUP",
            )
            logger.info("upbit_quote_feed_startup_restore", **feed_restore)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_quote_feed_startup_restore_error",
                error=str(exc),
            )

        # Feature Flag 기본 OFF — Paper Runner만 조건부 기동
        try:
            from stock_platform.realtime.execution_auto_start import (
                maybe_auto_start_runners,
            )

            auto = await maybe_auto_start_runners(
                source="LIFECYCLE_STARTUP",
                allow_live=False,
            )
            logger.info("realtime_auto_start_startup", **auto)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "realtime_auto_start_startup_error",
                error=str(exc),
            )

    async def _start_schedulers(self) -> None:
        settings = get_settings()

        # Paper Outbox Worker — Feature Flag 기본 OFF (LIVE와 claim 분리)
        from stock_platform.order.paper_unattended_runtime import (
            paper_fill_recovery_scheduler,
            paper_outbox_worker_runtime,
        )

        outbox_start = paper_outbox_worker_runtime.start()
        logger.info("paper_outbox_worker_startup", **outbox_start)
        recovery_start = paper_fill_recovery_scheduler.start()
        logger.info("paper_fill_recovery_startup", **recovery_start)

        # LIVE Outbox Worker — enabled만으로 polling 시작하지 않음 (Fail Closed)
        # LIVE_OUTBOX_WORKER_AUTO_START=true 일 때만 start(); 기본은 준비 상태만
        from stock_platform.order.live_outbox_worker_runtime import (
            live_outbox_worker_runtime,
        )

        if bool(getattr(settings, "live_outbox_worker_auto_start", False)):
            live_outbox_start = live_outbox_worker_runtime.start()
        else:
            live_outbox_start = {
                "started": False,
                "reason": "LIVE_OUTBOX_WORKER_AUTO_START_DISABLED",
                **live_outbox_worker_runtime.status(),
            }
        logger.info("live_outbox_worker_startup", **live_outbox_start)

        # ARM/Activation 만료 스캔 — 주문·Runtime 기동 없음
        try:
            from stock_platform.trading.live_session_expiry_runtime import (
                live_session_expiry_runtime,
            )

            expiry_start = live_session_expiry_runtime.start()
            logger.info("live_session_expiry_startup", **expiry_start)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "live_session_expiry_start_failed",
                error=str(exc)[:300],
            )

        # Autotrading reliability watchdog — PARTIAL_RESTORE 감지 + L1/L2 self-heal
        try:
            if bool(
                getattr(settings, "autotrading_reliability_watchdog_enabled", True)
            ):
                from stock_platform.trading.autotrading_reliability_watchdog import (
                    autotrading_reliability_watchdog,
                )

                wd_start = autotrading_reliability_watchdog.start()
                logger.info("autotrading_reliability_watchdog_startup", **wd_start)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "autotrading_reliability_watchdog_start_failed",
                error=str(exc)[:300],
            )

        # 레거시 무필터 Outbox는 Paper/LIVE 전용 worker Flag ON일 때 보조 기동하지 않음
        # (중복 claim 방지 — paper_only / live_only 단일 경로)
        if not bool(getattr(settings, "paper_outbox_worker_enabled", False)):
            logger.info(
                "legacy_order_outbox_scheduler_skipped",
                reason="PAPER_OUTBOX_WORKER_DISABLED",
            )
        # STEP 8-5-14 — DB Claim 기반이라 Leader Lock과 무관하게 항상 기동
        upbit_ambiguous_order_resolution_scheduler.start()
        # STEP 8-5-15 — 영속 Market Session Job Dispatcher/Reconcile 역시
        # DB Claim 기반이므로 Leader Lock과 무관하게 항상 기동
        market_session_job_scheduler.start()
        # UPBIT AI Market Analysis 주기 Job (Gate/실주문과 분리, enabled 플래그)
        try:
            from stock_platform.operation.upbit_ai_analysis_scheduler import (
                upbit_autotrading_ai_analysis_scheduler,
            )

            upbit_autotrading_ai_analysis_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_ai_analysis_scheduler_start_failed",
                error=str(exc)[:300],
            )
        # UPBIT Opportunity Scanner SHADOW_ONLY (enabled 플래그 기본 OFF)
        try:
            from stock_platform.operation.upbit_opportunity_scanner import (
                upbit_opportunity_scanner_scheduler,
            )

            upbit_opportunity_scanner_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_opportunity_scanner_start_failed",
                error=str(exc)[:300],
            )
        # UPBIT Shadow evaluator — ACTIVE window 자동 누적 (실주문 0)
        try:
            from stock_platform.operation.upbit_opportunity_shadow.evaluator_scheduler import (
                upbit_opportunity_shadow_evaluator_scheduler,
            )

            upbit_opportunity_shadow_evaluator_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_shadow_evaluator_start_failed",
                error=str(exc)[:300],
            )
        # Upbit Market Context Research (market/asset/F&G) — REAL 주문 무관
        try:
            from stock_platform.operation.upbit_market_context.research_collection_scheduler import (
                upbit_market_context_research_scheduler,
            )

            upbit_market_context_research_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_market_context_research_scheduler_start_failed",
                error=str(exc)[:300],
            )
        # STEP N2 — UPBIT News/Notice Collector (기본 OFF, Scanner/Shadow 격리)
        try:
            from stock_platform.news.collector_scheduler import (
                upbit_news_notice_collector_scheduler,
            )

            upbit_news_notice_collector_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_news_notice_collector_start_failed",
                error=str(exc)[:300],
            )
        # STEP N4 — UPBIT AI News Analysis (기본 OFF, INFORMATIONAL ONLY)
        try:
            from stock_platform.news.news_ai_analysis_scheduler import (
                upbit_news_ai_analysis_scheduler,
            )

            upbit_news_ai_analysis_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_news_ai_analysis_start_failed",
                error=str(exc)[:300],
            )
        # STEP N5 — UPBIT News Signal (기본 OFF, deterministic, LLM 금지)
        try:
            from stock_platform.news.news_signal_scheduler import (
                upbit_news_signal_scheduler,
            )

            upbit_news_signal_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_news_signal_start_failed",
                error=str(exc)[:300],
            )
        # STEP N6 — News Combined Shadow Experiment (기본 OFF, CONTROL 비수정)
        try:
            from stock_platform.operation.upbit_news_combined_shadow.scheduler import (
                upbit_news_combined_shadow_scheduler,
            )

            upbit_news_combined_shadow_scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_news_combined_shadow_start_failed",
                error=str(exc)[:300],
            )
        # STEP 8-5-16 — Upbit Daily Settlement (KRX Calendar 비연동 Cron)
        upbit_daily_settlement_scheduler.start()
        # STEP 8-8A — Post-Fill 재검증 (DB Claim)
        post_fill_verification_scheduler.start()
        upbit_live_tracking_scheduler.start()
        # STEP 8-11A — Recovery는 자체 enabled 플래그로 제어.
        # lifecycle cron 게이트/리더락과 무관하게 기동 (Outbox·Tracking과 동일 계열).
        # 주문 생성/Import/Conflict 승인 없음 — reconcile·조회만.
        try:
            broker_recovery_scheduler.start()
            session = get_session_factory()()
            try:
                from stock_platform.order.live_safety_audit import (
                    emit_live_safety_audit,
                )

                emit_live_safety_audit(
                    session,
                    event_type="RECOVERY_STARTUP_RESTORED",
                    actor="STARTUP",
                    run_id=None,
                    user_id=None,
                    account_id=None,
                    strategy_id=None,
                    detail={
                        "scheduler_status": broker_recovery_scheduler.status(),
                    },
                    commit=True,
                )
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "broker_recovery_scheduler_start_failed",
                error=str(exc)[:300],
            )
            session = get_session_factory()()
            try:
                from stock_platform.order.live_safety_audit import (
                    emit_live_safety_audit,
                )

                emit_live_safety_audit(
                    session,
                    event_type="RECOVERY_STARTUP_RESTORE_FAILED",
                    actor="STARTUP",
                    run_id=None,
                    user_id=None,
                    account_id=None,
                    strategy_id=None,
                    detail={"error": str(exc)[:300]},
                    commit=True,
                )
            finally:
                session.close()

        if not settings.lifecycle_scheduler_enabled:
            logger.info("lifecycle_scheduler_disabled")
            return

        if settings.scheduler_leader_lock_enabled:
            from stock_platform.scheduler.leader_lock import (
                try_acquire_lifecycle_scheduler_lock,
            )

            session = get_session_factory()()
            try:
                engine = session.get_bind()
            finally:
                session.close()
            leader = try_acquire_lifecycle_scheduler_lock(
                engine
            )
            self._scheduler_leader_lock = leader
            if not leader.acquired:
                logger.warning(
                    "lifecycle_scheduler_skipped_not_leader",
                    reason=leader.reason,
                )
                return
            logger.info(
                "lifecycle_scheduler_leader_acquired",
                reason=leader.reason,
            )

        daily_loss_monitor_scheduler.start()
        position_exit_monitor_scheduler.start()
        telegram_ops_scheduler.start()
        strategy_runtime_reload_scheduler.start()
        strategy_approval_scheduler.start()
        strategy_deployment_pipeline_scheduler.start()
        deployment_performance_monitor_scheduler.start()
        from stock_platform.operation.calendar_scheduler import (
            krx_trading_calendar_scheduler,
        )

        krx_trading_calendar_scheduler.start()
        # Startup Coverage 검사 (실패해도 기동 계속)
        try:
            await krx_trading_calendar_scheduler._run_coverage()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "krx_calendar_startup_coverage_failed",
                error=str(exc)[:300],
            )

    async def _shutdown_schedulers(self) -> None:
        from stock_platform.order.paper_unattended_runtime import (
            paper_fill_recovery_scheduler,
            paper_outbox_worker_runtime,
        )
        from stock_platform.order.live_outbox_worker_runtime import (
            live_outbox_worker_runtime,
        )
        from stock_platform.trading.live_session_expiry_runtime import (
            live_session_expiry_runtime,
        )
        from stock_platform.realtime.paper_price_feed import paper_price_feed

        await paper_outbox_worker_runtime.shutdown()
        await live_outbox_worker_runtime.shutdown()
        try:
            await live_session_expiry_runtime.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.trading.autotrading_reliability_watchdog import (
                autotrading_reliability_watchdog,
            )

            await autotrading_reliability_watchdog.shutdown()
        except Exception:  # noqa: BLE001
            pass
        await paper_fill_recovery_scheduler.shutdown()
        await paper_price_feed.shutdown()
        try:
            await order_outbox_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        await upbit_ambiguous_order_resolution_scheduler.shutdown()
        await market_session_job_scheduler.shutdown()
        try:
            from stock_platform.operation.upbit_ai_analysis_scheduler import (
                upbit_autotrading_ai_analysis_scheduler,
            )

            await upbit_autotrading_ai_analysis_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.operation.upbit_opportunity_scanner import (
                upbit_opportunity_scanner_scheduler,
            )

            await upbit_opportunity_scanner_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.operation.upbit_opportunity_shadow.evaluator_scheduler import (
                upbit_opportunity_shadow_evaluator_scheduler,
            )

            await upbit_opportunity_shadow_evaluator_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.operation.upbit_market_context.research_collection_scheduler import (
                upbit_market_context_research_scheduler,
            )

            await upbit_market_context_research_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.news.collector_scheduler import (
                upbit_news_notice_collector_scheduler,
            )

            await upbit_news_notice_collector_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.news.news_ai_analysis_scheduler import (
                upbit_news_ai_analysis_scheduler,
            )

            await upbit_news_ai_analysis_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.news.news_signal_scheduler import (
                upbit_news_signal_scheduler,
            )

            await upbit_news_signal_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.operation.upbit_news_combined_shadow.scheduler import (
                upbit_news_combined_shadow_scheduler,
            )

            await upbit_news_combined_shadow_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        await upbit_daily_settlement_scheduler.shutdown()
        await post_fill_verification_scheduler.shutdown()
        await upbit_live_tracking_scheduler.shutdown()
        await broker_recovery_scheduler.shutdown()
        try:
            from stock_platform.operation.calendar_scheduler import (
                krx_trading_calendar_scheduler,
            )

            await krx_trading_calendar_scheduler.shutdown()
        except Exception:  # noqa: BLE001
            pass
        await deployment_performance_monitor_scheduler.shutdown()
        await strategy_deployment_pipeline_scheduler.shutdown()
        await strategy_approval_scheduler.shutdown()
        await strategy_runtime_reload_scheduler.shutdown()
        await telegram_ops_scheduler.shutdown()
        await position_exit_monitor_scheduler.shutdown()
        await daily_loss_monitor_scheduler.shutdown()
        if self._scheduler_leader_lock is not None:
            self._scheduler_leader_lock.release()
            self._scheduler_leader_lock = None

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
        await realtime_execution_runner_manager.stop_all()
        await realtime_strategy_runner.stop()
        try:
            from stock_platform.realtime.market_data_hub import (
                get_realtime_market_data_hub,
            )

            await get_realtime_market_data_hub().shutdown()
        except Exception:  # noqa: BLE001
            pass
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
