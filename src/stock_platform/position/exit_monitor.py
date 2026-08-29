from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from stock_platform.notification.publisher import (
    NotificationPublisher,
    exit_notification_publisher,
)
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest


logger = structlog.get_logger(__name__)

# 강제 청산 사유 — RiskEngine 가격 평가를 건너뛴다.
FORCE_EXIT_REASONS = frozenset(
    {"KILL_SWITCH", "DAILY_LOSS"}
)


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    account_id: int
    exchange_code: str
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    highest_price: Decimal
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None
    trailing_stop_ratio: Decimal | None = None
    relative_loss_ratio: Decimal | None = None
    broker_code: str = "KIWOOM"
    # 설정 시 RiskEngine 대신 이 사유로 즉시 청산
    force_exit_reason: str | None = None
    user_broker_account_id: int | None = None
    owner_user_id: int | None = None
    environment: str = "PAPER"
    snapshot_synchronized_at: datetime | None = None
    # LIVE strategy-owned OPEN binding (없으면 LIVE exit 평가 skip)
    binding_id: int | None = None


@dataclass(frozen=True, slots=True)
class PositionExitAction:
    symbol: str
    reason: str
    trigger_price: Decimal | None
    order_id: int | None
    submitted: bool


class PositionExitMonitorService:
    """손절/익절/트레일링/상대손실·강제청산 조건을 평가해 청산 주문을 제출한다."""

    def __init__(
        self,
        session: Session,
        *,
        notification_publisher: NotificationPublisher
        | None = None,
    ) -> None:
        self._session = session
        self._risk_engine = RiskManagementEngine()
        self._execution = OrderExecutionService(session)
        self._publisher_impl = (
            notification_publisher
            or exit_notification_publisher
        )

    def evaluate_and_exit(
        self,
        positions: list[ManagedPosition],
        *,
        skip_risk_checks: bool = False,
    ) -> list[PositionExitAction]:
        logger.debug(
            "position_exit_scan_begin",
            position_count=len(positions),
        )
        actions: list[PositionExitAction] = []
        for position in positions:
            action = self._evaluate_one(
                position,
                skip_risk_checks=skip_risk_checks,
            )
            actions.append(action)
        logger.debug(
            "position_exit_scan_complete",
            position_count=len(positions),
            exit_submitted=sum(
                1 for item in actions if item.submitted
            ),
        )
        return actions

    def _evaluate_one(
        self,
        position: ManagedPosition,
        *,
        skip_risk_checks: bool,
    ) -> PositionExitAction:
        logger.debug(
            "position_exit_inspect",
            account_id=position.account_id,
            exchange_code=position.exchange_code,
            symbol=position.symbol,
            current_price=str(position.current_price),
            force_exit_reason=position.force_exit_reason,
        )

        reason: str
        trigger_price: Decimal | None

        if (
            position.force_exit_reason
            and position.force_exit_reason
            in FORCE_EXIT_REASONS
        ):
            reason = position.force_exit_reason
            trigger_price = position.current_price
            should_exit = True
        else:
            decision = self._risk_engine.evaluate_exit(
                ExitEvaluationRequest(
                    entry_price=position.entry_price,
                    current_price=position.current_price,
                    highest_price=position.highest_price,
                    stop_loss_price=position.stop_loss_price,
                    take_profit_price=(
                        position.take_profit_price
                    ),
                    trailing_stop_ratio=(
                        position.trailing_stop_ratio
                    ),
                    relative_loss_ratio=(
                        position.relative_loss_ratio
                    ),
                )
            )
            reason = decision.reason
            trigger_price = decision.trigger_price
            should_exit = decision.should_exit

        env_u = str(position.environment or "PAPER").upper()
        if not should_exit:
            # LIVE: 조건 해제 시 trigger cycle 리셋 (새 edge만 허용)
            if env_u == "LIVE" and position.user_broker_account_id:
                self._clear_live_trigger_cycle_if_needed(position)
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        logger.info(
            "position_exit_condition_found",
            symbol=position.symbol,
            reason=reason,
            trigger_price=(
                str(trigger_price)
                if trigger_price is not None
                else None
            ),
            environment=env_u,
            user_broker_account_id=position.user_broker_account_id,
            binding_id=position.binding_id,
        )

        if env_u == "LIVE":
            return self._submit_live_exit(
                position,
                reason=reason,
                trigger_price=trigger_price,
                skip_risk_checks=skip_risk_checks,
            )

        try:
            # Paper 계좌 소유자 → ResolvedRiskPolicy
            from stock_platform.trading.account_models import (
                PaperAccount,
            )

            paper = self._session.get(
                PaperAccount, position.account_id
            )
            owner_user_id = (
                int(paper.user_id)
                if paper is not None and paper.user_id is not None
                else None
            )
            result = self._execution.submit(
                OrderExecutionCommand(
                    account_id=position.account_id,
                    broker_code=position.broker_code,
                    exchange_code=position.exchange_code,
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=position.quantity,
                    price=position.current_price,
                    skip_risk_checks=skip_risk_checks,
                    metadata_payload={
                        "source": "POSITION_EXIT_MONITOR",
                        "exit_reason": reason,
                    },
                    actor="POSITION_EXIT_MONITOR",
                    order_source="EXIT",
                    is_risk_reducing=True,
                    user_id=owner_user_id,
                    account_number=(
                        f"PAPER-{position.account_id}"
                    ),
                    idempotency_key=(
                        f"EXIT:{position.exchange_code}:"
                        f"{position.symbol}:{reason}:"
                        f"{position.quantity}"
                    ),
                )
            )
        except Exception as exc:
            logger.exception(
                "position_exit_order_failed",
                symbol=position.symbol,
                reason=reason,
                error=str(exc),
            )
            self._publish_exit_event(
                reason=reason,
                position=position,
                trigger_price=trigger_price,
                submitted=False,
                order_id=None,
                error=str(exc),
            )
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        if result.allowed:
            logger.info(
                "position_exit_order_created",
                symbol=position.symbol,
                reason=reason,
                order_id=result.order_id,
            )
        else:
            logger.warning(
                "position_exit_order_failed",
                symbol=position.symbol,
                reason=reason,
                blocked_reason=result.reason_code,
            )

        self._publish_exit_event(
            reason=reason,
            position=position,
            trigger_price=trigger_price,
            submitted=result.allowed,
            order_id=result.order_id,
            error=(
                None
                if result.allowed
                else result.reason_code
            ),
        )

        return PositionExitAction(
            symbol=position.symbol,
            reason=reason,
            trigger_price=trigger_price,
            order_id=result.order_id,
            submitted=result.allowed,
        )

    def _submit_live_exit(
        self,
        position: ManagedPosition,
        *,
        reason: str,
        trigger_price: Decimal | None,
        skip_risk_checks: bool,
    ) -> PositionExitAction:
        """LIVE EXIT (UPBIT/KIWOOM) — OES만 사용. adapter 직접 호출 금지.

        Telegram/event: submit 성공 시에만 1회 (tick spam 금지).
        """

        uba_id = position.user_broker_account_id
        if uba_id is None:
            # UBA 없으면 주문 불가 — alert spam 금지
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        from stock_platform.position.exit_monitor_live import (
            SOURCE_EXIT_MONITOR,
            STATE_EXIT_ORDER_PENDING,
            STATE_EXIT_SUBMITTED,
            STATE_TRAILING_TRIGGERED,
            already_notified_exit_submit,
            exit_cycle_key,
            has_blocking_live_exit_sell,
            load_broker_position_snapshot,
            load_open_strategy_binding,
            persist_exit_lifecycle,
            read_exit_lifecycle,
        )
        from stock_platform.position.smoke_exit_isolation import (
            SUPPRESS_EVENT,
            is_exit_submission_suppressed_for_smoke,
        )

        broker = str(position.broker_code or "UPBIT").upper()
        # OPEN binding gate — closed/MA-exited 포지션 trailing 재평가 금지
        open_binding = load_open_strategy_binding(
            self._session,
            user_broker_account_id=int(uba_id),
            symbol=position.symbol,
            broker_code=broker,
        )
        binding_id = (
            int(open_binding.binding_id)
            if open_binding is not None
            and getattr(open_binding, "binding_id", None) is not None
            else position.binding_id
        )
        if open_binding is None:
            logger.info(
                "position_exit_skipped_no_open_binding",
                symbol=position.symbol,
                user_broker_account_id=int(uba_id),
                reason=reason,
            )
            return PositionExitAction(
                symbol=position.symbol,
                reason="TRAILING_EVALUATION_SKIPPED",
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        snap = None
        if broker == "UPBIT":
            snap = load_broker_position_snapshot(
                self._session,
                user_broker_account_id=int(uba_id),
                symbol=position.symbol,
            )
        lifecycle = (
            read_exit_lifecycle(getattr(snap, "raw_data", None))
            if snap is not None
            else {}
        )
        cycle = exit_cycle_key(
            uba_id=int(uba_id),
            binding_id=binding_id,
            reason=reason,
        )

        suppress_lease = is_exit_submission_suppressed_for_smoke(
            user_broker_account_id=int(uba_id),
            symbol=position.symbol,
        )
        if suppress_lease is not None:
            logger.info(
                SUPPRESS_EVENT,
                symbol=position.symbol,
                reason=reason,
                trigger_price=(
                    str(trigger_price) if trigger_price is not None else None
                ),
                user_broker_account_id=int(uba_id),
                lease_id=suppress_lease.lease_id,
                isolation_reason=suppress_lease.reason,
                correlation_id=suppress_lease.correlation_id,
            )
            try:
                from stock_platform.order.live_safety_audit import (
                    emit_live_safety_audit,
                )

                emit_live_safety_audit(
                    self._session,
                    event_type=SUPPRESS_EVENT,
                    actor="POSITION_EXIT_MONITOR",
                    run_id=suppress_lease.lease_id,
                    user_id=position.owner_user_id,
                    account_id=int(uba_id),
                    strategy_id=None,
                    symbol=position.symbol,
                    detail={
                        "exit_reason": reason,
                        "trigger_price": (
                            str(trigger_price)
                            if trigger_price is not None
                            else None
                        ),
                        "lease": suppress_lease.as_dict(),
                        "order_submitted": False,
                    },
                    commit=False,
                )
            except Exception:  # noqa: BLE001 — audit 실패가 exit 억제를 막지 않음
                logger.exception(
                    "smoke_exit_isolation_audit_failed",
                    user_broker_account_id=int(uba_id),
                    symbol=position.symbol,
                )
            # smoke suppress: Telegram 0 (이전 tick spam 경로 제거)
            if snap is not None:
                from datetime import datetime, timezone

                life = dict(lifecycle)
                life.update(
                    {
                        "state": STATE_EXIT_ORDER_PENDING,
                        "reason": reason,
                        "binding_id": binding_id,
                        "trigger_price": (
                            str(trigger_price)
                            if trigger_price is not None
                            else None
                        ),
                        "triggered_at": life.get("triggered_at")
                        or datetime.now(timezone.utc).isoformat(),
                        "cycle_key": cycle,
                        "suppress": SUPPRESS_EVENT,
                        "peak_price": str(position.highest_price),
                    }
                )
                persist_exit_lifecycle(snap, life)
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        if has_blocking_live_exit_sell(
            self._session,
            user_broker_account_id=int(uba_id),
            symbol=position.symbol,
            snapshot_synchronized_at=position.snapshot_synchronized_at,
        ):
            logger.info(
                "position_exit_skipped_pending_sell",
                symbol=position.symbol,
                user_broker_account_id=int(uba_id),
                reason=reason,
            )
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        # edge: 동일 cycle 이미 submit 성공 알림 보냈으면 재발행 금지
        if (
            str(lifecycle.get("state") or "") == STATE_EXIT_SUBMITTED
            and str(lifecycle.get("cycle_key") or "") == cycle
            and already_notified_exit_submit(lifecycle)
        ):
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=(
                    int(lifecycle["exit_order_id"])
                    if lifecycle.get("exit_order_id") is not None
                    else None
                ),
                submitted=True,
            )

        # first edge → TRAILING_TRIGGERED (아직 Telegram 없음)
        if snap is not None and str(lifecycle.get("cycle_key") or "") != cycle:
            from datetime import datetime, timezone

            life = dict(lifecycle)
            life.update(
                {
                    "state": STATE_TRAILING_TRIGGERED,
                    "reason": reason,
                    "binding_id": binding_id,
                    "entry_price": str(position.entry_price),
                    "peak_price": str(position.highest_price),
                    "peak_at": life.get("peak_at"),
                    "trailing_armed_at": life.get("trailing_armed_at"),
                    "trigger_price": (
                        str(trigger_price)
                        if trigger_price is not None
                        else None
                    ),
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                    "cycle_key": cycle,
                    "telegram_submitted_sent": False,
                    "exit_rule_version": "exit_reliability_v1",
                }
            )
            persist_exit_lifecycle(snap, life)
            lifecycle = life

        try:
            exchange = str(
                position.exchange_code
                or ("KRX" if broker == "KIWOOM" else "UPBIT")
            ).upper()
            strategy_id: int | None = None
            if open_binding is not None and open_binding.strategy_id is not None:
                strategy_id = int(open_binding.strategy_id)
            exit_meta: dict = {
                "source": SOURCE_EXIT_MONITOR,
                "exit_reason": reason,
                "exit_cycle_key": cycle,
            }
            if binding_id is not None:
                exit_meta["binding_id"] = int(binding_id)
            if strategy_id is not None:
                exit_meta["strategy_id"] = strategy_id
            # peak provenance for Telegram/Trace
            if lifecycle.get("peak_price"):
                exit_meta["peak_price"] = lifecycle.get("peak_price")
            else:
                exit_meta["peak_price"] = str(position.highest_price)
            if trigger_price is not None:
                exit_meta["trigger_price"] = str(trigger_price)
            result = self._execution.submit(
                OrderExecutionCommand(
                    account_id=None,
                    broker_code=broker,
                    exchange_code=exchange,
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=position.quantity,
                    price=position.current_price,
                    skip_risk_checks=skip_risk_checks,
                    metadata_payload=exit_meta,
                    actor="POSITION_EXIT_MONITOR",
                    order_source="EXIT",
                    strategy_id=strategy_id,
                    is_risk_reducing=True,
                    user_id=position.owner_user_id,
                    owner_user_id=position.owner_user_id,
                    user_broker_account_id=int(uba_id),
                    environment="LIVE",
                    account_number=f"UBA:{int(uba_id)}",
                    reference_price=position.current_price,
                    idempotency_key=(
                        f"EXIT:LIVE:{int(uba_id)}:"
                        f"{exchange}:"
                        f"{position.symbol}"
                    ),
                )
            )
        except Exception as exc:
            logger.exception(
                "position_exit_order_failed",
                symbol=position.symbol,
                reason=reason,
                error=str(exc),
                user_broker_account_id=int(uba_id),
            )
            if snap is not None:
                life = dict(lifecycle)
                life.update(
                    {
                        "state": STATE_EXIT_ORDER_PENDING,
                        "reason": reason,
                        "cycle_key": cycle,
                        "last_error": str(exc)[:200],
                    }
                )
                persist_exit_lifecycle(snap, life)
            # submit 실패 — Telegram 재발송 금지
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        if result.allowed:
            logger.info(
                "position_exit_order_created",
                symbol=position.symbol,
                reason=reason,
                order_id=result.order_id,
                user_broker_account_id=int(uba_id),
            )
            if snap is not None:
                life = dict(lifecycle)
                life.update(
                    {
                        "state": STATE_EXIT_SUBMITTED,
                        "reason": reason,
                        "cycle_key": cycle,
                        "exit_order_id": result.order_id,
                        "binding_id": binding_id,
                        "telegram_submitted_sent": True,
                    }
                )
                persist_exit_lifecycle(snap, life)
            # Policy A: submit 성공 시에만 1회 알림
            self._publish_exit_event(
                reason=reason,
                position=position,
                trigger_price=trigger_price,
                submitted=True,
                order_id=result.order_id,
                error=None,
                peak_price=str(
                    lifecycle.get("peak_price")
                    or position.highest_price
                ),
                binding_id=binding_id,
                dedupe_key=f"TG:{cycle}:SUBMIT",
            )
        else:
            logger.warning(
                "position_exit_order_failed",
                symbol=position.symbol,
                reason=reason,
                blocked_reason=result.reason_code,
                user_broker_account_id=int(uba_id),
            )
            if snap is not None:
                life = dict(lifecycle)
                life.update(
                    {
                        "state": STATE_EXIT_ORDER_PENDING,
                        "reason": reason,
                        "cycle_key": cycle,
                        "last_block_reason": str(result.reason_code or "")[
                            :120
                        ],
                    }
                )
                persist_exit_lifecycle(snap, life)
            # blocked retry — Telegram 0

        return PositionExitAction(
            symbol=position.symbol,
            reason=reason,
            trigger_price=trigger_price,
            order_id=result.order_id if result.allowed else None,
            submitted=bool(result.allowed),
        )

    def _clear_live_trigger_cycle_if_needed(
        self,
        position: ManagedPosition,
    ) -> None:
        uba_id = position.user_broker_account_id
        if uba_id is None:
            return
        if str(position.broker_code or "").upper() != "UPBIT":
            return
        try:
            from stock_platform.position.exit_monitor_live import (
                clear_exit_trigger_cycle,
                load_broker_position_snapshot,
            )

            snap = load_broker_position_snapshot(
                self._session,
                user_broker_account_id=int(uba_id),
                symbol=position.symbol,
            )
            if snap is not None:
                clear_exit_trigger_cycle(snap)
        except Exception:  # noqa: BLE001
            logger.debug(
                "clear_exit_trigger_cycle_failed",
                symbol=position.symbol,
                exc_info=True,
            )

    def _publish_exit_event(
        self,
        *,
        reason: str,
        position: ManagedPosition,
        trigger_price: Decimal | None,
        submitted: bool,
        order_id: int | None,
        error: str | None,
        peak_price: str | None = None,
        binding_id: int | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        title = f"Position exit: {reason}"
        message = (
            f"{position.exchange_code}/{position.symbol} "
            f"qty={position.quantity} "
            f"submitted={submitted}"
        )
        detail: dict = {
            "account_id": position.account_id,
            "user_broker_account_id": (
                position.user_broker_account_id
            ),
            "environment": str(
                position.environment or "PAPER"
            ).upper(),
            "exchange_code": position.exchange_code,
            "broker_code": position.broker_code,
            "market": (
                "UPBIT"
                if str(position.broker_code or "").upper() == "UPBIT"
                else "KIWOOM"
            ),
            "symbol": position.symbol,
            "symbol_display": position.symbol,
            "quantity": str(position.quantity),
            "entry_price": str(position.entry_price),
            "current_price": str(
                position.current_price
            ),
            "avg_price": str(position.current_price),
            "trigger_price": (
                str(trigger_price)
                if trigger_price is not None
                else None
            ),
            "peak_price": peak_price
            or str(position.highest_price),
            "binding_id": binding_id or position.binding_id,
            "order_id": order_id,
            "submitted": submitted,
            "error": error,
            "status_label": (
                "매도 주문 제출 완료"
                if submitted
                else "제출 실패/차단"
            ),
        }
        if dedupe_key:
            detail["dedupe_key"] = dedupe_key
        self._publisher.publish(
            event_type=reason,
            title=title,
            message=message,
            detail=detail,
        )

    @property
    def _publisher(self) -> NotificationPublisher:
        # __new__ 기반 단위 테스트 호환
        publisher = getattr(self, "_publisher_impl", None)
        if publisher is None:
            return exit_notification_publisher
        return publisher

    @_publisher.setter
    def _publisher(
        self,
        value: NotificationPublisher,
    ) -> None:
        self._publisher_impl = value
