"""STEP 8-5-9 — Scope별 Moving Average Evaluator (전역 State 금지).

timeframe=1D: raw tick을 MA deque에 넣지 않는다.
completed daily close + 당일 rolling close만 MA 입력이다.
SL/TP는 기존처럼 realtime tick price.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.realtime.hub_constants import (
    ConsumerWarmupStatus,
    SignalType,
)
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)
from stock_platform.realtime.strategy_signal import StrategySignal
from stock_platform.realtime.timeframe_bar import RealtimeTimeframeBarAggregator
from stock_platform.strategy_deployment.runtime_scope import (
    StrategyRuntimeScope,
)


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass
class ScopeStrategyState:
    """Scope 내부 종목별 전략 State — 다른 Scope와 공유 금지."""

    prices: deque[Decimal] = field(default_factory=deque)
    last_signal_type: str | None = None
    last_signal_at: datetime | None = None
    last_fingerprint: str | None = None
    # portfolio bullish entry — selection 단위 opportunity identity
    last_bullish_selection_id: int | None = None
    last_sequence: int | None = None
    last_event_time: datetime | None = None
    warmup_status: ConsumerWarmupStatus = ConsumerWarmupStatus.WARMING_UP
    last_error: str | None = None
    previous_short: Decimal | None = None
    previous_long: Decimal | None = None
    last_bar_date: date | None = None
    input_unit: str = "TICK"
    # MA_DEAD_CROSS confirmation (메모리 전용 — DB lifecycle 변경 없음)
    ma_exit_confirming: bool = False
    first_dead_cross_at: datetime | None = None
    last_ma_exit_telemetry: dict | None = None
    # Forward shadow 연구용 — 직전 evaluation MA 스냅샷 (REAL emit 무관)
    last_eval_short: Decimal | None = None
    last_eval_long: Decimal | None = None
    last_eval_prev_short: Decimal | None = None
    last_eval_prev_long: Decimal | None = None


class MovingAverageStrategyEvaluator:
    """
    이동평균 Cross·손절·익절 계산만 담당.
    WebSocket / Scope Registry / 주문은 다루지 않는다.
    """

    def __init__(
        self,
        scope: StrategyRuntimeScope,
        config: RealtimeStrategyConfig | None = None,
    ) -> None:
        self.scope = scope
        self.config = config or RealtimeStrategyConfig()
        self._validate()
        self._by_symbol: dict[str, ScopeStrategyState] = {}
        self._bars = RealtimeTimeframeBarAggregator(
            scope_key=scope.scope_key,
            timeframe=self.config.timeframe or "TICK",
        )
        # Portfolio BULLISH_STATE 전용 — FIXED/SINGLE 은 None 유지
        self.portfolio_entry_ctx = None
        # 진단용 메모리 카운터 (DB write 없음)
        self.path_counters: dict[str, int] = {}

    def _bump(self, key: str) -> None:
        self.path_counters[key] = int(self.path_counters.get(key, 0)) + 1

    def _record_gate_telemetry(
        self,
        symbol: str,
        *,
        decision: str,
        block_reason: str,
        snapshot: dict | None = None,
    ) -> None:
        """BULLISH 경로 진입 전 gate도 운영 가시성용으로 기록 (throttle는 telemetry 내부)."""

        ctx = self.portfolio_entry_ctx
        uba_id = int(
            getattr(ctx, "user_broker_account_id", None)
            or getattr(self.scope, "account_id", 0)
            or 0
        )
        if not uba_id:
            return
        if not (
            bool(self.config.portfolio_mode) or ctx is not None
        ):
            return
        try:
            from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                portfolio_entry_telemetry,
            )

            portfolio_entry_telemetry.record(
                uba_id,
                symbol.upper(),
                decision=decision,
                block_reason=block_reason,
                reason_code=None,
                snapshot=dict(snapshot or {}),
            )
        except Exception:  # noqa: BLE001
            pass

    def _validate(self) -> None:
        if self.config.short_window <= 0:
            raise ValueError("short_window must be > 0")
        if self.config.long_window <= self.config.short_window:
            raise ValueError(
                "long_window must be > short_window"
            )
        if self.config.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

    def get_state(self, symbol: str) -> ScopeStrategyState:
        key = symbol.upper()
        if key not in self._by_symbol:
            state = ScopeStrategyState()
            state.prices = deque(maxlen=self.config.long_window + 1)
            state.input_unit = (
                "DAY" if self.config.uses_daily_bars() else "TICK"
            )
            self._by_symbol[key] = state
        return self._by_symbol[key]

    def warmup_status(self, symbol: str) -> ConsumerWarmupStatus:
        return self.get_state(symbol).warmup_status

    def seed_completed_closes(
        self,
        symbol: str,
        closes: list[tuple[date, Decimal]],
    ) -> int:
        """completed daily close seed. 신호 없음. 오늘 봉은 넣지 말 것."""

        state = self.get_state(symbol)
        state.prices.clear()
        state.previous_short = None
        state.previous_long = None
        state.last_bar_date = None
        state.input_unit = "DAY"
        self._bars.reset(symbol)
        applied = 0
        for trade_date, close in closes:
            if close is None:
                continue
            state.prices.append(Decimal(str(close)))
            state.last_bar_date = trade_date
            applied += 1
            short_avg = self._average(state.prices, self.config.short_window)
            long_avg = self._average(state.prices, self.config.long_window)
            state.previous_short = short_avg
            state.previous_long = long_avg
        if len(state.prices) >= self.config.long_window + 1:
            state.warmup_status = ConsumerWarmupStatus.READY
        else:
            state.warmup_status = ConsumerWarmupStatus.WARMING_UP
        return applied

    def prime_current_day_bar(
        self,
        symbol: str,
        *,
        trade_date: date,
        close: Decimal,
    ) -> None:
        """당일 rolling bar bootstrap. REST/주입 전용, 신호 없음."""

        state = self.get_state(symbol)
        state.input_unit = "DAY"
        update = self._bars.prime(
            symbol, trade_date=trade_date, close=Decimal(str(close))
        )
        self._apply_daily_close(state, update.trade_date, update.close, update.replaced_last)
        short_avg = self._average(state.prices, self.config.short_window)
        long_avg = self._average(state.prices, self.config.long_window)
        state.previous_short = short_avg
        state.previous_long = long_avg
        if len(state.prices) >= self.config.long_window + 1:
            state.warmup_status = ConsumerWarmupStatus.READY
        else:
            state.warmup_status = ConsumerWarmupStatus.WARMING_UP

    def evaluate(
        self,
        event: RealtimeMarketEvent,
        *,
        position: RealtimePositionState | None = None,
        allow_signal: bool = True,
    ) -> StrategySignal | None:
        """신호 없으면 None. HOLD/NO_ACTION은 발행하지 않음."""

        self._bump("tick_received")
        if event.price is None:
            self._bump("price_none_return")
            return None
        symbol = event.symbol.upper()
        state = self.get_state(symbol)
        position = position or RealtimePositionState(
            quantity=ZERO, average_entry_price=None
        )

        # 중복·역순·오래된 Event — stale tick은 일봉도 갱신하지 않음
        if not self._accept_event(state, event):
            self._bump("stale_event_return")
            return None

        self._bump("ma_evaluator_called")

        if self.config.uses_daily_bars():
            update = self._bars.ingest(event)
            if update is None:
                self._bump("daily_ingest_none_return")
                return None
            self._apply_daily_close(
                state, update.trade_date, update.close, update.replaced_last
            )
        else:
            state.prices.append(event.price)

        short_avg = self._average(state.prices, self.config.short_window)
        long_avg = self._average(state.prices, self.config.long_window)

        # 보유 중 손절·익절은 warmup 여부와 무관하게 즉시 평가 (tick price)
        if (
            allow_signal
            and position.quantity > ZERO
            and position.average_entry_price is not None
        ):
            stop = position.average_entry_price * (
                ONE - self.config.stop_loss_ratio
            )
            take = position.average_entry_price * (
                ONE + self.config.take_profit_ratio
            )
            if event.price <= stop:
                sig = self._emit(
                    event, state, SignalType.SELL, "STOP_LOSS", short_avg, long_avg
                )
                self._observe_forward_shadow(
                    event, position, signal=sig, state=state
                )
                return sig
            if event.price >= take:
                sig = self._emit(
                    event, state, SignalType.SELL, "TAKE_PROFIT", short_avg, long_avg
                )
                self._observe_forward_shadow(
                    event, position, signal=sig, state=state
                )
                return sig

        needed = self.config.long_window + 1
        if len(state.prices) < needed:
            state.warmup_status = ConsumerWarmupStatus.WARMING_UP
            state.previous_short = short_avg
            state.previous_long = long_avg
            self._bump("warmup_return")
            self._record_gate_telemetry(
                symbol,
                decision="BLOCK",
                block_reason="WARMING_UP",
                snapshot={
                    "buffer_len": len(state.prices),
                    "needed": needed,
                    "short_window": self.config.short_window,
                    "long_window": self.config.long_window,
                },
            )
            return None

        state.warmup_status = ConsumerWarmupStatus.READY
        if not allow_signal:
            state.previous_short = short_avg
            state.previous_long = long_avg
            self._bump("signals_not_allowed_return")
            self._record_gate_telemetry(
                symbol,
                decision="BLOCK",
                block_reason="SIGNALS_NOT_ALLOWED",
            )
            return None

        prev_s = state.previous_short
        prev_l = state.previous_long
        state.previous_short = short_avg
        state.previous_long = long_avg
        state.last_eval_short = short_avg
        state.last_eval_long = long_avg
        state.last_eval_prev_short = prev_s
        state.last_eval_prev_long = prev_l

        if (
            short_avg is None
            or long_avg is None
            or prev_s is None
            or prev_l is None
        ):
            self._bump("prev_ma_none_return")
            self._record_gate_telemetry(
                symbol,
                decision="BLOCK",
                block_reason="PREV_MA_NOT_READY",
            )
            return None

        # Portfolio BULLISH_STATE — CROSS_EVENT와 분리 (FIXED는 영향 없음)
        wants_portfolio = bool(self.config.portfolio_mode) or (
            self.portfolio_entry_ctx is not None
        )
        if (
            position.quantity <= ZERO
            and wants_portfolio
            and self._uses_bullish_state_policy()
        ):
            self._bump("portfolio_eval_called")
            signal = self._evaluate_portfolio_bullish_buy(
                event,
                state,
                short_avg=short_avg,
                long_avg=long_avg,
            )
            if signal is None:
                self._bump("portfolio_eval_block")
            else:
                self._bump("portfolio_eval_pass")
            return signal

        if position.quantity <= ZERO and wants_portfolio:
            if self.portfolio_entry_ctx is None and not bool(
                self.config.portfolio_mode
            ):
                self._bump("ctx_missing_return")
                self._record_gate_telemetry(
                    symbol,
                    decision="BLOCK",
                    block_reason="PORTFOLIO_ENTRY_CTX_MISSING",
                )
            elif not self._uses_bullish_state_policy():
                self._bump("policy_not_bullish_return")
                self._record_gate_telemetry(
                    symbol,
                    decision="BLOCK",
                    block_reason="ENTRY_POLICY_NOT_BULLISH_STATE",
                    snapshot={
                        "entry_signal_policy": self.config.entry_signal_policy,
                    },
                )

        # Golden / Dead Cross — 1D면 previous/current daily-bar MA
        if (
            position.quantity <= ZERO
            and prev_s <= prev_l
            and short_avg > long_avg
            and self._passes_change(event)
        ):
            # REAL multi-symbol roster symbol → refresh path owns BUY (034310 포함)
            try:
                from stock_platform.operation.kiwoom_multi_symbol_universe.real_signal import (
                    multi_symbol_real_defers_legacy_ma_buy,
                )

                if multi_symbol_real_defers_legacy_ma_buy(
                    broker_code=str(self.scope.broker_code or ""),
                    uba_id=int(self.scope.account_id),
                    symbol=str(event.symbol or "").upper(),
                ):
                    return None
            except Exception:  # noqa: BLE001
                pass
            # KIWOOM K0 research shadow — REAL emit과 독립, fail-open
            try:
                from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.hooks import (
                    maybe_enroll_kiwoom_golden_cross_shadow,
                )

                maybe_enroll_kiwoom_golden_cross_shadow(
                    broker_code=str(self.scope.broker_code or ""),
                    uba_id=int(self.scope.account_id),
                    symbol=event.symbol.upper(),
                    short_ma=short_avg,
                    long_ma=long_avg,
                    prev_short=prev_s,
                    prev_long=prev_l,
                    event_time=event.event_time,
                    entry_reference_price=event.price,
                    scope_key=self.scope.scope_key,
                )
            except Exception:  # noqa: BLE001
                pass
            return self._emit(
                event, state, SignalType.BUY, "MA_GOLDEN_CROSS", short_avg, long_avg
            )
        # MA_DEAD_CROSS — anti-churn gate (보호 SL/TP는 위에서 이미 즉시 처리)
        # WRK-014: durable intent cooldown → STATE 재검증 후 bounded retry (edge 불필요)
        if position.quantity > ZERO and allow_signal:
            retry_sig = self._maybe_emit_durable_exit_retry(
                event,
                state,
                position=position,
                short_avg=short_avg,
                long_avg=long_avg,
            )
            if retry_sig is not None:
                self._observe_forward_shadow(
                    event,
                    position,
                    signal=retry_sig,
                    state=state,
                    short_avg=short_avg,
                    long_avg=long_avg,
                    prev_short=prev_s,
                    prev_long=prev_l,
                )
                return retry_sig

        raw_dead_cross = (
            position.quantity > ZERO
            and prev_s >= prev_l
            and short_avg is not None
            and long_avg is not None
            and short_avg < long_avg
        )
        if position.quantity > ZERO and (
            raw_dead_cross or state.ma_exit_confirming
        ):
            sig = self._evaluate_ma_dead_cross_exit(
                event,
                state,
                position=position,
                short_avg=short_avg,
                long_avg=long_avg,
                raw_dead_cross=raw_dead_cross,
            )
            self._observe_forward_shadow(
                event,
                position,
                signal=sig,
                state=state,
                short_avg=short_avg,
                long_avg=long_avg,
                prev_short=prev_s,
                prev_long=prev_l,
            )
            return sig
        if position.quantity > ZERO:
            self._observe_forward_shadow(
                event,
                position,
                signal=None,
                state=state,
                short_avg=short_avg,
                long_avg=long_avg,
                prev_short=prev_s,
                prev_long=prev_l,
            )
        return None

    def _observe_forward_shadow(
        self,
        event: RealtimeMarketEvent,
        position: RealtimePositionState,
        *,
        signal: StrategySignal | None,
        state: ScopeStrategyState,
        short_avg: Decimal | None = None,
        long_avg: Decimal | None = None,
        prev_short: Decimal | None = None,
        prev_long: Decimal | None = None,
    ) -> None:
        """연구용 forward shadow — REAL emit/정책 변경 없음."""

        try:
            from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.hooks import (
                observe_from_evaluator,
            )

            observe_from_evaluator(
                scope=self.scope,
                config=self.config,
                event=event,
                position=position,
                signal=signal,
                short_ma=short_avg or state.last_eval_short,
                long_ma=long_avg or state.last_eval_long,
                prev_short_ma=prev_short or state.last_eval_prev_short,
                prev_long_ma=prev_long or state.last_eval_prev_long,
            )
        except Exception:  # noqa: BLE001
            return

    def _maybe_emit_durable_exit_retry(
        self,
        event: RealtimeMarketEvent,
        state: ScopeStrategyState,
        *,
        position: RealtimePositionState,
        short_avg: Decimal | None,
        long_avg: Decimal | None,
    ) -> StrategySignal | None:
        """WRK-014: durable intent due → STATE 재검증 → bounded retry SELL."""

        try:
            from stock_platform.operation.upbit_exit_intent.hooks import (
                prepare_durable_retry,
            )

            uba = int(getattr(self.scope, "account_id", 0) or 0)
            if not uba:
                return None
            prep = prepare_durable_retry(
                user_broker_account_id=uba,
                symbol=str(event.symbol),
                short_ma=short_avg,
                long_ma=long_avg,
            )
            if prep.get("action") != "emit_retry":
                return None
            intent_id = prep.get("exit_intent_id")
            retry_before = int(prep.get("retry_count_before") or 0)
            # opportunity_id로 fingerprint 충돌·중복 억제
            opp = f"exit_intent:{intent_id}:retry:{retry_before + 1}"
            return self._emit(
                event,
                state,
                SignalType.SELL,
                "MA_DEAD_CROSS",
                short_avg,
                long_avg,
                opportunity_id=opp,
                extra_metadata={
                    "ma_exit_confirmation": "REVALIDATED_STATE",
                    "exit_intent_id": intent_id,
                    "exit_attempt_kind": "RETRY",
                    "exit_attempt_index": retry_before + 1,
                    "exit_intent_retry": True,
                    "condition": prep.get("condition"),
                    "profit_only_gate": False,
                },
            )
        except Exception:  # noqa: BLE001
            return None

    def _ma_exit_thresholds(self):
        """config에 붙은 MA exit 임계값 (attach 시 policy에서 patch)."""

        from stock_platform.realtime.ma_exit_policy import MaExitThresholds

        cfg = self.config
        return MaExitThresholds(
            exit_min_ma_separation_pct=float(
                getattr(cfg, "exit_min_ma_separation_pct", 0.03) or 0.03
            ),
            ma_exit_min_holding_seconds=int(
                getattr(cfg, "ma_exit_min_holding_seconds", 180) or 180
            ),
            estimated_fee_rate=float(
                getattr(cfg, "estimated_fee_rate", 0.0005) or 0.0005
            ),
        )

    def _evaluate_ma_dead_cross_exit(
        self,
        event: RealtimeMarketEvent,
        state: ScopeStrategyState,
        *,
        position: RealtimePositionState,
        short_avg: Decimal | None,
        long_avg: Decimal | None,
        raw_dead_cross: bool,
    ) -> StrategySignal | None:
        """MA_DEAD_CROSS: confirmation + min-hold. 손실이어도 EMIT 허용."""

        from stock_platform.realtime.ma_exit_policy import (
            evaluate_ma_dead_cross_gate,
        )

        thresholds = self._ma_exit_thresholds()
        if raw_dead_cross and not state.ma_exit_confirming:
            state.ma_exit_confirming = True
            state.first_dead_cross_at = event.event_time or datetime.now(
                timezone.utc
            )

        gate = evaluate_ma_dead_cross_gate(
            raw_dead_cross_event=raw_dead_cross,
            confirming=bool(state.ma_exit_confirming),
            short_ma=short_avg,
            long_ma=long_avg,
            opened_at=getattr(position, "opened_at", None),
            thresholds=thresholds,
            now=event.event_time or datetime.now(timezone.utc),
            entry_price=position.average_entry_price,
            quantity=position.quantity,
            current_price=event.price,
            buy_fee=getattr(position, "buy_fee", None),
        )
        state.last_ma_exit_telemetry = {
            **gate,
            "first_dead_cross_at": (
                state.first_dead_cross_at.isoformat()
                if state.first_dead_cross_at
                else None
            ),
            "exit_min_ma_separation_pct": thresholds.exit_min_ma_separation_pct,
            "ma_exit_min_holding_seconds": thresholds.ma_exit_min_holding_seconds,
        }
        self._bump(f"ma_exit_{str(gate.get('decision') or 'HOLD').lower()}")

        decision = str(gate.get("decision") or "HOLD")
        if decision == "RESET":
            state.ma_exit_confirming = False
            state.first_dead_cross_at = None
            return None
        if decision == "EMIT":
            state.ma_exit_confirming = False
            first_at = state.first_dead_cross_at
            state.first_dead_cross_at = None
            # WRK-014: durable intent BEFORE initial SELL (idempotent)
            intent_id = None
            try:
                from stock_platform.operation.upbit_exit_intent.hooks import (
                    create_intent_on_ma_emit,
                    should_suppress_ma_exit_emit,
                )

                uba = int(getattr(self.scope, "account_id", 0) or 0)
                # deterministic ORDER_QTY_EXCEEDED cooldown — 동일 상태 재제출 금지
                if uba and should_suppress_ma_exit_emit(
                    user_broker_account_id=uba,
                    symbol=str(event.symbol),
                ):
                    self._bump("ma_exit_suppressed_deterministic_qty")
                    return None
                intent_id = create_intent_on_ma_emit(
                    user_broker_account_id=uba,
                    symbol=str(event.symbol),
                    signal_id=None,
                    strategy_id=getattr(self.scope, "strategy_id", None),
                    strategy_version=getattr(
                        self.scope, "strategy_version", None
                    ),
                    quantity=position.quantity,
                )
            except Exception:  # noqa: BLE001
                intent_id = None
            return self._emit(
                event,
                state,
                SignalType.SELL,
                "MA_DEAD_CROSS",
                short_avg,
                long_avg,
                extra_metadata={
                    "ma_exit_confirmation": "CONFIRMED",
                    "ma_separation_pct": gate.get("ma_separation_pct"),
                    "holding_seconds": gate.get("holding_seconds"),
                    "first_dead_cross_at": (
                        first_at.isoformat() if first_at else None
                    ),
                    "estimated_net_pnl": (gate.get("fee_aware") or {}).get(
                        "estimated_net_pnl"
                    ),
                    "estimated_net_return_pct": (gate.get("fee_aware") or {}).get(
                        "estimated_net_return_pct"
                    ),
                    "break_even_price": (gate.get("fee_aware") or {}).get(
                        "break_even_price"
                    ),
                    "fee_aware": gate.get("fee_aware"),
                    "profit_only_gate": False,
                    "exit_intent_id": intent_id,
                    "exit_attempt_kind": "INITIAL",
                    "exit_attempt_index": 0,
                },
            )
        # CONFIRMING / HOLD — 주문 없음
        if decision == "CONFIRMING":
            state.ma_exit_confirming = True
        return None

    def _uses_bullish_state_policy(self) -> bool:
        from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
            POLICY_BULLISH_STATE,
            normalize_entry_policy,
        )

        policy = normalize_entry_policy(self.config.entry_signal_policy)
        if self.portfolio_entry_ctx is not None:
            policy = normalize_entry_policy(self.portfolio_entry_ctx.policy)
        return policy == POLICY_BULLISH_STATE

    def _evaluate_portfolio_bullish_buy(
        self,
        event: RealtimeMarketEvent,
        state: ScopeStrategyState,
        *,
        short_avg: Decimal,
        long_avg: Decimal,
    ) -> StrategySignal | None:
        from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
            REASON_BULLISH,
            evaluate_bullish_state_entry,
            load_thresholds_from_settings,
            portfolio_entry_telemetry,
        )
        from stock_platform.common.settings import get_settings

        ctx = self.portfolio_entry_ctx
        uba_id = int(
            getattr(ctx, "user_broker_account_id", None)
            or getattr(self.scope, "account_id", 0)
            or 0
        )
        thresholds = (
            ctx.thresholds
            if ctx is not None
            else load_thresholds_from_settings(get_settings())
        )
        snap = None
        if ctx is not None:
            snap = ctx.by_symbol.get(event.symbol.upper())
        ok, block, detail = evaluate_bullish_state_entry(
            short_ma=short_avg,
            long_ma=long_avg,
            event_time=event.event_time,
            snap=snap,
            thresholds=thresholds,
        )
        selection_id = int(snap.selection_id) if snap and snap.selection_id else None
        strategy_id = getattr(self.scope, "strategy_id", None)
        trace_id: str | None = None
        emit_prov: dict[str, Any] | None = None
        if uba_id:
            try:
                from stock_platform.database.session import get_session_factory
                from stock_platform.operation.upbit_entry_execution_trace.hooks import (
                    trace_bullish_evaluation,
                )
                from stock_platform.operation.upbit_entry_execution_trace.service import (
                    build_provenance,
                    new_execution_trace_id,
                    resolve_lifecycle_kind,
                )

                _sf = get_session_factory()
                _sess = _sf()
                try:
                    if not ok:
                        trace_bullish_evaluation(
                            _sess,
                            user_broker_account_id=int(uba_id),
                            symbol=event.symbol.upper(),
                            strategy_id=strategy_id,
                            selection_id=selection_id,
                            technical_ok=False,
                            block_reason=block,
                            signal_emitted=False,
                            detail=detail,
                        )
                        _sess.commit()
                    else:
                        trace_id = new_execution_trace_id()
                        lifecycle = resolve_lifecycle_kind(
                            _sess,
                            user_broker_account_id=int(uba_id),
                            selection_id=selection_id,
                        )
                        emit_prov = build_provenance(
                            _sess,
                            user_broker_account_id=int(uba_id),
                            symbol=event.symbol.upper(),
                            strategy_id=strategy_id,
                            selection_id=selection_id,
                            execution_trace_id=trace_id,
                            lifecycle_kind=lifecycle,
                        )
                finally:
                    _sess.close()
            except Exception:  # noqa: BLE001
                pass
        # decision=BUY는 StrategySignal 생성(_emit) 성공 후에만 기록.
        # 기술적 조건만 통과하고 emit이 막히면 TECHNICAL_PASS로 구분해
        # UI에서 실주문 BUY와 혼동하지 않게 한다.
        if not ok:
            if uba_id:
                portfolio_entry_telemetry.record(
                    uba_id,
                    event.symbol.upper(),
                    decision="BLOCK",
                    block_reason=block,
                    reason_code=None,
                    snapshot=detail,
                )
                try:
                    from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.hooks import (
                        maybe_enroll_entry_signal_shadow,
                    )

                    maybe_enroll_entry_signal_shadow(
                        uba_id=int(uba_id),
                        symbol=event.symbol.upper(),
                        short_ma=short_avg,
                        long_ma=long_avg,
                        snap=snap,
                        decision="BLOCK",
                        block_reason=block,
                        detail=detail,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return None
        # 새 selection이면 이전 opportunity의 entry dedup/cooldown을 소비하지 않음
        if (
            selection_id is not None
            and state.last_bullish_selection_id is not None
            and int(state.last_bullish_selection_id) != int(selection_id)
        ):
            state.last_fingerprint = None
            state.last_signal_at = None
        signal = self._emit(
            event,
            state,
            SignalType.BUY,
            REASON_BULLISH,
            short_avg,
            long_avg,
            extra_metadata=emit_prov,
            opportunity_id=(
                f"sel:{int(selection_id)}" if selection_id is not None else None
            ),
        )
        if signal is not None and selection_id is not None:
            state.last_bullish_selection_id = int(selection_id)
        if uba_id and ok:
            try:
                from stock_platform.database.session import get_session_factory
                from stock_platform.operation.upbit_entry_execution_trace.hooks import (
                    trace_bullish_evaluation,
                )

                _sf = get_session_factory()
                _sess = _sf()
                try:
                    trace_bullish_evaluation(
                        _sess,
                        user_broker_account_id=int(uba_id),
                        symbol=event.symbol.upper(),
                        strategy_id=strategy_id,
                        selection_id=selection_id,
                        technical_ok=True,
                        block_reason=None,
                        signal_emitted=signal is not None,
                        signal_id=(
                            str(signal.signal_id) if signal is not None else None
                        ),
                        detail=detail,
                        execution_trace_id=trace_id,
                    )
                    _sess.commit()
                finally:
                    _sess.close()
            except Exception:  # noqa: BLE001
                pass
        if uba_id:
            if signal is None:
                detail = {
                    **detail,
                    "signal_emitted": False,
                    "technical_pass": True,
                }
                portfolio_entry_telemetry.record(
                    uba_id,
                    event.symbol.upper(),
                    decision="TECHNICAL_PASS",
                    block_reason="SIGNAL_EMIT_SUPPRESSED",
                    reason_code=None,
                    snapshot=detail,
                )
            else:
                detail = {**detail, "signal_emitted": True}
                portfolio_entry_telemetry.record(
                    uba_id,
                    event.symbol.upper(),
                    decision="BUY",
                    block_reason=None,
                    reason_code=REASON_BULLISH,
                    snapshot=detail,
                )
            # RESEARCH_ONLY forward shadow — REAL path 불변 / fail-open
            try:
                from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.hooks import (
                    maybe_enroll_entry_signal_shadow,
                )

                maybe_enroll_entry_signal_shadow(
                    uba_id=int(uba_id),
                    symbol=event.symbol.upper(),
                    short_ma=short_avg,
                    long_ma=long_avg,
                    snap=snap,
                    decision="BUY" if signal is not None else "TECHNICAL_PASS",
                    block_reason=(
                        None if signal is not None else "SIGNAL_EMIT_SUPPRESSED"
                    ),
                    detail=detail,
                )
            except Exception:  # noqa: BLE001
                pass
        return signal

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._by_symbol.clear()
            self._bars.reset()
            return
        self._by_symbol.pop(symbol.upper(), None)
        self._bars.reset(symbol)

    def status(self) -> dict:
        return {
            "scope_key": self.scope.scope_key,
            "short_window": self.config.short_window,
            "long_window": self.config.long_window,
            "timeframe": self.config.timeframe or "",
            "ma_input_unit": (
                "DAY" if self.config.uses_daily_bars() else "TICK"
            ),
            "portfolio_mode": bool(self.config.portfolio_mode),
            "entry_signal_policy": self.config.entry_signal_policy,
            "portfolio_entry_ctx": self.portfolio_entry_ctx is not None,
            "path_counters": dict(self.path_counters),
            "symbols": {
                sym: {
                    "warmup_status": st.warmup_status.value,
                    "buffer_len": len(st.prices),
                    "input_unit": st.input_unit,
                    "last_bar_date": (
                        st.last_bar_date.isoformat()
                        if st.last_bar_date
                        else None
                    ),
                    "last_signal_type": st.last_signal_type,
                    "last_signal_at": (
                        st.last_signal_at.isoformat()
                        if st.last_signal_at
                        else None
                    ),
                    "ma_exit_confirming": bool(st.ma_exit_confirming),
                    "first_dead_cross_at": (
                        st.first_dead_cross_at.isoformat()
                        if st.first_dead_cross_at
                        else None
                    ),
                    "last_ma_exit_telemetry": st.last_ma_exit_telemetry,
                    "last_error": st.last_error,
                }
                for sym, st in self._by_symbol.items()
            },
        }

    def _apply_daily_close(
        self,
        state: ScopeStrategyState,
        trade_date: date,
        close: Decimal,
        replaced_last: bool,
    ) -> None:
        """같은 날이면 last close 교체, 새 날이면 append. 일수를 tick 수만큼 늘리지 않음."""

        state.input_unit = "DAY"
        if replaced_last and state.prices:
            state.prices.pop()
        state.prices.append(close)
        state.last_bar_date = trade_date

    def _accept_event(
        self, state: ScopeStrategyState, event: RealtimeMarketEvent
    ) -> bool:
        from stock_platform.common.settings import get_settings

        max_age = float(
            getattr(get_settings(), "realtime_event_max_age_seconds", 10)
        )
        now = datetime.now(timezone.utc)
        age = (now - event.received_at).total_seconds()
        if age > max_age:
            return False
        if (
            state.last_sequence is not None
            and event.raw_sequence is not None
        ):
            if event.raw_sequence <= state.last_sequence:
                return False
        if (
            state.last_event_time is not None
            and event.event_time < state.last_event_time
            and event.raw_sequence is None
        ):
            return False
        if event.raw_sequence is not None:
            state.last_sequence = event.raw_sequence
        state.last_event_time = event.event_time
        return True

    def _passes_change(self, event: RealtimeMarketEvent) -> bool:
        if self.config.minimum_change_rate <= ZERO:
            return True
        if event.change_rate is None:
            return True
        return abs(event.change_rate) >= self.config.minimum_change_rate

    def _emit(
        self,
        event: RealtimeMarketEvent,
        state: ScopeStrategyState,
        signal_type: SignalType,
        reason: str,
        short_avg: Decimal | None,
        long_avg: Decimal | None,
        *,
        extra_metadata: dict | None = None,
        opportunity_id: str | None = None,
    ) -> StrategySignal | None:
        now = datetime.now(timezone.utc)
        if (
            state.last_signal_at is not None
            and self.config.cooldown_seconds > 0
        ):
            elapsed = (now - state.last_signal_at).total_seconds()
            if elapsed < self.config.cooldown_seconds:
                return None

        fingerprint = StrategySignal.build_fingerprint(
            scope_key=self.scope.scope_key,
            symbol=event.symbol,
            signal_type=signal_type.value,
            reason_code=reason,
            event_time=event.event_time,
            sequence=event.raw_sequence,
            opportunity_id=opportunity_id,
        )
        if state.last_fingerprint == fingerprint:
            return None

        meta = {
            "short_average": (
                str(short_avg) if short_avg is not None else None
            ),
            "long_average": (
                str(long_avg) if long_avg is not None else None
            ),
            "ma_input_unit": state.input_unit,
            "last_bar_date": (
                state.last_bar_date.isoformat()
                if state.last_bar_date
                else None
            ),
            # 주문/원장 키는 시세 exchange (broker_code=데이터소스와 혼동 금지)
            "exchange_code": (
                event.exchange_code or event.broker_code
            ),
            "source_code": event.source_code,
        }
        if extra_metadata:
            meta.update(dict(extra_metadata))

        signal = StrategySignal(
            signal_id=StrategySignal.build_id(
                scope_key=self.scope.scope_key,
                symbol=event.symbol,
            ),
            fingerprint=fingerprint,
            scope_key=self.scope.scope_key,
            user_id=self.scope.user_id,
            account_kind=self.scope.account_kind.value,
            account_id=self.scope.account_id,
            strategy_id=self.scope.strategy_id,
            strategy_version=self.scope.strategy_version,
            broker_code=self.scope.broker_code,
            market_type=self.scope.market_type,
            symbol=event.symbol.upper(),
            signal_type=signal_type.value,
            generated_at=now,
            event_time=event.event_time,
            reference_price=event.price or ZERO,
            reason_code=reason,
            metadata=meta,
        )
        state.last_fingerprint = fingerprint
        state.last_signal_at = now
        state.last_signal_type = signal_type.value
        return signal

    @staticmethod
    def _average(
        prices: deque[Decimal], window: int
    ) -> Decimal | None:
        if len(prices) < window:
            return None
        values = list(prices)[-window:]
        return sum(values) / Decimal(window)
