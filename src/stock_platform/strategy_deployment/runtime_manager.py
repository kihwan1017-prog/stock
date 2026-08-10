"""STEP 8-5-5 — Scope 기반 Strategy Runtime Registry.

전역 `_runtime` / `_strategy` 슬롯을 제거한다.
조회·제어는 반드시 scope_key가 필요하다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.default_registry import (
    configure_default_strategy_registry,
)
from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
)
from stock_platform.strategy_deployment.registry import (
    strategy_factory_registry,
)
from stock_platform.strategy_deployment.runtime_loader import (
    ActiveStrategyRuntimeLoader,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
    StrategyRuntimeReloadResult,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
    StrategyRuntimeScopeError,
)

logger = structlog.get_logger(__name__)


class RuntimeScopeRequiredError(LookupError):
    """Scope 없는 Runtime 조회는 금지."""


@dataclass
class ScopedRuntimeEntry:
    scope: StrategyRuntimeScope
    runtime: LoadedStrategyRuntime
    strategy: object
    status: RuntimeLifecycleStatus = RuntimeLifecycleStatus.CREATED
    pause_reason: str | None = None
    last_error: str | None = None
    last_started_at: datetime | None = None
    last_paused_at: datetime | None = None
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def as_dict(self, *, include_strategy_code: bool = True) -> dict[str, Any]:
        data = {
            "scope_key": self.scope.scope_key,
            "status": self.status.value,
            "pause_reason": self.pause_reason,
            "last_error": self.last_error,
            "last_started_at": (
                self.last_started_at.isoformat()
                if self.last_started_at
                else None
            ),
            "last_paused_at": (
                self.last_paused_at.isoformat()
                if self.last_paused_at
                else None
            ),
            "updated_at": self.updated_at.isoformat(),
            "user_id": self.scope.user_id,
            "account_kind": self.scope.account_kind.value,
            "account_id": self.scope.account_id,
            "paper_account_id": self.scope.paper_account_id,
            "user_broker_account_id": (
                self.scope.user_broker_account_id
            ),
            "strategy_id": self.scope.strategy_id,
            "strategy_version": self.scope.strategy_version,
            "market_type": self.scope.market_type,
            "broker_code": self.scope.broker_code,
            "deployment_id": self.runtime.deployment_id,
            "market_code": self.runtime.market_code,
            "symbol": self.runtime.symbol,
        }
        if include_strategy_code:
            data["strategy_code"] = self.runtime.strategy_code
        return data


class DynamicStrategyRuntimeManager:
    """Scope Key → Runtime 인스턴스 레지스트리."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runtimes: dict[str, ScopedRuntimeEntry] = {}
        self._last_error: str | None = None
        self._accepting_work = True

    def _require_scope_key(self, scope_key: str | None) -> str:
        if not scope_key or not str(scope_key).strip():
            raise RuntimeScopeRequiredError(
                "scope_key is required; global runtime slot removed (STEP 8-5-5)"
            )
        return str(scope_key).strip()

    async def initialize_scoped(
        self,
        scope: StrategyRuntimeScope,
        *,
        force: bool = True,
        start: bool = True,
    ) -> StrategyRuntimeReloadResult:
        """단일 Scope Runtime 생성·로드."""

        configure_default_strategy_registry()
        return await self.reload_scope(scope, force=force, start=start)

    async def initialize(
        self,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
        user_id: int | None = None,
        account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> dict[str, Any]:
        """Startup 진입점 — 활성 account_strategy_link만 Scope별 생성.

        기본 KRX 단일 Runtime은 생성하지 않는다.
        market_code/symbol 인자는 하위 호환용으로 무시(링크 기준).
        """

        _ = (market_code, symbol, user_id, account_id, user_broker_account_id)
        configure_default_strategy_registry()
        from stock_platform.strategy_deployment.runtime_bootstrap import (
            bootstrap_scoped_runtimes,
        )

        return await bootstrap_scoped_runtimes(self)

    async def reload_scope(
        self,
        scope: StrategyRuntimeScope,
        *,
        force: bool = False,
        start: bool = True,
    ) -> StrategyRuntimeReloadResult:
        async with self._lock:
            return await self._reload_scope_locked(
                scope, force=force, start=start
            )

    async def _reload_scope_locked(
        self,
        scope: StrategyRuntimeScope,
        *,
        force: bool,
        start: bool,
    ) -> StrategyRuntimeReloadResult:
        session = get_session_factory()()
        scope_key = scope.scope_key
        try:
            runtime, strategy = ActiveStrategyRuntimeLoader(
                session=session,
                registry=strategy_factory_registry,
            ).load(
                market_code=scope.market_code or scope.market_type,
                symbol=None,
                mode=(
                    StrategyDeploymentMode.PAPER
                    if scope.account_kind == AccountKind.PAPER
                    else StrategyDeploymentMode.LIVE
                ),
                user_id=scope.user_id,
                account_id=scope.paper_account_id,
                user_broker_account_id=scope.user_broker_account_id,
                strategy_id=scope.strategy_id,
            )

            # Loader 결과와 Scope 계좌 일치 강제
            runtime = LoadedStrategyRuntime(
                deployment_id=runtime.deployment_id,
                strategy_code=runtime.strategy_code,
                market_code=runtime.market_code,
                symbol=runtime.symbol,
                parameter_payload=runtime.parameter_payload,
                loaded_at=runtime.loaded_at,
                user_id=scope.user_id,
                account_id=scope.paper_account_id,
                user_broker_account_id=scope.user_broker_account_id,
                strategy_id=scope.strategy_id,
                strategy_version=scope.strategy_version,
                market_type=scope.market_type,
                scope_key=scope_key,
                broker_code=scope.broker_code,
                account_kind=scope.account_kind.value,
            )

            if runtime.strategy_id is not None:
                from stock_platform.strategy_deployment.definition_entities import (
                    StrategyDefinitionEntity,
                )

                definition = session.get(
                    StrategyDefinitionEntity, runtime.strategy_id
                )
                if definition is None or definition.deleted_at is not None:
                    raise LookupError("Strategy definition deleted")
                if not definition.is_active:
                    raise LookupError("Inactive strategy cannot run")

            previous = self._runtimes.get(scope_key)
            previous_id = (
                previous.runtime.deployment_id if previous else None
            )
            if (
                not force
                and previous is not None
                and previous.runtime.deployment_id == runtime.deployment_id
                and previous.status
                != RuntimeLifecycleStatus.STOPPED
            ):
                return StrategyRuntimeReloadResult(
                    changed=False,
                    previous_deployment_id=previous_id,
                    current_deployment_id=previous_id,
                    strategy_code=runtime.strategy_code,
                    message="Active deployment has not changed",
                    reloaded_at=datetime.now(timezone.utc),
                    scope_key=scope_key,
                )

            status = (
                RuntimeLifecycleStatus.RUNNING
                if start
                else RuntimeLifecycleStatus.PAUSED
            )
            entry = ScopedRuntimeEntry(
                scope=scope,
                runtime=runtime,
                strategy=strategy,
                status=status,
                pause_reason=None if start else "reloaded_paused",
                last_started_at=(
                    datetime.now(timezone.utc) if start else None
                ),
            )
            self._runtimes[scope_key] = entry
            self._last_error = None
            # STEP 8-5-9 — Realtime Consumer 동기화 (실패해도 다른 Scope 유지)
            try:
                from stock_platform.realtime.runtime_bridge import (
                    sync_realtime_consumer_for_entry,
                )

                sync_realtime_consumer_for_entry(entry)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "realtime_bridge_sync_failed",
                    scope_key=scope_key[:48],
                )
            return StrategyRuntimeReloadResult(
                changed=True,
                previous_deployment_id=previous_id,
                current_deployment_id=runtime.deployment_id,
                strategy_code=runtime.strategy_code,
                message="Scoped strategy runtime reloaded",
                reloaded_at=datetime.now(timezone.utc),
                scope_key=scope_key,
            )
        except Exception as exc:
            self._last_error = str(exc)
            existing = self._runtimes.get(scope_key)
            if existing is not None:
                existing.status = RuntimeLifecycleStatus.ERROR
                existing.last_error = str(exc)
                existing.updated_at = datetime.now(timezone.utc)
            raise
        finally:
            session.close()

    async def reload(
        self,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
        force: bool = False,
        user_id: int | None = None,
        account_id: int | None = None,
        user_broker_account_id: int | None = None,
        scope_key: str | None = None,
        strategy_id: int | None = None,
    ) -> StrategyRuntimeReloadResult | dict[str, Any]:
        """Scope 지정 Reload. scope_key 없으면 등록된 전체 Scope Reload."""

        _ = (market_code, symbol, user_id, account_id, user_broker_account_id)
        if scope_key:
            key = self._require_scope_key(scope_key)
            entry = self._runtimes.get(key)
            if entry is None:
                raise LookupError(f"Runtime not found: {key}")
            return await self.reload_scope(
                entry.scope, force=force, start=True
            )

        if strategy_id is not None:
            return await self.reload_strategy(
                int(strategy_id), force=force
            )

        # 전체 Scope 재로드 (Scheduler)
        return await self.reload_all_scopes(force=force)

    async def reload_all_scopes(
        self, *, force: bool = False
    ) -> dict[str, Any]:
        async with self._lock:
            keys = list(self._runtimes.keys())
        changed = 0
        failed: list[dict[str, str]] = []
        for key in keys:
            entry = self._runtimes.get(key)
            if entry is None:
                continue
            try:
                result = await self.reload_scope(
                    entry.scope, force=force, start=(
                        entry.status == RuntimeLifecycleStatus.RUNNING
                    )
                )
                if result.changed:
                    changed += 1
            except Exception as exc:  # noqa: BLE001
                failed.append({"scope_key": key, "error": str(exc)})
                logger.warning(
                    "scoped_runtime_reload_failed",
                    scope_key=key,
                    error=str(exc),
                )
        return {
            "reloaded_scopes": len(keys),
            "changed": changed,
            "failed": failed,
        }

    async def reload_strategy(
        self, strategy_id: int, *, force: bool = True
    ) -> dict[str, Any]:
        async with self._lock:
            targets = [
                e
                for e in self._runtimes.values()
                if e.scope.strategy_id == int(strategy_id)
            ]
        changed = 0
        failed: list[dict[str, str]] = []
        for entry in targets:
            try:
                result = await self.reload_scope(
                    entry.scope,
                    force=force,
                    start=entry.status == RuntimeLifecycleStatus.RUNNING,
                )
                if result.changed:
                    changed += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(
                    {
                        "scope_key": entry.scope.scope_key,
                        "error": str(exc),
                    }
                )
        return {
            "strategy_id": strategy_id,
            "target_count": len(targets),
            "changed": changed,
            "failed": failed,
        }

    async def put_entry(
        self,
        entry: ScopedRuntimeEntry,
        *,
        replace: bool = True,
    ) -> ScopedRuntimeEntry:
        async with self._lock:
            key = entry.scope.scope_key
            if not replace and key in self._runtimes:
                raise StrategyRuntimeScopeError(
                    "duplicate_scope",
                    f"Runtime already exists for {key}",
                )
            self._runtimes[key] = entry
            return entry

    async def pause_runtime(
        self, scope_key: str, *, reason: str
    ) -> ScopedRuntimeEntry:
        key = self._require_scope_key(scope_key)
        async with self._lock:
            entry = self._require_entry(key)
            entry.status = RuntimeLifecycleStatus.PAUSED
            entry.pause_reason = reason
            entry.last_paused_at = datetime.now(timezone.utc)
            entry.updated_at = datetime.now(timezone.utc)
            try:
                from stock_platform.realtime.runtime_bridge import (
                    sync_realtime_consumer_for_entry,
                )

                sync_realtime_consumer_for_entry(entry)
            except Exception:  # noqa: BLE001
                pass
            return entry

    async def resume_runtime(
        self, scope_key: str
    ) -> ScopedRuntimeEntry:
        key = self._require_scope_key(scope_key)
        async with self._lock:
            entry = self._require_entry(key)
            if entry.status == RuntimeLifecycleStatus.STOPPED:
                raise LookupError("Cannot resume stopped runtime")
            entry.status = RuntimeLifecycleStatus.RUNNING
            entry.pause_reason = None
            entry.last_error = None
            entry.last_started_at = datetime.now(timezone.utc)
            entry.updated_at = datetime.now(timezone.utc)
            try:
                from stock_platform.realtime.runtime_bridge import (
                    sync_realtime_consumer_for_entry,
                )

                sync_realtime_consumer_for_entry(entry)
            except Exception:  # noqa: BLE001
                pass
            return entry

    async def stop_runtime(self, scope_key: str) -> ScopedRuntimeEntry:
        key = self._require_scope_key(scope_key)
        async with self._lock:
            entry = self._require_entry(key)
            entry.status = RuntimeLifecycleStatus.STOPPED
            entry.pause_reason = "stopped"
            entry.updated_at = datetime.now(timezone.utc)
            try:
                from stock_platform.realtime.runtime_bridge import (
                    sync_realtime_consumer_for_entry,
                )

                sync_realtime_consumer_for_entry(entry)
            except Exception:  # noqa: BLE001
                pass
            return entry

    async def pause_account_runtimes(
        self,
        *,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
        reason: str,
    ) -> list[str]:
        async with self._lock:
            keys = [
                e.scope.scope_key
                for e in self._runtimes.values()
                if e.scope.matches_account(
                    paper_account_id=paper_account_id,
                    user_broker_account_id=user_broker_account_id,
                )
            ]
            for key in keys:
                entry = self._runtimes[key]
                entry.status = RuntimeLifecycleStatus.PAUSED
                entry.pause_reason = reason
                entry.last_paused_at = datetime.now(timezone.utc)
                entry.updated_at = datetime.now(timezone.utc)
                try:
                    from stock_platform.realtime.runtime_bridge import (
                        sync_realtime_consumer_for_entry,
                    )

                    sync_realtime_consumer_for_entry(entry)
                except Exception:  # noqa: BLE001
                    pass
            return keys

    async def resume_account_runtimes(
        self,
        *,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> list[str]:
        async with self._lock:
            keys = [
                e.scope.scope_key
                for e in self._runtimes.values()
                if e.scope.matches_account(
                    paper_account_id=paper_account_id,
                    user_broker_account_id=user_broker_account_id,
                )
                and e.status != RuntimeLifecycleStatus.STOPPED
            ]
            for key in keys:
                entry = self._runtimes[key]
                if entry.pause_reason in {
                    "manual_review_required",
                    "UPBIT_REMOTE_ONLY_ORDER_REVIEW",
                    "recovery_failed",
                    "credential_error",
                    "kill_switch",
                }:
                    # DB 안전 상태가 우선 — 호출측에서 사전 검증 후 resume
                    pass
                entry.status = RuntimeLifecycleStatus.RUNNING
                entry.pause_reason = None
                entry.last_started_at = datetime.now(timezone.utc)
                entry.updated_at = datetime.now(timezone.utc)
            return keys

    async def pause_user_runtimes(
        self, user_id: int, *, reason: str
    ) -> list[str]:
        paused_entries: list[ScopedRuntimeEntry] = []
        async with self._lock:
            keys = [
                e.scope.scope_key
                for e in self._runtimes.values()
                if e.scope.user_id == int(user_id)
            ]
            for key in keys:
                entry = self._runtimes[key]
                entry.status = RuntimeLifecycleStatus.PAUSED
                entry.pause_reason = reason
                entry.last_paused_at = datetime.now(timezone.utc)
                entry.updated_at = datetime.now(timezone.utc)
                paused_entries.append(entry)
        for entry in paused_entries:
            try:
                from stock_platform.realtime.runtime_bridge import (
                    sync_realtime_consumer_for_entry,
                )

                sync_realtime_consumer_for_entry(entry)
            except Exception:  # noqa: BLE001
                pass
        return [e.scope.scope_key for e in paused_entries]

    async def pause_all(
        self,
        *,
        reason: str,
        except_brokers: set[str] | frozenset[str] | None = None,
    ) -> int:
        skip = {
            str(b).upper() for b in (except_brokers or set()) if b
        }
        paused_entries: list[ScopedRuntimeEntry] = []
        async with self._lock:
            for entry in self._runtimes.values():
                broker = str(
                    getattr(entry.scope, "broker_code", "") or ""
                ).upper()
                if broker and broker in skip:
                    continue
                entry.status = RuntimeLifecycleStatus.PAUSED
                entry.pause_reason = reason
                entry.last_paused_at = datetime.now(timezone.utc)
                entry.updated_at = datetime.now(timezone.utc)
                paused_entries.append(entry)
        # lock 해제 후 Hub sync — Manager PAUSED와 consumer 상태 일치
        for entry in paused_entries:
            try:
                from stock_platform.realtime.runtime_bridge import (
                    sync_realtime_consumer_for_entry,
                )

                sync_realtime_consumer_for_entry(entry)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "realtime_bridge_sync_failed_on_pause_all",
                    scope_key=entry.scope.scope_key[:48],
                )
        return len(paused_entries)

    async def stop_account_runtimes(
        self,
        *,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> list[str]:
        async with self._lock:
            keys = [
                e.scope.scope_key
                for e in self._runtimes.values()
                if e.scope.matches_account(
                    paper_account_id=paper_account_id,
                    user_broker_account_id=user_broker_account_id,
                )
            ]
            for key in keys:
                self._runtimes[key].status = (
                    RuntimeLifecycleStatus.STOPPED
                )
                self._runtimes[key].updated_at = datetime.now(
                    timezone.utc
                )
            return keys

    async def stop_user_runtimes(self, user_id: int) -> list[str]:
        async with self._lock:
            keys = [
                e.scope.scope_key
                for e in self._runtimes.values()
                if e.scope.user_id == int(user_id)
            ]
            for key in keys:
                self._runtimes[key].status = (
                    RuntimeLifecycleStatus.STOPPED
                )
            return keys

    async def clear(self, *, scope_key: str | None = None) -> None:
        async with self._lock:
            if scope_key is None:
                self._runtimes.clear()
            else:
                self._runtimes.pop(self._require_scope_key(scope_key), None)

    async def shutdown_all(self) -> dict[str, Any]:
        """서버 종료 — 모든 Scope 중지. 하나 실패해도 계속."""

        self._accepting_work = False
        async with self._lock:
            keys = list(self._runtimes.keys())
            failed: list[dict[str, str]] = []
            for key in keys:
                try:
                    entry = self._runtimes[key]
                    entry.status = RuntimeLifecycleStatus.STOPPED
                    entry.pause_reason = "shutdown"
                    entry.updated_at = datetime.now(timezone.utc)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"scope_key": key, "error": str(exc)})
            self._runtimes.clear()
            return {
                "stopped": len(keys) - len(failed),
                "failed": failed,
            }

    def get_strategy(self, *, scope_key: str | None = None):
        key = self._require_scope_key(scope_key)
        entry = self._runtimes.get(key)
        if entry is None:
            raise LookupError(
                "Realtime strategy is not loaded for scope"
            )
        if entry.status == RuntimeLifecycleStatus.STOPPED:
            raise LookupError("Runtime is stopped")
        return entry.strategy

    def get_runtime(
        self, *, scope_key: str | None = None
    ) -> LoadedStrategyRuntime | None:
        key = self._require_scope_key(scope_key)
        entry = self._runtimes.get(key)
        return entry.runtime if entry else None

    def get_entry(
        self, scope_key: str
    ) -> ScopedRuntimeEntry | None:
        return self._runtimes.get(self._require_scope_key(scope_key))

    def list_entries(
        self,
        *,
        user_id: int | None = None,
        strategy_id: int | None = None,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> list[ScopedRuntimeEntry]:
        rows = list(self._runtimes.values())
        if user_id is not None:
            rows = [e for e in rows if e.scope.user_id == int(user_id)]
        if strategy_id is not None:
            rows = [
                e
                for e in rows
                if e.scope.strategy_id == int(strategy_id)
            ]
        if paper_account_id is not None or user_broker_account_id is not None:
            rows = [
                e
                for e in rows
                if e.scope.matches_account(
                    paper_account_id=paper_account_id,
                    user_broker_account_id=user_broker_account_id,
                )
            ]
        return rows

    def status(self, *, scope_key: str | None = None) -> dict[str, Any]:
        if scope_key is not None:
            entry = self.get_entry(scope_key)
            if entry is None:
                return {
                    "loaded": False,
                    "scope_key": scope_key,
                    "runtime": None,
                }
            return {
                "loaded": True,
                **entry.as_dict(),
                "registered_strategy_codes": (
                    strategy_factory_registry.list_codes()
                ),
            }

        items = [e.as_dict() for e in self._runtimes.values()]
        return {
            "loaded": len(items) > 0,
            "scoped_runtime_count": len(items),
            "scoped_keys": sorted(self._runtimes.keys()),
            "runtimes": items,
            # 전역 단일 runtime 필드 제거 — 호환용 None
            "runtime": None,
            "registered_strategy_codes": (
                strategy_factory_registry.list_codes()
            ),
            "last_error": self._last_error,
            "accepting_work": self._accepting_work,
            "global_slot_removed": True,
        }

    def _require_entry(self, scope_key: str) -> ScopedRuntimeEntry:
        entry = self._runtimes.get(scope_key)
        if entry is None:
            raise LookupError(f"Runtime not found: {scope_key}")
        return entry


dynamic_strategy_runtime_manager = DynamicStrategyRuntimeManager()
