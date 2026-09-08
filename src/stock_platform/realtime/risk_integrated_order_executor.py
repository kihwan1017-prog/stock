from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
    RealtimeExecutionResult,
)
from stock_platform.realtime.execution_scope import (
    SUPPORTED_LIVE_BROKERS,
    resolve_signal_broker_code,
    resolve_signal_user_broker_account_id,
)
from stock_platform.realtime.order_executor import (
    RealtimePaperOrderExecutor,
)
from stock_platform.realtime.safety_guard import (
    RealtimeOrderSafetyGuard,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
)
from stock_platform.risk_engine.kill_switch_guard import (
    KillSwitchUnavailableError,
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.order_guard import (
    DatabaseBackedRiskOrderGuard,
)


def resolve_execution_environment(
    config: RealtimeExecutionConfig,
    signal: RealtimeSignal,
) -> str:
    """실행 모드·계좌 종류로 PAPER/MOCK/LIVE 결정 (기본 PAPER, Fail Closed)."""

    if config.mode == RealtimeExecutionMode.LIVE:
        return "LIVE"
    if config.mode == RealtimeExecutionMode.MOCK:
        # MOCK은 LIVE HTTP 금지 — KiwoomMockAdapter 경로만
        return "MOCK"
    account_kind = str(getattr(signal, "account_kind", "") or "").upper()
    if account_kind == "USER_BROKER":
        # Scope가 실계좌인데 mode가 PAPER면 LIVE enqueue 금지 — PAPER 유지
        return "PAPER"
    return "PAPER"


def resolve_portfolio_order_amount_krw(begin: dict[str, Any]) -> Decimal | None:
    """begin_entry_from_signal 결과 → Risk-compatible executable KRW."""

    portfolio_amount_krw = (
        begin.get("approved_amount_krw")
        or begin.get("final_order_amount_krw")
        or begin.get("reserved_amount_krw")
        or begin.get("allocated_amount_krw")
    )
    if portfolio_amount_krw is None:
        return None
    return Decimal(str(portfolio_amount_krw))


class RiskIntegratedRealtimeOrderExecutor:
    """
    기본 설정 검증 → Persistent Kill Switch
    → Risk Engine → Safety Guard → OrderExecutionService.
    """

    def __init__(
        self,
        *,
        session: Session,
        execution_config: RealtimeExecutionConfig,
        safety_guard: RealtimeOrderSafetyGuard,
    ) -> None:
        self._session = session
        self._execution_config = execution_config
        self._safety_guard = safety_guard

    def execute(
        self,
        signal: RealtimeSignal,
    ) -> RealtimeExecutionResult:
        broker_code = resolve_signal_broker_code(signal)
        environment = resolve_execution_environment(
            self._execution_config, signal
        )
        self._set_entry_trace_context(signal)

        # STEP 8-5-9 — Signal Scope 계좌 우선 (환경변수 기본 계좌 우회 금지)
        exec_account_id = self._execution_config.account_id
        user_broker_account_id = getattr(
            self._execution_config, "user_broker_account_id", None
        )
        account_kind = str(
            getattr(signal, "account_kind", "") or ""
        ).upper()

        if getattr(signal, "scope_key", None):
            if not getattr(signal, "account_id", None):
                return self._skipped(signal, "SCOPE_ACCOUNT_REQUIRED")
            if account_kind == "PAPER":
                exec_account_id = int(signal.account_id)
                user_broker_account_id = None
            elif account_kind == "USER_BROKER":
                user_broker_account_id = int(signal.account_id)
                # LIVE UBA 주문도 trading_order.account_id(Paper FK)는
                # 설정 기본 Paper 계좌를 유지한다.
                exec_account_id = self._execution_config.account_id

        signal_uba = resolve_signal_user_broker_account_id(signal)
        if signal_uba is not None and account_kind == "USER_BROKER":
            user_broker_account_id = int(signal_uba)

        if (
            environment == "LIVE"
            and broker_code == "UPBIT"
            and str(signal.action.value).upper() == "BUY"
            and user_broker_account_id
            and getattr(signal, "execution_trace_id", None)
        ):
            self._trace_executor_received(signal, user_broker_account_id)

        cfg_uba = getattr(
            self._execution_config, "user_broker_account_id", None
        )
        cfg_broker = str(
            getattr(self._execution_config, "broker_code", "") or ""
        ).upper()
        if environment == "LIVE" and cfg_uba:
            if account_kind == "PAPER":
                return self._skipped(signal, "PAPER_SIGNAL_IN_LIVE")
            if user_broker_account_id is None:
                return self._skipped(signal, "LIVE_UBA_REQUIRED")
            if int(user_broker_account_id) != int(cfg_uba):
                return self._skipped(signal, "CROSS_UBA_SIGNAL")
            expected_broker = cfg_broker or broker_code
            if expected_broker not in SUPPORTED_LIVE_BROKERS:
                return self._skipped(signal, "UNSUPPORTED_BROKER")
            if broker_code != expected_broker:
                return self._skipped(signal, "CROSS_BROKER_SIGNAL")

        if (
            environment == "LIVE"
            and broker_code == "UPBIT"
            and user_broker_account_id
        ):
            from stock_platform.trading.upbit_24x7_control import (
                evaluate_runtime_run_gates,
            )

            run_gates = evaluate_runtime_run_gates(
                self._session,
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=getattr(signal, "strategy_id", None),
                enforce_pause=True,
            )
            if not run_gates.get("ok"):
                return self._skipped(
                    signal,
                    str(
                        (run_gates.get("blockers") or ["RUN_GATE_FAILED"])[0]
                    ),
                )

        if (
            environment == "LIVE"
            and broker_code == "KIWOOM"
            and user_broker_account_id
        ):
            from stock_platform.realtime.kiwoom_runtime_run_gates import (
                evaluate_kiwoom_runtime_run_gates,
            )

            run_gates = evaluate_kiwoom_runtime_run_gates(
                self._session,
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=getattr(signal, "strategy_id", None),
                tick_source_code=getattr(signal, "source_code", None),
            )
            if not run_gates.get("ok"):
                return self._skipped(
                    signal,
                    str(
                        (run_gates.get("blockers") or ["RUN_GATE_FAILED"])[0]
                    ),
                )
            from stock_platform.realtime.kiwoom_market_source_gate import (
                evaluate_real_execution_market_source,
            )

            market_src = evaluate_real_execution_market_source(
                self._session,
                user_broker_account_id=int(user_broker_account_id),
                broker_code="KIWOOM",
                source_code=getattr(signal, "source_code", None),
            )
            if market_src.get("applied") and not market_src.get("ok"):
                return self._skipped(
                    signal,
                    str(market_src.get("reason") or "MARKET_SOURCE_BLOCKED"),
                )
            from stock_platform.realtime.kiwoom_market_realtime_runtime import (
                kiwoom_market_realtime_runtime,
            )
            from stock_platform.broker.kiwoom.execution_env import (
                kiwoom_uba_has_explicit_real_execution,
            )
            from stock_platform.broker.kiwoom.market_realtime_contract import (
                REASON_MARKET_DATA_DISCONNECTED,
            )

            if kiwoom_uba_has_explicit_real_execution(
                self._session, int(user_broker_account_id)
            ):
                feed = kiwoom_market_realtime_runtime.status()
                client = feed.get("client") or {}
                if not bool(client.get("connected")):
                    return self._skipped(
                        signal,
                        REASON_MARKET_DATA_DISCONNECTED,
                    )

        account_number = self._resolve_account_number(
            broker_code=broker_code,
            environment=environment,
            user_broker_account_id=user_broker_account_id,
            paper_account_id=exec_account_id,
        )
        if environment == "LIVE" and not account_number:
            return self._skipped(
                signal,
                "RISK_ACCOUNT_NUMBER_MISSING",
            )

        # Account Pause(Recovery Lock) — Signal 경로에서도 차단
        try:
            from stock_platform.broker.recovery_lock import (
                RecoveryAccountLockService,
            )

            lock = RecoveryAccountLockService(self._session)
            paused = False
            if environment == "LIVE" or environment == "MOCK":
                if user_broker_account_id is not None:
                    paused = (
                        lock.is_trading_paused(
                            user_broker_account_id=int(
                                user_broker_account_id
                            ),
                            broker_code=broker_code,
                        )
                        is True
                    )
            else:
                paused = (
                    lock.is_trading_paused(
                        paper_account_id=int(exec_account_id),
                        broker_code=broker_code,
                    )
                    is True
                )
            if paused:
                return self._skipped(signal, "ACCOUNT_PAUSED")
        except Exception:  # noqa: BLE001
            # Pause 조회 실패 시 BUY는 fail-closed, SELL은 위험축소로 통과
            if str(signal.action.value).upper() != "SELL":
                return self._skipped(signal, "ACCOUNT_PAUSE_CHECK_FAILED")

        # FULL_MARKET Dynamic: ENTRY만 assignment/warmup/cooldown gate
        portfolio_approved_amount: Decimal | None = None
        if (
            str(signal.action.value).upper() == "BUY"
            and environment == "LIVE"
            and user_broker_account_id is not None
            and str(broker_code).upper() == "UPBIT"
        ):
            try:
                from stock_platform.operation.upbit_full_market.service import (
                    UpbitFullMarketAssignmentService,
                )

                allowed, fm_reason = UpbitFullMarketAssignmentService(
                    self._session
                ).entry_allowed(
                    int(user_broker_account_id),
                    symbol=str(getattr(signal, "symbol", "") or None),
                )
                if not allowed:
                    return self._skipped(
                        signal, f"FULL_MARKET_{fm_reason}"
                    )
                # Portfolio: WAITING_SIGNAL → reserve → ENTRY_PENDING (signal 직후)
                from stock_platform.operation.upbit_full_market.constants import (
                    is_full_market_portfolio,
                )
                from stock_platform.operation.upbit_full_market.portfolio_service import (
                    UpbitPortfolioService,
                )

                fm_status = UpbitFullMarketAssignmentService(
                    self._session
                ).status_dict(int(user_broker_account_id))
                if is_full_market_portfolio(fm_status.get("mode")):
                    begin = UpbitPortfolioService(
                        self._session
                    ).begin_entry_from_signal(
                        int(user_broker_account_id),
                        symbol=str(getattr(signal, "symbol", "") or ""),
                        available_krw=None,
                    )
                    # already=True 는 동일 심볼 ENTRY_PENDING 예약 존재 —
                    # 두 번째 BUY를 절대 생성하지 않음 (overlapping entry 방지)
                    if begin.get("already"):
                        return self._skipped(
                            signal,
                            "PORTFOLIO_ENTRY_ALREADY_PENDING",
                        )
                    if not begin.get("ok"):
                        return self._skipped(
                            signal,
                            f"PORTFOLIO_{begin.get('reason') or 'BEGIN_ENTRY_FAILED'}",
                        )
                    portfolio_approved_amount = resolve_portfolio_order_amount_krw(
                        begin
                    )
                    # begin 성공 후 approved 없으면 100k config fallback 금지 (fail-closed)
                    if portfolio_approved_amount is None:
                        return self._skipped(
                            signal,
                            "PORTFOLIO_APPROVED_AMOUNT_MISSING",
                        )
            except Exception:  # noqa: BLE001
                return self._skipped(signal, "FULL_MARKET_GATE_FAILED")

        try:
            PersistentKillSwitchGuard(
                self._session
            ).require_order_allowed(
                side=signal.action.value,
                allow_sell=True,
                exchange_code=signal.exchange_code,
                user_broker_account_id=user_broker_account_id,
                paper_account_id=(
                    int(exec_account_id)
                    if environment == "PAPER"
                    else None
                ),
            )
        except KillSwitchUnavailableError:
            return self._skipped(
                signal,
                "KILL_SWITCH_UNAVAILABLE",
            )
        except PermissionError:
            return self._skipped(
                signal,
                "GLOBAL_KILL_SWITCH_ACTIVE",
            )

        # MA Signal → AI Gate (LLM은 주문 생성/한도 확대 금지)
        order_amount = Decimal(str(self._execution_config.order_amount))
        if portfolio_approved_amount is not None:
            order_amount = portfolio_approved_amount
        try:
            from stock_platform.realtime.ai_signal_gate import (
                evaluate_ai_signal_gate,
            )
            from stock_platform.realtime.ai_signal_gate_models import (
                AiSignalGateDecision,
            )

            gate = evaluate_ai_signal_gate(
                self._session,
                signal,
                environment=environment,
            )
            if gate.decision == AiSignalGateDecision.HOLD:
                return self._skipped(signal, gate.reason_code)
            if gate.decision == AiSignalGateDecision.REDUCE:
                order_amount = (
                    order_amount * Decimal(str(gate.size_multiplier))
                )
        except Exception:  # noqa: BLE001
            # LIVE Fail Closed — gate 예외 시 신규 AI-gated 주문 차단
            # risk-reducing EXIT는 Gate 예외로도 막지 않음
            from stock_platform.realtime.ai_signal_gate_exit_policy import (
                should_bypass_ai_gate,
            )
            from stock_platform.realtime.ai_signal_gate_policy import (
                is_ai_signal_gate_active,
            )

            bypass, _bypass_code = should_bypass_ai_gate(signal)
            if not bypass and (
                environment == "LIVE"
                and bool(
                    getattr(
                        get_settings(),
                        "autotrading_ai_live_fail_closed",
                        True,
                    )
                )
                and is_ai_signal_gate_active(environment)
            ):
                return self._skipped(signal, "AI_GATE_EXCEPTION")

        if order_amount <= 0:
            return self._skipped(signal, "AI_GATE_REDUCE_ZERO_AMOUNT")

        # BUY ENTRY: nominal config(order_amount) → effective Risk clamp
        # (100000 default 를 그대로 qty 산정에 쓰지 않음)
        side_u = str(signal.action.value or "").upper()
        if side_u == "BUY":
            from stock_platform.realtime.risk_aware_entry_sizing import (
                resolve_risk_aware_entry_size,
            )

            sized = resolve_risk_aware_entry_size(
                self._session,
                user_broker_account_id=user_broker_account_id,
                user_id=(
                    getattr(signal, "user_id", None)
                    or getattr(self._execution_config, "user_id", None)
                ),
                signal_price=Decimal(str(signal.signal_price)),
                nominal_order_amount=order_amount,
                exchange_code=str(signal.exchange_code or "KRX"),
            )
            if not sized.get("ok"):
                return self._skipped(
                    signal,
                    str(sized.get("skip_reason") or "ENTRY_SIZING_FAILED"),
                )
            quantity = Decimal(str(sized["quantity"]))
            order_amount = Decimal(str(sized["order_amount"]))
        else:
            quantity = (order_amount / signal.signal_price).quantize(
                Decimal("0.00000001")
            )
        if quantity <= 0:
            return self._skipped(signal, "AI_GATE_REDUCE_ZERO_QTY")

        # 매도: 보유 수량 초과 주문 방지 (PAPER / MOCK ledger)
        if signal.action.value.upper() == "SELL" and getattr(
            signal, "account_id", None
        ):
            account_kind_u = str(
                getattr(signal, "account_kind", "") or ""
            ).upper()
            if account_kind_u == "PAPER":
                from stock_platform.trading.account_models import (
                    PaperPosition,
                )

                held = self._session.scalar(
                    select(PaperPosition.quantity).where(
                        PaperPosition.account_id == int(signal.account_id),
                        PaperPosition.symbol
                        == str(signal.symbol).upper(),
                        PaperPosition.quantity > 0,
                    )
                )
                if held is not None:
                    held_qty = Decimal(str(held))
                    if held_qty <= 0:
                        return self._skipped(signal, "NO_POSITION_TO_SELL")
                    if quantity > held_qty:
                        quantity = held_qty
            elif account_kind_u == "USER_BROKER" and environment in {
                "MOCK",
                "LIVE",
            }:
                from stock_platform.broker.account_models import (
                    BrokerPositionSnapshotEntity,
                )

                held = self._session.scalar(
                    select(BrokerPositionSnapshotEntity.quantity).where(
                        BrokerPositionSnapshotEntity.user_broker_account_id
                        == int(signal.account_id),
                        BrokerPositionSnapshotEntity.symbol
                        == str(signal.symbol).upper(),
                        BrokerPositionSnapshotEntity.quantity > 0,
                    )
                )
                if held is None or Decimal(str(held)) <= 0:
                    return self._skipped(signal, "NO_POSITION_TO_SELL")
                # MOCK/LIVE AUTO: broker 전량이 아니라 canonical EXIT 수량
                # (strategy-owned ∩ sellable ∩ max_order_quantity)
                requested_sell = Decimal(str(held))
                try:
                    from stock_platform.risk_engine.exit_sell_quantity import (
                        resolve_exit_sell_quantity,
                    )
                    from stock_platform.risk_engine.resolved_policy import (
                        ResolvedRiskPolicyResolver,
                    )

                    policy = ResolvedRiskPolicyResolver(
                        self._session
                    ).resolve(
                        user_id=getattr(signal, "user_id", None),
                        user_broker_account_id=int(signal.account_id),
                    )
                    plan = resolve_exit_sell_quantity(
                        self._session,
                        user_broker_account_id=int(signal.account_id),
                        symbol=str(signal.symbol).upper(),
                        exchange_code=str(
                            getattr(signal, "exchange_code", "") or ""
                        ),
                        environment=environment,
                        broker_code=broker_code,
                        requested_quantity=requested_sell,
                        max_order_quantity=getattr(
                            policy, "max_order_quantity", None
                        ),
                        require_strategy_owned=True,
                    )
                    if plan.sell_quantity <= 0:
                        return self._skipped(
                            signal,
                            "NO_SELLABLE_STRATEGY_QTY"
                            if "NO_STRATEGY_OWNED" in plan.capped_by
                            else "NO_POSITION_TO_SELL",
                        )
                    quantity = plan.sell_quantity
                except Exception:  # noqa: BLE001
                    # fail-closed: 산정 실패 시 전량 제출 금지 → skip
                    return self._skipped(
                        signal, "EXIT_SELL_QTY_RESOLVE_FAILED"
                    )

        # MOCK/LIVE SELL도 outstanding/EXIT Risk를 건너뛰지 않는다.
        # EXIT 수량은 위에서 canonical plan으로 이미 적용했다.
        risk_result = DatabaseBackedRiskOrderGuard(
            self._session,
            broker_code=broker_code,
        ).check(
            account_number=account_number or f"PAPER-{exec_account_id}",
            # LIVE/UBA: Paper FK와 XOR — Risk ownership Fail Closed
            account_id=(
                None
                if (
                    environment in {"LIVE", "MOCK"}
                    and user_broker_account_id is not None
                )
                else exec_account_id
            ),
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            side=signal.action.value,
            quantity=quantity,
            price=signal.signal_price,
            user_id=(
                getattr(signal, "user_id", None)
                or getattr(self._execution_config, "user_id", None)
            ),
            user_broker_account_id=user_broker_account_id,
            order_source="AUTO",
            is_risk_reducing=(
                signal.action.value.upper() == "SELL"
            ),
            environment=environment,
            # UPBIT MARKET BUY: qty*price 재계산 dust로 max_order 초과 방지
            quote_amount=order_amount,
            reference_unit_price=signal.signal_price,
        )
        risk_allowed = risk_result.allowed
        risk_blocked = risk_result.blocked_reason

        if not risk_allowed:
            return self._skipped(
                signal,
                risk_blocked or "RISK_ENGINE_BLOCKED",
            )

        from stock_platform.trading.account_models import (
            PaperPosition,
        )

        if (
            environment in {"LIVE", "MOCK"}
            and user_broker_account_id is not None
        ):
            from stock_platform.broker.account_models import (
                BrokerPositionSnapshotEntity,
            )

            broker_u = str(broker_code or "").upper()
            if broker_u == "UPBIT":
                # AUTO slot: AUTO-owned + ENTRY reservation only
                from stock_platform.operation.upbit_full_market.auto_slot_count import (
                    count_auto_slots_used,
                )

                open_position_count = count_auto_slots_used(
                    self._session,
                    user_broker_account_id=int(user_broker_account_id),
                    broker_code="UPBIT",
                )
            else:
                open_position_count = self._session.scalar(
                    select(func.count())
                    .select_from(BrokerPositionSnapshotEntity)
                    .where(
                        BrokerPositionSnapshotEntity.user_broker_account_id
                        == int(user_broker_account_id),
                        BrokerPositionSnapshotEntity.quantity > 0,
                    )
                ) or 0
        else:
            open_position_count = self._session.scalar(
                select(func.count())
                .select_from(PaperPosition)
                .where(
                    PaperPosition.account_id
                    == exec_account_id,
                    PaperPosition.quantity > 0,
                )
            ) or 0

        unlock_token = None
        if self._execution_config.mode == RealtimeExecutionMode.LIVE:
            unlock_token = getattr(
                self._safety_guard._config, "live_unlock_token", None
            )

        decision = self._safety_guard.evaluate(
            signal=signal,
            mode=self._execution_config.mode,
            order_amount=order_amount,
            open_position_count=int(open_position_count),
            live_unlock_token=unlock_token,
        )
        if not decision.allowed:
            reason = decision.reason_code
            # UPBIT AUTO slot 한도 — canonical reason (compat: MAX_OPEN alias)
            if (
                str(broker_code or "").upper() == "UPBIT"
                and reason == "MAX_OPEN_POSITIONS_REACHED"
            ):
                reason = "AUTO_POSITION_LIMIT_REACHED"
            return self._skipped(
                signal,
                reason,
            )

        from stock_platform.order.live_dry_run import is_live_dry_run_mode
        from stock_platform.order.live_shadow import is_live_shadow_mode

        meta = {
            "source": "REALTIME_SIGNAL",
            "signal_reason": signal.reason_code,
            "execution_mode": self._execution_config.mode.value,
            "environment": environment,
            "resolved_broker_code": broker_code,
            "scope_key": getattr(signal, "scope_key", None),
            "runtime_scope": getattr(signal, "scope_key", None),
            "strategy_id": getattr(signal, "strategy_id", None),
            "strategy_version": getattr(signal, "strategy_version", None),
            "signal_id": getattr(signal, "signal_id", None),
            "source_signal_fingerprint": getattr(
                signal, "fingerprint", None
            ),
            "order_source": "AUTO",
        }
        # UBA1380 P1 — FUTURE BUY만 immutable risk snapshot (기존 주문 백필 금지)
        if str(signal.action.value).upper() == "BUY":
            try:
                from stock_platform.operation.autotrading_truth_bundle import (
                    build_risk_decision_snapshot,
                    maybe_stamp_risk_decision_snapshot,
                )

                snap = build_risk_decision_snapshot(
                    allowed=True,
                    result="PASS",
                    reason_codes=["RISK_PASS", "LIVE_SAFETY_PASS"],
                    limits={
                        "open_position_count": int(open_position_count),
                    },
                    usage={
                        "broker_code": str(broker_code or "").upper(),
                        "order_source": "AUTO",
                    },
                    extra={
                        "risk_blocked": risk_blocked,
                        "safety_reason": getattr(
                            decision, "reason_code", None
                        ),
                    },
                )
                meta = maybe_stamp_risk_decision_snapshot(
                    meta, snap, side="BUY"
                )
            except Exception:  # noqa: BLE001
                pass
        # SELL provenance — exit_reason과 signal_reason 동시 stamp (집계 단일화)
        if str(signal.action.value).upper() == "SELL" and signal.reason_code:
            meta["exit_reason"] = signal.reason_code
        # WRK-014 exit intent lineage
        sig_meta = getattr(signal, "metadata", None) or {}
        if isinstance(sig_meta, dict):
            for k in (
                "exit_intent_id",
                "exit_attempt_kind",
                "exit_attempt_index",
                "exit_intent_retry",
            ):
                if sig_meta.get(k) is not None:
                    meta[k] = sig_meta.get(k)
        for key in (
            "execution_trace_id",
            "candidate_selection_id",
            "candidate_id",
            "waiting_id",
            "lifecycle_kind",
        ):
            val = getattr(signal, key, None)
            if val is not None:
                meta[key] = val
        # AUTO entry provenance — ranking 미변경, selection 관측만 stamp
        sel_id = getattr(signal, "candidate_selection_id", None)
        if sel_id is not None:
            try:
                from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.lineage import (
                    resolve_candidate_provenance,
                )

                prov = resolve_candidate_provenance(
                    self._session,
                    selection_id=int(sel_id),
                    order_meta=meta,
                )
                for pk in (
                    "scanner_rank",
                    "scanner_score",
                    "candidate_universe_size",
                    "candidate_selected_at",
                    "variant_scores",
                    "scanner_run_id",
                ):
                    if prov.get(pk) not in (None, "NOT_RECORDED", {}):
                        meta[pk] = prov[pk]
            except Exception:  # noqa: BLE001
                pass
        if getattr(signal, "execution_trace_id", None):
            self._trace_order_intent(signal, user_broker_account_id)
        if environment == "LIVE" and is_live_dry_run_mode():
            meta["dry_run"] = True
            meta["dry_run_mode"] = "LIVE_DRY_RUN"
        elif environment == "LIVE" and is_live_shadow_mode():
            meta["shadow"] = True
            meta["shadow_mode"] = "LIVE_SHADOW"

        from stock_platform.realtime.autotrading_idempotency import (
            build_autotrading_idempotency_key,
        )

        idem_key = build_autotrading_idempotency_key(
            signal,
            user_broker_account_id=user_broker_account_id,
            paper_account_id=(
                int(exec_account_id)
                if environment == "PAPER" and exec_account_id is not None
                else None
            ),
        )

        # Canonical numeric strategy identity (reason_code 는 label 전용)
        canonical_strategy_id = getattr(signal, "strategy_id", None)
        try:
            if canonical_strategy_id is not None:
                canonical_strategy_id = int(canonical_strategy_id)
        except (TypeError, ValueError):
            canonical_strategy_id = None

        # Common Entry Admission — AUTO LIVE BUY only (final LiveOrderSafetyPipeline 유지)
        if (
            environment == "LIVE"
            and str(signal.action.value).upper() == "BUY"
            and user_broker_account_id is not None
        ):
            try:
                from stock_platform.trading.entry_admission_service import (
                    EntryAdmissionService,
                    should_emit_admission_telegram,
                )

                uid = getattr(self._execution_config, "user_id", None) or getattr(
                    signal, "user_id", None
                )
                admission = EntryAdmissionService(
                    self._session
                ).evaluate_auto_buy(
                    user_id=int(uid) if uid is not None else None,
                    user_broker_account_id=int(user_broker_account_id),
                    broker_code=str(broker_code or ""),
                    symbol=str(signal.symbol or ""),
                    strategy_id=canonical_strategy_id,
                    strategy_deployment_id=getattr(
                        signal, "strategy_deployment_id", None
                    ),
                    environment="LIVE",
                )
                if not admission.allowed:
                    # persistent block: intent 미생성 + Telegram day-dedupe
                    try:
                        if should_emit_admission_telegram(
                            user_broker_account_id=int(
                                user_broker_account_id
                            ),
                            reason_code=admission.reason_code,
                        ):
                            from stock_platform.order.live_safety_audit import (
                                emit_live_order_telegram,
                            )

                            emit_live_order_telegram(
                                event_type="ENTRY_ADMISSION_DENIED",
                                title=(
                                    "AUTO entry admission denied: "
                                    f"{admission.reason_code}"
                                ),
                                message=(
                                    f"{broker_code} {signal.symbol} BUY "
                                    f"— {admission.reason_code} "
                                    f"(source={admission.source})"
                                ),
                                detail=admission.to_dict(),
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    return self._skipped(signal, admission.reason_code)
            except Exception:  # noqa: BLE001 — final safety gate 가 재검증
                pass

        result = OrderExecutionService(self._session).submit(
            OrderExecutionCommand(
                account_id=exec_account_id,
                broker_code=broker_code,
                exchange_code=signal.exchange_code,
                symbol=signal.symbol,
                side=OrderSide(signal.action.value),
                order_type=OrderType.LIMIT,
                quantity=quantity,
                order_amount=None,
                price=signal.signal_price,
                # reason_code 를 strategy_code 로 넣지 않음 (identity 혼동 금지)
                strategy_code=None,
                strategy_id=canonical_strategy_id,
                account_number=account_number or None,
                # LIVE: LiveSafety(ARM/daily/vault) 우회 금지 — 상단 Risk만으로 부족
                # PAPER: 기존 상단 검증 재사용 (이중 검사 부담 완화)
                skip_risk_checks=(environment == "PAPER"),
                metadata_payload=meta,
                actor="REALTIME_EXECUTION",
                order_source="AUTO",
                environment=environment,
                is_risk_reducing=(
                    signal.action.value.upper() == "SELL"
                ),
                user_id=getattr(
                    self._execution_config, "user_id", None
                ) or getattr(signal, "user_id", None),
                user_broker_account_id=user_broker_account_id,
                idempotency_key=idem_key,
            )
        )

        if not result.allowed:
            self._trace_executor_rejected(signal, result.reason_code)
            # WRK-014: retry 거부 시 intent BLOCKED (retry_count 미증가)
            if (
                str(signal.action.value).upper() == "SELL"
                and str(getattr(signal, "reason_code", "") or "").upper()
                == "MA_DEAD_CROSS"
            ):
                try:
                    from stock_platform.operation.upbit_exit_intent.hooks import (
                        mark_intent_blocked,
                    )

                    sig_meta = getattr(signal, "metadata", None) or {}
                    iid = (
                        sig_meta.get("exit_intent_id")
                        if isinstance(sig_meta, dict)
                        else None
                    )
                    if iid is not None:
                        mark_intent_blocked(
                            exit_intent_id=int(iid),
                            reason=str(result.reason_code or "EXECUTOR_REJECTED"),
                        )
                except Exception:  # noqa: BLE001
                    pass
            return self._skipped(
                signal,
                result.reason_code,
            )

        if result.order_id is not None:
            self._trace_order_persisted(
                signal,
                user_broker_account_id,
                order_id=int(result.order_id),
                outbox_id=getattr(result, "outbox_id", None),
            )
            # WRK-014: link SELL order to durable exit intent
            if (
                str(signal.action.value).upper() == "SELL"
                and str(getattr(signal, "reason_code", "") or "").upper()
                == "MA_DEAD_CROSS"
            ):
                try:
                    from stock_platform.operation.upbit_exit_intent.hooks import (
                        link_order_to_intent,
                    )

                    sig_meta = getattr(signal, "metadata", None) or {}
                    intent_id = None
                    is_retry = False
                    if isinstance(sig_meta, dict):
                        intent_id = sig_meta.get("exit_intent_id")
                        is_retry = bool(
                            sig_meta.get("exit_intent_retry")
                            or str(sig_meta.get("exit_attempt_kind") or "")
                            .upper()
                            == "RETRY"
                        )
                    link_order_to_intent(
                        exit_intent_id=(
                            int(intent_id) if intent_id is not None else None
                        ),
                        user_broker_account_id=(
                            int(user_broker_account_id)
                            if user_broker_account_id is not None
                            else None
                        ),
                        symbol=str(signal.symbol or ""),
                        order_id=int(result.order_id),
                        signal_id=getattr(signal, "signal_id", None),
                        is_retry=is_retry,
                    )
                except Exception:  # noqa: BLE001
                    pass

        # Portfolio BUY: 주문 생성 직후 ENTRY_PENDING slot에 entry_order_id 연결
        if (
            str(signal.action.value).upper() == "BUY"
            and environment == "LIVE"
            and user_broker_account_id is not None
            and str(broker_code).upper() == "UPBIT"
            and result.order_id is not None
        ):
            try:
                from stock_platform.operation.upbit_full_market.constants import (
                    is_full_market_portfolio,
                )
                from stock_platform.operation.upbit_full_market.portfolio_service import (
                    UpbitPortfolioService,
                )

                fm_status = UpbitFullMarketAssignmentService(
                    self._session
                ).status_dict(int(user_broker_account_id))
                if is_full_market_portfolio(fm_status.get("mode")):
                    UpbitPortfolioService(self._session).link_entry_order_to_pending_slot(
                        int(user_broker_account_id),
                        order_id=int(result.order_id),
                        symbol=str(signal.symbol or ""),
                        actor="REALTIME_EXECUTION",
                    )
            except Exception:  # noqa: BLE001
                pass

        self._safety_guard.mark_order_executed(signal)

        return RealtimeExecutionResult(
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            signal_action=signal.action.value,
            execution_mode=self._execution_config.mode.value,
            order_id=result.order_id,
            trade_id=None,
            order_status=result.status_code or "PENDING",
            quantity=result.quantity or Decimal("0"),
            order_price=result.price or signal.signal_price,
            reason_code=result.reason_code,
            executed_at=datetime.now(timezone.utc),
        )

    def _resolve_account_number(
        self,
        *,
        broker_code: str,
        environment: str,
        user_broker_account_id: int | None,
        paper_account_id: int,
    ) -> str:
        """LIVE/MOCK는 UBA, PAPER는 합성 식별자 (Kiwoom 전역 강제 금지)."""

        if environment in {"LIVE", "MOCK"} and user_broker_account_id is not None:
            from stock_platform.trading.account_models import (
                UserBrokerAccount,
            )

            uba = self._session.get(
                UserBrokerAccount, int(user_broker_account_id)
            )
            if uba is not None:
                ref = (
                    getattr(uba, "masked_account_ref", None)
                    or getattr(uba, "account_alias", None)
                    or ""
                )
                if ref:
                    return str(ref)
                return f"UBA:{int(user_broker_account_id)}"

        if environment == "LIVE":
            settings = get_settings()
            if broker_code == "UPBIT":
                return str(
                    getattr(settings, "upbit_account_ref", "") or ""
                ).strip()
            return str(settings.kiwoom_account_number or "").strip()

        return f"PAPER-{int(paper_account_id)}"

    def _set_entry_trace_context(self, signal: RealtimeSignal) -> None:
        try:
            from stock_platform.operation.upbit_entry_execution_trace.context import (
                clear_current,
                set_current,
            )
            from stock_platform.operation.upbit_entry_execution_trace.service import (
                provenance_from_signal,
            )

            prov = provenance_from_signal(signal)
            if prov.get("execution_trace_id"):
                set_current(prov)
            else:
                clear_current()
        except Exception:  # noqa: BLE001
            pass

    def _trace_base(self, signal: RealtimeSignal, uba_id: int | None) -> dict:
        return {
            "execution_trace_id": getattr(signal, "execution_trace_id", None),
            "user_broker_account_id": int(uba_id or getattr(signal, "user_broker_account_id", 0) or 0),
            "symbol": str(signal.symbol or "").upper(),
            "selection_id": getattr(signal, "candidate_selection_id", None),
            "candidate_id": getattr(signal, "candidate_id", None),
            "waiting_id": getattr(signal, "waiting_id", None),
            "strategy_id": getattr(signal, "strategy_id", None),
            "lifecycle_kind": getattr(signal, "lifecycle_kind", None) or "INITIAL",
            "signal_id": getattr(signal, "signal_id", None),
        }

    def _trace_executor_received(
        self, signal: RealtimeSignal, uba_id: int | None
    ) -> None:
        tid = getattr(signal, "execution_trace_id", None)
        if not tid or not uba_id:
            return
        try:
            from stock_platform.operation.upbit_entry_execution_trace.constants import (
                DECISION_PASS,
                STAGE_EXECUTOR_RECEIVED,
            )
            from stock_platform.operation.upbit_entry_execution_trace.service import (
                append_stage_fail_open,
            )

            append_stage_fail_open(
                self._session,
                **self._trace_base(signal, uba_id),
                stage=STAGE_EXECUTOR_RECEIVED,
                decision=DECISION_PASS,
            )
        except Exception:  # noqa: BLE001
            pass

    def _trace_executor_rejected(
        self, signal: RealtimeSignal, reason_code: str | None
    ) -> None:
        tid = getattr(signal, "execution_trace_id", None)
        if not tid:
            return
        try:
            from stock_platform.operation.upbit_entry_execution_trace.constants import (
                DECISION_REJECT,
                STAGE_EXECUTOR_REJECTED,
            )
            from stock_platform.operation.upbit_entry_execution_trace.service import (
                append_stage_fail_open,
            )

            append_stage_fail_open(
                self._session,
                **self._trace_base(signal, None),
                stage=STAGE_EXECUTOR_REJECTED,
                decision=DECISION_REJECT,
                reason_code=str(reason_code or "EXECUTOR_REJECTED"),
            )
        except Exception:  # noqa: BLE001
            pass

    def _trace_order_intent(
        self, signal: RealtimeSignal, uba_id: int | None
    ) -> None:
        tid = getattr(signal, "execution_trace_id", None)
        if not tid:
            return
        try:
            from stock_platform.operation.upbit_entry_execution_trace.constants import (
                DECISION_PASS,
                STAGE_ORDER_INTENT_CREATED,
            )
            from stock_platform.operation.upbit_entry_execution_trace.service import (
                append_stage_fail_open,
            )

            append_stage_fail_open(
                self._session,
                **self._trace_base(signal, uba_id),
                stage=STAGE_ORDER_INTENT_CREATED,
                decision=DECISION_PASS,
            )
        except Exception:  # noqa: BLE001
            pass

    def _trace_order_persisted(
        self,
        signal: RealtimeSignal,
        uba_id: int | None,
        *,
        order_id: int,
        outbox_id: int | None,
    ) -> None:
        tid = getattr(signal, "execution_trace_id", None)
        if not tid:
            return
        try:
            from stock_platform.operation.upbit_entry_execution_trace.constants import (
                DECISION_PASS,
                STAGE_ORDER_PERSISTED,
                STAGE_OUTBOX_ENQUEUED,
            )
            from stock_platform.operation.upbit_entry_execution_trace.service import (
                append_stage_fail_open,
            )

            base = self._trace_base(signal, uba_id)
            append_stage_fail_open(
                self._session,
                **base,
                stage=STAGE_ORDER_PERSISTED,
                decision=DECISION_PASS,
                order_id=int(order_id),
            )
            if outbox_id is not None:
                append_stage_fail_open(
                    self._session,
                    **base,
                    stage=STAGE_OUTBOX_ENQUEUED,
                    decision=DECISION_PASS,
                    order_id=int(order_id),
                    outbox_id=int(outbox_id),
                )
        except Exception:  # noqa: BLE001
            pass

    def _skipped(
        self,
        signal: RealtimeSignal,
        reason_code: str,
    ) -> RealtimeExecutionResult:
        self._trace_executor_rejected(signal, reason_code)
        # begin_entry 이후 주문 미생성 terminal reject → ENTRY_PENDING 즉시 복귀
        self._maybe_rollback_orderless_entry_pending(signal, reason_code)
        try:
            from stock_platform.operation.upbit_entry_execution_trace.context import (
                clear_current,
            )

            clear_current()
        except Exception:  # noqa: BLE001
            pass
        executor = RealtimePaperOrderExecutor.__new__(
            RealtimePaperOrderExecutor
        )
        executor._config = self._execution_config

        return executor._skipped(
            signal=signal,
            reason_code=reason_code,
        )

    def _maybe_rollback_orderless_entry_pending(
        self,
        signal: RealtimeSignal,
        reason_code: str,
    ) -> None:
        """UPBIT LIVE BUY: 주문 없는 terminal reject 시 ENTRY_PENDING rollback."""
        try:
            if str(getattr(signal.action, "value", signal.action) or "").upper() != "BUY":
                return
            uba_id = resolve_signal_user_broker_account_id(signal)
            if uba_id is None:
                uba_id = getattr(
                    self._execution_config, "user_broker_account_id", None
                )
            if uba_id is None:
                return
            broker_code = resolve_signal_broker_code(signal) or getattr(
                self._execution_config, "broker_code", None
            )
            if str(broker_code or "").upper() != "UPBIT":
                return
            environment = resolve_execution_environment(
                self._execution_config, signal
            )
            if environment != "LIVE":
                return

            from stock_platform.operation.upbit_full_market.portfolio_service import (
                UpbitPortfolioService,
            )

            sel_id = getattr(signal, "candidate_selection_id", None)
            UpbitPortfolioService(
                self._session
            ).rollback_entry_pending_after_terminal_reject(
                int(uba_id),
                symbol=str(getattr(signal, "symbol", "") or ""),
                reason_code=str(reason_code or "EXECUTOR_REJECTED"),
                actor="risk_integrated_order_executor",
                signal_id=getattr(signal, "signal_id", None),
                selection_id=int(sel_id) if sel_id is not None else None,
                execution_trace_id=getattr(
                    signal, "execution_trace_id", None
                ),
            )
        except Exception:  # noqa: BLE001
            # rollback 실패가 skip 경로를 막지 않음
            pass
