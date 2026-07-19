"""주문 경로 공통 가드 — Kill Switch / Risk / Live 실거래."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.common.settings import get_settings
from stock_platform.risk_engine.kill_switch_guard import (
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
) -> None:
    """Kill Switch가 활성면 신규 주문을 거부한다 (SELL 예외 가능)."""

    try:
        PersistentKillSwitchGuard(session).require_order_allowed(
            side=side,
            allow_sell=allow_sell,
        )
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
) -> None:
    """Risk 엔진 + 포지션 한도를 통과해야 한다."""

    if not account_number.strip():
        raise TradingGuardError(
            "account_number is required for risk checks"
        )

    result = DatabaseBackedRiskOrderGuard(
        session,
        broker_code=broker_code,
    ).check(
        account_number=account_number,
        account_id=account_id,
        exchange_code=exchange_code,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
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
) -> None:
    """Kill Switch → Risk 순서로 검사한다."""

    require_kill_switch_allows_order(
        session,
        side=side,
        allow_sell=allow_sell,
    )
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
    )


def resolve_broker_adapter_for_cancel(session: Session):
    """
    취소/정정용 어댑터.
    실거래는 KIWOOM_LIVE_ORDER_ENABLED + live transition 승인 시에만.
    그 외는 Paper 어댑터.
    """

    settings = get_settings()
    if settings.kiwoom_live_order_enabled:
        try:
            return BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "KIWOOM",
                session=session,
            )
        except PermissionError as exc:
            raise TradingGuardError(str(exc)) from exc
    return PaperBrokerAdapter()
