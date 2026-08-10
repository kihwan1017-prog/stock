"""STEP 8-5-9 — Scope Consumer Registry."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stock_platform.realtime.hub_constants import ConsumerWarmupStatus
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)
from stock_platform.realtime.strategy_signal import StrategySignal
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


class ScopeRequiredError(ValueError):
    """Scope 없는 Consumer 등록 차단."""


def _resolve_paper_position(
    consumer: "ScopedRealtimeConsumer",
    symbol: str,
) -> RealtimePositionState | None:
    """Paper 계좌 보유 수량을 Evaluator에 전달 (손절·익절·청산용)."""

    if consumer.scope.account_kind != AccountKind.PAPER:
        return None
    try:
        from decimal import Decimal

        from sqlalchemy import select

        from stock_platform.database.session import get_session_factory
        from stock_platform.trading.account_models import PaperPosition

        session = get_session_factory()()
        try:
            row = session.scalar(
                select(PaperPosition).where(
                    PaperPosition.account_id == int(consumer.scope.account_id),
                    PaperPosition.symbol == symbol.upper(),
                    PaperPosition.quantity > 0,
                )
            )
            if row is None:
                return RealtimePositionState(
                    quantity=Decimal("0"),
                    average_entry_price=None,
                )
            return RealtimePositionState(
                quantity=Decimal(str(row.quantity)),
                average_entry_price=(
                    Decimal(str(row.average_entry_price))
                    if row.average_entry_price is not None
                    else None
                ),
            )
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        return None


def _resolve_uba_ledger_position(
    consumer: "ScopedRealtimeConsumer",
    symbol: str,
) -> RealtimePositionState | None:
    """USER_BROKER UBA — BrokerPositionSnapshot 기반 손절·익절 (MOCK/LIVE 원장)."""

    if consumer.scope.account_kind != AccountKind.USER_BROKER:
        return None
    broker = str(consumer.scope.broker_code or "").upper()
    if broker not in {"KIWOOM", "UPBIT"}:
        return None
    try:
        from decimal import Decimal

        from sqlalchemy import select

        from stock_platform.broker.account_models import (
            BrokerPositionSnapshotEntity,
        )
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            row = session.scalar(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == int(consumer.scope.account_id),
                    BrokerPositionSnapshotEntity.symbol == symbol.upper(),
                )
            )
            if row is None or Decimal(str(row.quantity or 0)) <= 0:
                return RealtimePositionState(
                    quantity=Decimal("0"),
                    average_entry_price=None,
                )
            avg = row.average_purchase_price
            return RealtimePositionState(
                quantity=Decimal(str(row.quantity)),
                average_entry_price=(
                    Decimal(str(avg))
                    if avg is not None and Decimal(str(avg)) > 0
                    else None
                ),
            )
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        _ = exc
        return None


# 하위 호환 alias
_resolve_mock_uba_position = _resolve_uba_ledger_position


@dataclass
class ScopedRealtimeConsumer:
    scope: StrategyRuntimeScope
    symbols: set[str]
    evaluator: MovingAverageStrategyEvaluator
    runtime_status: RuntimeLifecycleStatus = RuntimeLifecycleStatus.CREATED
    pause_reason: str | None = None
    signals_allowed: bool = True
    registered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_event_at: datetime | None = None
    last_signal_at: datetime | None = None
    last_error: str | None = None
    event_count: int = 0
    signal_count: int = 0
    duplicate_blocked: int = 0

    @property
    def scope_key(self) -> str:
        return self.scope.scope_key

    def as_dict(self) -> dict[str, Any]:
        warmups = {
            sym: self.evaluator.warmup_status(sym).value
            for sym in sorted(self.symbols)
        }
        overall = ConsumerWarmupStatus.READY.value
        if any(
            v == ConsumerWarmupStatus.WARMING_UP.value
            for v in warmups.values()
        ):
            overall = ConsumerWarmupStatus.WARMING_UP.value
        if any(
            v == ConsumerWarmupStatus.FAILED.value for v in warmups.values()
        ):
            overall = ConsumerWarmupStatus.FAILED.value
        return {
            "scope_key": self.scope_key,
            "user_id": self.scope.user_id,
            "account_kind": self.scope.account_kind.value,
            "account_id": self.scope.account_id,
            "account_masked": f"***{str(self.scope.account_id)[-4:]}",
            "strategy_id": self.scope.strategy_id,
            "strategy_version": self.scope.strategy_version,
            "broker_code": self.scope.broker_code,
            "market_type": self.scope.market_type,
            "symbols": sorted(self.symbols),
            "runtime_status": self.runtime_status.value,
            "pause_reason": self.pause_reason,
            "signals_allowed": self.signals_allowed,
            "warmup_status": overall,
            "warmup_by_symbol": warmups,
            "last_event_at": (
                self.last_event_at.isoformat() if self.last_event_at else None
            ),
            "last_signal_at": (
                self.last_signal_at.isoformat()
                if self.last_signal_at
                else None
            ),
            "last_error": self.last_error,
            "event_count": self.event_count,
            "signal_count": self.signal_count,
            "duplicate_blocked": self.duplicate_blocked,
            "registered_at": self.registered_at.isoformat(),
        }


class ScopeConsumerRegistry:
    """
    Symbol → scope_key 집합 + scope_key → consumer.
    Scope 없는 등록은 거부한다.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_scope: dict[str, ScopedRealtimeConsumer] = {}
        self._by_subscription: dict[str, set[str]] = {}

    @staticmethod
    def market_data_broker(*, broker_code: str, market_type: str) -> str:
        """시세 소스 Broker — Paper 계좌도 동일 시세 스트림을 공유."""

        mt = (market_type or "").upper()
        bc = (broker_code or "").upper()
        if mt in {"CRYPTO", "UPBIT"} or bc == "UPBIT":
            return "UPBIT"
        if mt in {"STOCK", "KRX", "KOSPI", "KOSDAQ"} or bc == "KIWOOM":
            return "KIWOOM"
        return bc or "UNKNOWN"

    @staticmethod
    def subscription_key(
        *, broker_code: str, market_type: str, symbol: str
    ) -> str:
        data_broker = ScopeConsumerRegistry.market_data_broker(
            broker_code=broker_code, market_type=market_type
        )
        return (
            f"{data_broker}|{market_type.upper()}|{symbol.upper()}"
        )

    def register_consumer(
        self,
        scope: StrategyRuntimeScope | None,
        symbols: list[str] | set[str],
        *,
        config: RealtimeStrategyConfig | None = None,
        runtime_status: RuntimeLifecycleStatus = RuntimeLifecycleStatus.RUNNING,
    ) -> ScopedRealtimeConsumer:
        if scope is None:
            raise ScopeRequiredError(
                "StrategyRuntimeScope is required; "
                "scope-less consumer registration blocked (STEP 8-5-9)"
            )
        clean = {str(s).upper().strip() for s in symbols if str(s).strip()}
        if not clean:
            raise ValueError("symbols required")

        from stock_platform.common.settings import get_settings

        max_scopes = int(
            getattr(get_settings(), "realtime_max_scopes_per_symbol", 100)
        )

        with self._lock:
            existing = self._by_scope.get(scope.scope_key)
            if existing is not None:
                # 동일 Scope 중복 등록 → symbols 병합·상태 갱신
                existing.symbols |= clean
                existing.runtime_status = runtime_status
                existing.signals_allowed = (
                    runtime_status == RuntimeLifecycleStatus.RUNNING
                )
                for sym in clean:
                    sk = self.subscription_key(
                        broker_code=scope.broker_code,
                        market_type=scope.market_type,
                        symbol=sym,
                    )
                    bucket = self._by_subscription.setdefault(sk, set())
                    if (
                        scope.scope_key not in bucket
                        and len(bucket) >= max_scopes
                    ):
                        raise ValueError(
                            f"max scopes per symbol exceeded: {sk}"
                        )
                    bucket.add(scope.scope_key)
                return existing

            evaluator = MovingAverageStrategyEvaluator(scope, config)
            consumer = ScopedRealtimeConsumer(
                scope=scope,
                symbols=clean,
                evaluator=evaluator,
                runtime_status=runtime_status,
                signals_allowed=(
                    runtime_status == RuntimeLifecycleStatus.RUNNING
                ),
            )
            self._by_scope[scope.scope_key] = consumer
            for sym in clean:
                sk = self.subscription_key(
                    broker_code=scope.broker_code,
                    market_type=scope.market_type,
                    symbol=sym,
                )
                bucket = self._by_subscription.setdefault(sk, set())
                if len(bucket) >= max_scopes:
                    # rollback partial
                    self._by_scope.pop(scope.scope_key, None)
                    raise ValueError(
                        f"max scopes per symbol exceeded: {sk}"
                    )
                bucket.add(scope.scope_key)
            return consumer

    def unregister_consumer(
        self, scope: StrategyRuntimeScope | str
    ) -> list[str]:
        """제거 후 더 이상 구독자 없는 subscription_key 목록 반환."""

        key = (
            scope.scope_key
            if isinstance(scope, StrategyRuntimeScope)
            else str(scope).strip()
        )
        if not key:
            raise ScopeRequiredError("scope_key required")
        freed: list[str] = []
        with self._lock:
            consumer = self._by_scope.pop(key, None)
            if consumer is None:
                return []
            for sym in consumer.symbols:
                sk = self.subscription_key(
                    broker_code=consumer.scope.broker_code,
                    market_type=consumer.scope.market_type,
                    symbol=sym,
                )
                bucket = self._by_subscription.get(sk)
                if not bucket:
                    continue
                bucket.discard(key)
                if not bucket:
                    self._by_subscription.pop(sk, None)
                    freed.append(sk)
        return freed

    def set_runtime_status(
        self,
        scope_key: str,
        status: RuntimeLifecycleStatus,
        *,
        pause_reason: str | None = None,
    ) -> None:
        with self._lock:
            consumer = self._by_scope.get(scope_key)
            if consumer is None:
                return
            consumer.runtime_status = status
            consumer.pause_reason = pause_reason
            # Pause: State 갱신 가능, 신호만 차단
            consumer.signals_allowed = (
                status == RuntimeLifecycleStatus.RUNNING
            )
            if status == RuntimeLifecycleStatus.STOPPED:
                consumer.signals_allowed = False

    def rewarm(self, scope_key: str) -> None:
        with self._lock:
            consumer = self._by_scope.get(scope_key)
            if consumer is None:
                raise KeyError(scope_key)
            consumer.evaluator.reset()
            consumer.last_error = None

    def dispatch(
        self, event: RealtimeMarketEvent
    ) -> list[StrategySignal]:
        sk = event.subscription_key
        with self._lock:
            scope_keys = list(self._by_subscription.get(sk, ()))
            consumers = [
                self._by_scope[k]
                for k in scope_keys
                if k in self._by_scope
                and self._by_scope[k].runtime_status
                != RuntimeLifecycleStatus.STOPPED
            ]

        signals: list[StrategySignal] = []
        now = datetime.now(timezone.utc)
        for consumer in consumers:
            try:
                consumer.event_count += 1
                consumer.last_event_at = now
                before_fp = None
                position = _resolve_paper_position(consumer, event.symbol)
                if position is None:
                    position = _resolve_uba_ledger_position(
                        consumer, event.symbol
                    )
                # evaluate
                signal = consumer.evaluator.evaluate(
                    event,
                    position=position,
                    allow_signal=consumer.signals_allowed,
                )
                if signal is None:
                    continue
                # 중복 fingerprint 추가 방어
                st = consumer.evaluator.get_state(event.symbol)
                if before_fp and st.last_fingerprint == before_fp:
                    consumer.duplicate_blocked += 1
                    continue
                consumer.signal_count += 1
                consumer.last_signal_at = signal.generated_at
                signals.append(signal)
            except Exception as exc:  # noqa: BLE001
                consumer.last_error = str(exc)[:200]
        return signals

    def list_consumers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [c.as_dict() for c in self._by_scope.values()]

    def get_consumer(self, scope_key: str) -> dict[str, Any] | None:
        with self._lock:
            c = self._by_scope.get(scope_key)
            return c.as_dict() if c else None

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for sk, scopes in self._by_subscription.items():
                parts = sk.split("|")
                rows.append(
                    {
                        "subscription_key": sk,
                        "broker_code": parts[0] if parts else "",
                        "market_type": parts[1] if len(parts) > 1 else "",
                        "symbol": parts[2] if len(parts) > 2 else "",
                        "scope_count": len(scopes),
                        "scope_keys": sorted(scopes),
                    }
                )
            return rows

    def active_scope_count(self) -> int:
        with self._lock:
            return len(self._by_scope)

    def running_scope_count(self) -> int:
        """신호 허용(RUNNING) Scope만 카운트 — PAUSED 등록은 제외."""

        with self._lock:
            return sum(
                1
                for consumer in self._by_scope.values()
                if consumer.runtime_status == RuntimeLifecycleStatus.RUNNING
            )

    def warming_up_count(self) -> int:
        with self._lock:
            n = 0
            for c in self._by_scope.values():
                if any(
                    c.evaluator.warmup_status(s)
                    == ConsumerWarmupStatus.WARMING_UP
                    for s in c.symbols
                ):
                    n += 1
            return n

    def clear(self) -> None:
        with self._lock:
            self._by_scope.clear()
            self._by_subscription.clear()
