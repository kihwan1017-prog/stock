from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.account_factory import (
    build_kiwoom_account_client,
)
from stock_platform.broker.kiwoom.account_sync_service import (
    KiwoomAccountSyncService,
)
from stock_platform.broker.kiwoom.pending_factory import (
    build_kiwoom_pending_order_client,
)
from stock_platform.broker.kiwoom.pending_service import (
    KiwoomPendingOrderService,
)
from stock_platform.broker.kiwoom.ws_manager import (
    kiwoom_order_websocket_manager,
)
from stock_platform.broker.recovery_models import (
    RecoveryComponent,
    RecoveryRunResult,
    RecoveryStatus,
    RecoveryStepResult,
)
from stock_platform.broker.recovery_repository import (
    BrokerRecoveryRepository,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)


AsyncStep = Callable[[], Awaitable[dict[str, Any]]]


class BrokerRecoveryService:
    """
    서버 재시작 후 계좌·미체결·WebSocket·실시간 실행기를 순서대로 복구한다.
    """

    def __init__(
        self,
        *,
        session: Session,
        account_number: str,
        start_websocket: bool = True,
        start_realtime_runners: bool = False,
        start_scheduler: bool = True,
    ) -> None:
        self._session = session
        self._account_number = account_number
        self._start_websocket = start_websocket
        self._start_realtime_runners = (
            start_realtime_runners
        )
        self._start_scheduler = start_scheduler
        self._repository = BrokerRecoveryRepository(
            session
        )

    async def recover(self) -> RecoveryRunResult:
        started_at = datetime.now(timezone.utc)
        run_entity = self._repository.start_run()
        results: list[RecoveryStepResult] = []

        try:
            results.append(
                await self._run_step(
                    RecoveryComponent.KIWOOM_ACCOUNT,
                    self._sync_account,
                )
            )
            results.append(
                await self._run_step(
                    RecoveryComponent.KIWOOM_PENDING_ORDERS,
                    self._sync_pending_orders,
                )
            )

            if self._start_websocket:
                results.append(
                    await self._run_step(
                        RecoveryComponent
                        .KIWOOM_ORDER_WEBSOCKET,
                        self._start_order_websocket,
                    )
                )
            else:
                results.append(
                    self._skipped(
                        RecoveryComponent
                        .KIWOOM_ORDER_WEBSOCKET,
                        "WebSocket automatic start disabled",
                    )
                )

            if self._start_realtime_runners:
                results.append(
                    await self._run_step(
                        RecoveryComponent
                        .REALTIME_EXECUTION,
                        self._start_execution,
                    )
                )
                results.append(
                    await self._run_step(
                        RecoveryComponent
                        .REALTIME_STRATEGY,
                        self._start_strategy,
                    )
                )
            else:
                results.append(
                    self._skipped(
                        RecoveryComponent
                        .REALTIME_EXECUTION,
                        "Automatic execution start disabled",
                    )
                )
                results.append(
                    self._skipped(
                        RecoveryComponent
                        .REALTIME_STRATEGY,
                        "Automatic strategy start disabled",
                    )
                )

            if self._start_scheduler:
                results.append(
                    await self._run_step(
                        RecoveryComponent
                        .REALTIME_SCHEDULER,
                        self._start_scheduler_service,
                    )
                )
            else:
                results.append(
                    self._skipped(
                        RecoveryComponent
                        .REALTIME_SCHEDULER,
                        "Automatic scheduler start disabled",
                    )
                )

            finished_at = datetime.now(timezone.utc)
            required_failed = any(
                item.status == RecoveryStatus.FAILED
                for item in results[:2]
            )

            result = RecoveryRunResult(
                started_at=started_at,
                finished_at=finished_at,
                success=not required_failed,
                steps=results,
            )
            self._repository.finish_run(
                entity=run_entity,
                result=result,
            )
            return result

        except Exception as exc:
            self._session.rollback()
            self._repository.fail_run(
                entity=run_entity,
                error_message=str(exc),
            )
            raise

    async def _sync_account(self) -> dict[str, Any]:
        return await KiwoomAccountSyncService(
            session=self._session,
            account_client=build_kiwoom_account_client(),
        ).synchronize()

    async def _sync_pending_orders(
        self,
    ) -> dict[str, Any]:
        return await KiwoomPendingOrderService(
            session=self._session,
            client=build_kiwoom_pending_order_client(),
        ).synchronize(
            account_number=self._account_number
        )

    async def _start_order_websocket(
        self,
    ) -> dict[str, Any]:
        status = (
            kiwoom_order_websocket_manager.status()
        )
        if status.get("running"):
            return {
                "already_running": True,
                **status,
            }

        return await (
            kiwoom_order_websocket_manager.start()
        )

    async def _start_execution(
        self,
    ) -> dict[str, Any]:
        status = realtime_execution_runner.status()
        if status.get("running"):
            return {
                "already_running": True,
                **status,
            }

        return await realtime_execution_runner.start()

    async def _start_strategy(
        self,
    ) -> dict[str, Any]:
        status = realtime_strategy_runner.status()
        if status.get("running"):
            return {
                "already_running": True,
                **status,
            }

        return await realtime_strategy_runner.start()

    async def _start_scheduler_service(
        self,
    ) -> dict[str, Any]:
        scheduler = (
            realtime_trading_scheduler.scheduler
        )

        if scheduler.running:
            return {
                "already_running": True,
                "job_count": len(
                    scheduler.get_jobs()
                ),
            }

        realtime_trading_scheduler.start()

        return {
            "running": scheduler.running,
            "job_count": len(
                scheduler.get_jobs()
            ),
        }

    async def _run_step(
        self,
        component: RecoveryComponent,
        func: AsyncStep,
    ) -> RecoveryStepResult:
        started_at = datetime.now(timezone.utc)

        try:
            detail = await func()
            return RecoveryStepResult(
                component=component,
                status=RecoveryStatus.SUCCESS,
                message="Recovery step completed",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                detail=detail,
            )
        except Exception as exc:
            return RecoveryStepResult(
                component=component,
                status=RecoveryStatus.FAILED,
                message=str(exc),
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                detail={},
            )

    @staticmethod
    def _skipped(
        component: RecoveryComponent,
        message: str,
    ) -> RecoveryStepResult:
        now = datetime.now(timezone.utc)
        return RecoveryStepResult(
            component=component,
            status=RecoveryStatus.SKIPPED,
            message=message,
            started_at=now,
            finished_at=now,
            detail={},
        )
