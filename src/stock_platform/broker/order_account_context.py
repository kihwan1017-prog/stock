"""STEP8-1 — BrokerOrderRequest 계좌 격리 헬퍼."""

from __future__ import annotations

from stock_platform.broker.models import BrokerOrderRequest
from stock_platform.trading.account_models import UserBrokerAccount


def system_shared_credential_ref(broker_code: str) -> str:
    return f"SYSTEM_SHARED:{(broker_code or '').strip().upper()}"


def user_broker_credential_ref(user_broker_account_id: int) -> str:
    return f"USER_BROKER_ACCOUNT:{int(user_broker_account_id)}"


def attach_user_broker_context(
    request: BrokerOrderRequest,
    *,
    uba: UserBrokerAccount | None,
    broker_code: str,
    account_type: str,
    uses_system_shared_credential: bool,
) -> BrokerOrderRequest:
    """
    Outbox/Adapter 호출 전 UBA 메타를 명시적으로 붙인다.
    환경변수 단일 계좌번호를 사용자 계좌처럼 쓰지 않는다.
    """

    code = (broker_code or request.broker_code or "").strip().upper()
    if uba is None:
        return BrokerOrderRequest(
            client_order_id=request.client_order_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            account_id=request.account_id,
            time_in_force=request.time_in_force,
            user_broker_account_id=None,
            broker_code=code or None,
            account_type=account_type,
            external_account_ref=None,
            credential_ref=(
                system_shared_credential_ref(code)
                if uses_system_shared_credential
                else None
            ),
            owner_user_id=None,
            uses_system_shared_credential=uses_system_shared_credential,
        )

    uba_id = int(uba.user_broker_account_id)
    return BrokerOrderRequest(
        client_order_id=request.client_order_id,
        exchange_code=request.exchange_code,
        symbol=request.symbol,
        side=request.side,
        order_type=request.order_type,
        quantity=request.quantity,
        price=request.price,
        account_id=request.account_id,
        time_in_force=request.time_in_force,
        user_broker_account_id=uba_id,
        broker_code=str(uba.broker_code).upper(),
        account_type=account_type,
        external_account_ref=uba.masked_account_number,
        credential_ref=(
            system_shared_credential_ref(uba.broker_code)
            if uses_system_shared_credential
            else user_broker_credential_ref(uba_id)
        ),
        owner_user_id=int(uba.user_id),
        uses_system_shared_credential=uses_system_shared_credential,
    )


def require_user_broker_context_for_live(
    request: BrokerOrderRequest,
) -> None:
    """
    LIVE 사용자 주문은 UBA 컨텍스트가 있어야 한다.
    공용 환경변수 계좌를 사용자 계좌 대용으로 허용하지 않는다.
    """

    account_type = (request.account_type or "").strip().upper()
    broker = (request.broker_code or "").strip().upper()
    if account_type != "LIVE":
        return
    if broker not in {"KIWOOM", "UPBIT"}:
        return
    if request.user_broker_account_id is None:
        raise PermissionError(
            "LIVE broker order requires user_broker_account_id "
            "(env shared account is not a user account)"
        )
