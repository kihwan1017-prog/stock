"""UBA×broker 단위 RealtimeExecutionRunner 관리.

전역 LIVE binding을 공유하지 않는다.
한 Runner의 START/STOP/ERROR가 다른 Runner subscriber를 제거하지 않는다.
"""

from __future__ import annotations

from typing import Any

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.execution_runner import (
    RealtimeExecutionRunner,
)
from stock_platform.realtime.execution_scope import (
    PAPER_SCOPE_KEY,
    runner_scope_key,
)
from stock_platform.realtime.safety_guard import (
    RealtimeOrderSafetyGuard,
)
from stock_platform.realtime.safety_models import (
    RealtimeOrderSafetyConfig,
)
from stock_platform.realtime.signal_bus import (
    RealtimeSignalBus,
)


def clone_safety_guard(
    template: RealtimeOrderSafetyGuard,
    *,
    live_trading_enabled: bool,
    live_unlock_token: str = "",
) -> RealtimeOrderSafetyGuard:
    """Runner별 Safety Guard. daily loss/rate limit을 공유하지 않는다."""

    sc = template._config
    return RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_order_amount=sc.max_order_amount,
            max_daily_loss=sc.max_daily_loss,
            max_open_positions=sc.max_open_positions,
            duplicate_order_window_seconds=sc.duplicate_order_window_seconds,
            symbol_cooldown_seconds=sc.symbol_cooldown_seconds,
            max_orders_per_minute=sc.max_orders_per_minute,
            trading_start_time=sc.trading_start_time,
            trading_end_time=sc.trading_end_time,
            enforce_market_hours_for_krx=sc.enforce_market_hours_for_krx,
            live_trading_enabled=live_trading_enabled,
            live_unlock_token=live_unlock_token or "",
        )
    )


