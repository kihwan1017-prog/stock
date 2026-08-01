from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

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


def resolve_signal_broker_code(signal: RealtimeSignal) -> str:
    """Scope/신호의 broker_code 우선, 없으면 거래소 휴리스틱."""

    raw = getattr(signal, "broker_code", None)
    if raw:
        return str(raw).strip().upper()

    exchange = str(signal.exchange_code or "").strip().upper()
    if exchange in {"UPBIT", "CRYPTO", "BINANCE"}:
        return "UPBIT"
    return "KIWOOM"


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

        quantity = (
            self._execution_config.order_amount
            / signal.signal_price
        ).quantize(Decimal("0.00000001"))

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
                # MOCK/LIVE 자동매매: SELL 신호 시 전량 청산
                quantity = Decimal(str(held))

        # MOCK/LIVE SELL: 원장 전량 캡 — Paper Risk 보유검사 스킵
        if (
            environment in {"MOCK", "LIVE"}
            and signal.action.value.upper() == "SELL"
        ):
            risk_allowed = True
            risk_blocked = None
        else:
            risk_result = DatabaseBackedRiskOrderGuard(
                self._session,
                broker_code=broker_code,
            ).check(
                account_number=account_number or f"PAPER-{exec_account_id}",
                account_id=exec_account_id,
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
            order_amount=self._execution_config.order_amount,
            open_position_count=int(open_position_count),
            live_unlock_token=unlock_token,
        )
        if not decision.allowed:
            return self._skipped(
                signal,
                decision.reason_code,
            )

        from stock_platform.order.live_shadow import is_live_shadow_mode

        meta = {
            "source": "REALTIME_SIGNAL",
            "signal_reason": signal.reason_code,
            "execution_mode": self._execution_config.mode.value,
            "environment": environment,
            "resolved_broker_code": broker_code,
        }
        if environment == "LIVE" and is_live_shadow_mode():
            meta["shadow"] = True
            meta["shadow_mode"] = "LIVE_SHADOW"

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
                strategy_code=signal.reason_code,
                account_number=account_number or None,
                skip_risk_checks=True,  # 이미 상단에서 검증
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
                idempotency_key=(
                    f"RT:{signal.exchange_code}:"
                    f"{signal.symbol}:"
                    f"{signal.action.value}:"
                    f"{signal.generated_at.isoformat()}"
                ),
            )
        )

        if not result.allowed:
            return self._skipped(
                signal,
                result.reason_code,
            )

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

    def _skipped(
        self,
        signal: RealtimeSignal,
        reason_code: str,
    ) -> RealtimeExecutionResult:
        executor = RealtimePaperOrderExecutor.__new__(
            RealtimePaperOrderExecutor
        )
        executor._config = self._execution_config

        return executor._skipped(
            signal=signal,
            reason_code=reason_code,
        )
