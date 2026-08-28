from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
)
from stock_platform.realtime.execution_scope import (
    signal_matches_execution_scope,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.safety_guard import (
    RealtimeOrderSafetyGuard,
)
from stock_platform.realtime.signal_bus import (
    RealtimeSignalBus,
)


logger = structlog.get_logger(__name__)


class RealtimeExecutionRunner:
    """실시간 신호를 Risk Engine과 Safety Guard를 거쳐 실행한다."""

    def __init__(
        self,
        *,
        signal_bus: RealtimeSignalBus,
        config: RealtimeExecutionConfig,
        safety_guard: RealtimeOrderSafetyGuard,
        history_size: int = 500,
    ) -> None:
        self._signal_bus = signal_bus
        self._config = config
        self._safety_guard = safety_guard
        self._task: asyncio.Task | None = None
        self._running = False
        self._processed_count = 0
        self._executed_count = 0
        self._blocked_count = 0
        self._failed_count = 0
        self._last_error: str | None = None
        self._started_at: datetime | None = None
        self._heartbeat_at: datetime | None = None
        self._history: deque[dict[str, Any]] = deque(
            maxlen=history_size
        )

    async def start(self) -> dict:
        if self._task is not None and not self._task.done():
            return {
                "already_running": True,
                **self.status(),
            }
        self._task = None

        uba = getattr(self._config, "user_broker_account_id", None) or 0
        broker = str(getattr(self._config, "broker_code", "") or "PAPER")
        self._task = asyncio.create_task(
            self.run_forever(),
            name=f"realtime-execution-runner-{broker}-{uba}",
        )
        # 태스크가 _running 플래그를 올릴 때까지 짧게 양보
        await asyncio.sleep(0)
        return self.status()

    def _execute_signal(self, signal) -> Any:
        """동기 execute는 스레드에서만 호출한다. Session은 이 스레드에서 연다.

        SKIP/REJECT 경로의 EXECUTOR_* append-only trace는 flush만 되고
        commit이 없으면 session.close() 시 롤백되어 유실된다.
        execute 성공 반환 후 반드시 commit한다.
        """

        session = get_session_factory()()
        try:
            result = RiskIntegratedRealtimeOrderExecutor(
                session=session,
                execution_config=self._config,
                safety_guard=self._safety_guard,
            ).execute(signal)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def run_forever(self) -> None:
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._heartbeat_at = self._started_at

        try:
            async for signal in self._signal_bus.subscribe():
                self._heartbeat_at = datetime.now(timezone.utc)
                # 다른 UBA/broker 신호는 이 Runner가 주문하지 않는다.
                if not signal_matches_execution_scope(signal, self._config):
                    self._trace_scope_filter_reject(signal)
                    continue
                self._processed_count += 1
                try:
                    # 이벤트 루프를 막지 않기 위해 동기 주문 경로를 스레드로 보낸다.
                    result = await asyncio.to_thread(
                        self._execute_signal, signal
                    )

                    if result.order_status == "SKIPPED":
                        self._blocked_count += 1
                    else:
                        self._executed_count += 1

                    self._history.appendleft(
                        self._to_dict(result)
                    )
                    self._last_error = None

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._failed_count += 1
                    self._last_error = str(exc)
                    logger.exception(
                        "realtime_execution_failed",
                        exchange_code=(
                            signal.exchange_code
                        ),
                        symbol=signal.symbol,
                        action=signal.action.value,
                    )
        finally:
            self._running = False

    def _trace_scope_filter_reject(self, signal) -> None:
        """provenance 있는 BUY가 이 Runner scope와 안 맞으면 durable reject."""

        tid = getattr(signal, "execution_trace_id", None)
        if not tid:
            return
        action = getattr(signal, "action", None)
        action_val = getattr(action, "value", action)
        if str(action_val or "").upper() != "BUY":
            return
        uba = getattr(signal, "user_broker_account_id", None) or getattr(
            signal, "account_id", None
        )
        if not uba:
            return
        try:
            from stock_platform.operation.upbit_entry_execution_trace.constants import (
                DECISION_REJECT,
                STAGE_SIGNAL_FILTER_REJECTED,
            )
            from stock_platform.operation.upbit_entry_execution_trace.service import (
                append_stage_fail_open,
            )

            session = get_session_factory()()
            try:
                append_stage_fail_open(
                    session,
                    execution_trace_id=str(tid),
                    user_broker_account_id=int(uba),
                    symbol=str(getattr(signal, "symbol", "") or "").upper(),
                    stage=STAGE_SIGNAL_FILTER_REJECTED,
                    decision=DECISION_REJECT,
                    reason_code="EXECUTION_SCOPE_MISMATCH",
                    selection_id=getattr(signal, "candidate_selection_id", None),
                    candidate_id=getattr(signal, "candidate_id", None),
                    waiting_id=getattr(signal, "waiting_id", None),
                    strategy_id=getattr(signal, "strategy_id", None),
                    lifecycle_kind=getattr(signal, "lifecycle_kind", None)
                    or "INITIAL",
                    signal_id=getattr(signal, "signal_id", None),
                    commit=True,
                )
                session.commit()
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            return

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except (asyncio.CancelledError, TimeoutError):
            pass
        finally:
            self._task = None
            self._running = False

    def status(self) -> dict:
        started = self._started_at
        heartbeat = self._heartbeat_at
        return {
            "running": self._running,
            "mode": self._config.mode.value,
            "account_id": self._config.account_id,
            "broker_code": getattr(
                self._config, "broker_code", None
            ),
            "user_broker_account_id": (
                self._config.user_broker_account_id
            ),
            "started_at": (
                started.isoformat() if started is not None else None
            ),
            "heartbeat": (
                heartbeat.isoformat()
                if heartbeat is not None
                else None
            ),
            "signal_subscriber_count": (
                self._signal_bus.subscriber_count
            ),
            "order_amount": str(
                self._config.order_amount
            ),
            "processed_count": self._processed_count,
            "executed_count": self._executed_count,
            "blocked_count": self._blocked_count,
            "failed_count": self._failed_count,
            "daily_realized_loss": str(
                self._safety_guard.daily_realized_loss
            ),
            "last_error": self._last_error,
        }

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    @staticmethod
    def _to_dict(result) -> dict[str, Any]:
        return {
            "exchange_code": result.exchange_code,
            "symbol": result.symbol,
            "signal_action": result.signal_action,
            "execution_mode": result.execution_mode,
            "order_id": result.order_id,
            "trade_id": result.trade_id,
            "order_status": result.order_status,
            "quantity": str(result.quantity),
            "order_price": str(result.order_price),
            "reason_code": result.reason_code,
            "executed_at": (
                result.executed_at.isoformat()
            ),
        }