class RealtimeExecutionRunnerManager:
    """(user_broker_account_id, broker_code) → 독립 Runner."""

    def __init__(
        self,
        *,
        signal_bus: RealtimeSignalBus,
        safety_guard_template: RealtimeOrderSafetyGuard,
        paper_config: RealtimeExecutionConfig,
    ) -> None:
        self._signal_bus = signal_bus
        self._safety_template = safety_guard_template
        paper_guard = clone_safety_guard(
            safety_guard_template,
            live_trading_enabled=False,
            live_unlock_token="",
        )
        self._paper_runner = RealtimeExecutionRunner(
            signal_bus=signal_bus,
            config=paper_config,
            safety_guard=paper_guard,
        )
        self._runners: dict[tuple[int, str], RealtimeExecutionRunner] = {
            PAPER_SCOPE_KEY: self._paper_runner,
        }
        self._last_applied_live_key: tuple[int, str] | None = None

    @property
    def paper_runner(self) -> RealtimeExecutionRunner:
        return self._paper_runner

    @property
    def signal_bus(self) -> RealtimeSignalBus:
        return self._signal_bus

    def get(
        self,
        user_broker_account_id: int,
        broker_code: str,
    ) -> RealtimeExecutionRunner | None:
        return self._runners.get(
            runner_scope_key(user_broker_account_id, broker_code)
        )

    def list_live_runners(self) -> list[RealtimeExecutionRunner]:
        return [
            runner
            for key, runner in self._runners.items()
            if key != PAPER_SCOPE_KEY
        ]

    def running_live_runners(self) -> list[RealtimeExecutionRunner]:
        return [
            runner
            for runner in self.list_live_runners()
            if bool(runner.status().get("running"))
        ]

    def get_or_create_live(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        config: RealtimeExecutionConfig | None = None,
        safety_guard: RealtimeOrderSafetyGuard | None = None,
    ) -> RealtimeExecutionRunner:
        """LIVE Runner를 가져오거나 만든다. 다른 scope는 건드리지 않는다."""

        broker = str(broker_code or "").strip().upper()
        key = runner_scope_key(user_broker_account_id, broker)
        existing = self._runners.get(key)
        if existing is not None:
            if config is not None:
                existing._config = config
            if safety_guard is not None:
                existing._safety_guard = safety_guard
            self._last_applied_live_key = key
            return existing

        paper_cfg = self._paper_runner._config
        resolved = config or RealtimeExecutionConfig(
            mode=RealtimeExecutionMode.LIVE,
            account_id=paper_cfg.account_id,
            order_amount=paper_cfg.order_amount,
            auto_fill=False,
            allow_buy=paper_cfg.allow_buy,
            allow_sell=paper_cfg.allow_sell,
            user_id=paper_cfg.user_id,
            user_broker_account_id=int(user_broker_account_id),
            broker_code=broker,
        )
        guard = safety_guard or clone_safety_guard(
            self._safety_template,
            live_trading_enabled=True,
            live_unlock_token="",
        )
        runner = RealtimeExecutionRunner(
            signal_bus=self._signal_bus,
            config=resolved,
            safety_guard=guard,
        )
        self._runners[key] = runner
        self._last_applied_live_key = key
        return runner

    async def start_scope(
        self,
        user_broker_account_id: int,
        broker_code: str,
    ) -> dict[str, Any]:
        """해당 UBA만 START. 다른 Runner는 STOP하지 않는다."""

        runner = self.get_or_create_live(
            user_broker_account_id=int(user_broker_account_id),
            broker_code=broker_code,
        )
        started = await runner.start()
        return started

    async def stop_scope(
        self,
        user_broker_account_id: int,
        broker_code: str,
    ) -> dict[str, Any]:
        """해당 UBA subscriber만 제거. Signal Bus 전체 unsubscribe 금지."""

        runner = self.get(int(user_broker_account_id), broker_code)
        if runner is None:
            return {
                "stopped": False,
                "reason": "RUNNER_NOT_FOUND",
                "user_broker_account_id": int(user_broker_account_id),
                "broker_code": str(broker_code).upper(),
            }
        await runner.stop()
        return {
            "stopped": True,
            "user_broker_account_id": int(user_broker_account_id),
            "broker_code": str(broker_code).upper(),
            **runner.status(),
        }

    async def stop_all(self) -> None:
        """프로세스 종료 전용. 운영 API에서 호출하지 않는다."""

        for runner in list(self._runners.values()):
            await runner.stop()

    def drop_idle_live_configs(self) -> None:
        """START되지 않은 LIVE config만 제거. RUNNING Runner는 유지."""

        for key in list(self._runners):
            if key == PAPER_SCOPE_KEY:
                continue
            runner = self._runners[key]
            if bool(runner.status().get("running")):
                continue
            self._runners.pop(key, None)
            if self._last_applied_live_key == key:
                self._last_applied_live_key = None

    def apply_paper_config(self, config: RealtimeExecutionConfig) -> None:
        self._paper_runner._config = config

    def compatibility_config(self) -> RealtimeExecutionConfig:
        running = self.running_live_runners()
        if running:
            return self._prefer_upbit(running)._config
        if self._last_applied_live_key is not None:
            last = self._runners.get(self._last_applied_live_key)
            if last is not None:
                return last._config
        return self._paper_runner._config

    def compatibility_safety_guard(self) -> RealtimeOrderSafetyGuard:
        running = self.running_live_runners()
        if running:
            return self._prefer_upbit(running)._safety_guard
        if self._last_applied_live_key is not None:
            last = self._runners.get(self._last_applied_live_key)
            if last is not None:
                return last._safety_guard
        return self._paper_runner._safety_guard

    def apply_compatibility_config(
        self,
        config: RealtimeExecutionConfig,
    ) -> None:
        """레거시 `_config =` 대입. 다른 RUNNING LIVE Runner는 유지."""

        if (
            config.mode == RealtimeExecutionMode.LIVE
            and config.user_broker_account_id
        ):
            broker = str(config.broker_code or "UNRESOLVED").upper()
            self.get_or_create_live(
                user_broker_account_id=int(config.user_broker_account_id),
                broker_code=broker,
                config=config,
            )
            return
        self._paper_runner._config = config
        if config.mode != RealtimeExecutionMode.LIVE:
            self.drop_idle_live_configs()

    def runners_status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, runner in self._runners.items():
            status = runner.status()
            uba_id, broker = key
            rows.append(
                {
                    "uba": uba_id if uba_id > 0 else None,
                    "broker": broker,
                    "running": bool(status.get("running")),
                    **status,
                }
            )
        return rows

    def compatibility_status(self) -> dict[str, Any]:
        runners = self.runners_status()
        primary = self._primary_runner()
        status = primary.status()
        return {
            **status,
            "runners": runners,
            "signal_subscriber_count": self._signal_bus.subscriber_count,
        }

    def history(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for runner in self._runners.values():
            items.extend(runner.history())
        items.sort(key=lambda row: str(row.get("executed_at") or ""), reverse=True)
        return items[:500]

    def _primary_runner(self) -> RealtimeExecutionRunner:
        running = self.running_live_runners()
        if running:
            return self._prefer_upbit(running)
        if self._last_applied_live_key is not None:
            last = self._runners.get(self._last_applied_live_key)
            if last is not None:
                return last
        return self._paper_runner

    @staticmethod
    def _prefer_upbit(
        runners: list[RealtimeExecutionRunner],
    ) -> RealtimeExecutionRunner:
        for runner in runners:
            broker = str(getattr(runner._config, "broker_code", "") or "").upper()
            if broker == "UPBIT":
                return runner
        return runners[0]


class CompatibilityRealtimeExecutionRunner:
    """기존 singleton import 호환. 전역 1-LIVE 재바인딩을 하지 않는다."""

    def __init__(self, manager: RealtimeExecutionRunnerManager) -> None:
        self._manager = manager

    @property
    def _config(self) -> RealtimeExecutionConfig:
        return self._manager.compatibility_config()

    @_config.setter
    def _config(self, value: RealtimeExecutionConfig) -> None:
        self._manager.apply_compatibility_config(value)

    @property
    def _safety_guard(self) -> RealtimeOrderSafetyGuard:
        return self._manager.compatibility_safety_guard()

    @_safety_guard.setter
    def _safety_guard(self, value: RealtimeOrderSafetyGuard) -> None:
        primary = self._manager._primary_runner()
        primary._safety_guard = value

    @property
    def _task(self) -> Any:
        return self._manager._primary_runner()._task

    @_task.setter
    def _task(self, value: Any) -> None:
        self._manager._primary_runner()._task = value

    @property
    def _running(self) -> bool:
        return bool(self._manager._primary_runner()._running)

    @property
    def _signal_bus(self) -> RealtimeSignalBus:
        return self._manager.signal_bus

    async def start(self) -> dict[str, Any]:
        cfg = self._config
        if (
            cfg.mode == RealtimeExecutionMode.LIVE
            and cfg.user_broker_account_id
        ):
            broker = str(cfg.broker_code or "UNRESOLVED").upper()
            return await self._manager.start_scope(
                int(cfg.user_broker_account_id),
                broker,
            )
        return await self._manager.paper_runner.start()

    async def stop(self) -> None:
        """레거시 STOP.

        LIVE Runner가 2개 이상이면 어느 것도 멈추지 않는다.
        (무분별한 전체 unsubscribe 방지)
        """

        live_running = self._manager.running_live_runners()
        if len(live_running) > 1:
            return
        if len(live_running) == 1:
            await live_running[0].stop()
            return
        await self._manager.paper_runner.stop()

    def status(self) -> dict[str, Any]:
        return self._manager.compatibility_status()

    def history(self) -> list[dict[str, Any]]:
        return self._manager.history()
