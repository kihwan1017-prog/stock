"""주문 경로 공통 가드 — Kill Switch / Risk / Live 실거래."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.recovery_lock import raise_if_recovery_paused
from stock_platform.risk_engine.kill_switch_guard import (
    KillSwitchUnavailableError,
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.order_guard import (
    DatabaseBackedRiskOrderGuard,
)


class TradingGuardError(PermissionError):
    """주문/취소 가드 거부."""


def require_kill_switch_allows_order(
    session: Session,
    *,
    side: str,
    allow_sell: bool = True,
    exchange_code: str | None = None,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
) -> None:
    """Kill Switch가 활성면 신규 주문을 거부한다 (SELL 예외 가능).

    DB 조회 실패 시에도 BUY는 차단한다 (fail-closed).
    """

    try:
        PersistentKillSwitchGuard(session).require_order_allowed(
            side=side,
            allow_sell=allow_sell,
            exchange_code=exchange_code,
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
        )
    except KillSwitchUnavailableError as exc:
        raise TradingGuardError(str(exc)) from exc
    except PermissionError as exc:
        raise TradingGuardError(str(exc)) from exc


def require_risk_allows_order(
    session: Session,
    *,
    account_number: str,
    account_id: int,
    exchange_code: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    broker_code: str = "KIWOOM",
    user_id: int | None = None,
    user_broker_account_id: int | None = None,
    order_source: str = "MANUAL",
    is_risk_reducing: bool = False,
    environment: str = "LIVE",
) -> None:
    """Risk 엔진 + 포지션 한도를 통과해야 한다."""

    env = (environment or "LIVE").upper()
    if env == "LIVE" and user_broker_account_id is None:
        raise TradingGuardError(
            "UBA_REQUIRED"
            if not (account_number or "").strip()
            else "LEGACY_ACCOUNT_NUMBER_ONLY"
        )
    if env != "LIVE" and (account_id is None or int(account_id) <= 0):
        raise TradingGuardError("PAPER_ACCOUNT_REQUIRED")

    result = DatabaseBackedRiskOrderGuard(
        session,
        broker_code=broker_code,
    ).check(
        account_number=account_number or "",
        account_id=account_id,
        exchange_code=exchange_code,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        user_id=user_id,
        user_broker_account_id=user_broker_account_id,
        order_source=order_source,
        is_risk_reducing=is_risk_reducing,
        environment=environment,
    )
    if not result.allowed:
        raise TradingGuardError(
            result.blocked_reason or "RISK_ENGINE_BLOCKED"
        )


def require_order_safety(
    session: Session,
    *,
    side: str,
    account_number: str,
    account_id: int,
    exchange_code: str,
    symbol: str,
    quantity: Decimal,
    price: Decimal,
    broker_code: str = "KIWOOM",
    allow_sell: bool = True,
    user_id: int | None = None,
    user_broker_account_id: int | None = None,
    order_source: str = "MANUAL",
    is_risk_reducing: bool = False,
    environment: str = "LIVE",
) -> None:
    """Kill Switch → Recovery pause → Risk 순서로 검사한다."""

    env = (environment or "LIVE").upper()
    if env == "LIVE":
        from stock_platform.operation.live_health_gate import (
            LiveHealthBlockedError,
            assert_live_orders_allowed,
        )

        try:
            assert_live_orders_allowed(session)
        except LiveHealthBlockedError as exc:
            raise TradingGuardError(str(exc)) from exc

    require_kill_switch_allows_order(
        session,
        side=side,
        allow_sell=allow_sell,
        exchange_code=exchange_code,
        user_broker_account_id=user_broker_account_id,
        paper_account_id=(
            account_id if env != "LIVE" else None
        ),
    )
    # Recovery 중 신규 주문 차단 (위험축소 매도는 허용)
    from fastapi import HTTPException

    try:
        if user_broker_account_id is not None:
            raise_if_recovery_paused(
                session,
                user_broker_account_id=user_broker_account_id,
                broker_code=broker_code,
                is_risk_reducing=is_risk_reducing,
            )
        elif account_id:
            raise_if_recovery_paused(
                session,
                paper_account_id=account_id,
                is_risk_reducing=is_risk_reducing,
            )
    except HTTPException as exc:
        raise TradingGuardError(str(exc.detail)) from exc

    require_risk_allows_order(
        session,
        account_number=account_number,
        account_id=account_id,
        exchange_code=exchange_code,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        broker_code=broker_code,
        user_id=user_id,
        user_broker_account_id=user_broker_account_id,
        order_source=order_source,
        is_risk_reducing=is_risk_reducing,
        environment=environment,
    )


def resolve_broker_adapter_for_cancel(
    session: Session,
    *,
    broker_code: str = "KIWOOM",
    environment: str = "PAPER",
):
    """
    취소/정정용 어댑터.
    LIVE는 GLOBAL + 브로커 LIVE + transition 승인 시에만.
    UPBIT PAPER는 mock 어댑터, 그 외 Paper.
    """

    from stock_platform.order.outbox_adapter_resolver import (
        resolve_outbox_adapter,
    )

    return resolve_outbox_adapter(
        {
            "broker_code": broker_code,
            "environment": environment,
        },
        session=session,
    )
