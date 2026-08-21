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
    stop_loss_price: Decimal
    take_profit_price: Decimal
    trailing_stop_ratio: Decimal | None = None
    relative_loss_ratio: Decimal | None = None
    broker_code: str = "KIWOOM"
    # 설정 시 RiskEngine 대신 이 사유로 즉시 청산
    force_exit_reason: str | None = None
    user_broker_account_id: int | None = None
    owner_user_id: int | None = None
    environment: str = "PAPER"
    snapshot_synchronized_at: datetime | None = None


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

        if not should_exit:
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
            environment=str(position.environment or "PAPER").upper(),
            user_broker_account_id=position.user_broker_account_id,
        )

        env_u = str(position.environment or "PAPER").upper()
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
        """LIVE EXIT (UPBIT/KIWOOM) — OES만 사용. adapter 직접 호출 금지."""

        uba_id = position.user_broker_account_id
        if uba_id is None:
            self._publish_exit_event(
                reason=reason,
                position=position,
                trigger_price=trigger_price,
                submitted=False,
                order_id=None,
                error="UBA_REQUIRED",
            )
            return PositionExitAction(
                symbol=position.symbol,
                reason=reason,
                trigger_price=trigger_price,
                order_id=None,
                submitted=False,
            )

        from stock_platform.position.exit_monitor_live import (
            SOURCE_EXIT_MONITOR,
            has_blocking_live_exit_sell,
        )
        from stock_platform.position.smoke_exit_isolation import (
            SUPPRESS_EVENT,
            is_exit_submission_suppressed_for_smoke,
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
            self._publish_exit_event(
                reason=reason,
                position=position,
                trigger_price=trigger_price,
                submitted=False,
                order_id=None,
                error=SUPPRESS_EVENT,
            )
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

        try:
            broker = str(position.broker_code or "UPBIT").upper()
            exchange = str(
                position.exchange_code
                or ("KRX" if broker == "KIWOOM" else "UPBIT")
            ).upper()
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
                    metadata_payload={
                        "source": SOURCE_EXIT_MONITOR,
                        "exit_reason": reason,
                    },
                    actor="POSITION_EXIT_MONITOR",
                    order_source="EXIT",
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
                user_broker_account_id=int(uba_id),
            )
        else:
            logger.warning(
                "position_exit_order_failed",
                symbol=position.symbol,
                reason=reason,
                blocked_reason=result.reason_code,
                user_broker_account_id=int(uba_id),
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

    def _publish_exit_event(
        self,
        *,
        reason: str,
        position: ManagedPosition,
        trigger_price: Decimal | None,
        submitted: bool,
        order_id: int | None,
        error: str | None,
    ) -> None:
        title = f"Position exit: {reason}"
        message = (
            f"{position.exchange_code}/{position.symbol} "
            f"qty={position.quantity} "
            f"submitted={submitted}"
        )
        self._publisher.publish(
            event_type=reason,
            title=title,
            message=message,
            detail={
                "account_id": position.account_id,
                "user_broker_account_id": (
                    position.user_broker_account_id
                ),
                "environment": str(
                    position.environment or "PAPER"
                ).upper(),
                "exchange_code": position.exchange_code,
                "symbol": position.symbol,
                "quantity": str(position.quantity),
                "entry_price": str(position.entry_price),
                "current_price": str(
                    position.current_price
                ),
                "trigger_price": (
                    str(trigger_price)
                    if trigger_price is not None
                    else None
                ),
                "order_id": order_id,
                "submitted": submitted,
                "error": error,
            },
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
