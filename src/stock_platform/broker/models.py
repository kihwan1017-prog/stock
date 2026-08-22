from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class BrokerEnvironment(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class BrokerOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class BrokerOrderStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class BrokerOrderRequest:
    client_order_id: str
    exchange_code: str
    symbol: str
    side: BrokerOrderSide
    order_type: BrokerOrderType
    quantity: Decimal
    price: Decimal | None = None
    account_id: int | None = None
    time_in_force: str = "DAY"
    # STEP8-1 — UserBrokerAccount 단위 격리 컨텍스트
    user_broker_account_id: int | None = None
    broker_code: str | None = None
    # PAPER | LIVE | MOCK (어댑터 라우팅 메타)
    account_type: str | None = None
    # 마스킹된 외부 계좌 식별자 (평문 계좌번호 금지)
    external_account_ref: str | None = None
    # 예: SYSTEM_SHARED:KIWOOM / USER_BROKER_ACCOUNT:12
    credential_ref: str | None = None
    owner_user_id: int | None = None
    # 환경변수 공용 자격증명을 API 인증에 쓰는 경우 True
    uses_system_shared_credential: bool = False
    # STEP 8-5-12 — Upbit identifier (client_order_id와 분리)
    upbit_client_identifier: str | None = None
    # UPBIT MARKET BUY 전용 — 총 매수 KRW (ticker/unit price 와 분리)
    quote_amount_krw: Decimal | None = None
    # 참고가 (사이징/슬리피지 telemetry). broker MARKET BUY price 로 쓰지 않음.
    reference_price: Decimal | None = None



@dataclass(frozen=True, slots=True)
class BrokerOrderResult:
    """기존 OrderDispatcher / Kiwoom sync 어댑터용 결과."""

    accepted: bool
    status: BrokerOrderStatus
    broker_order_id: str | None
    submitted_at: datetime
    reject_code: str | None = None
    reject_message: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerOrderResponse:
    """공통 BrokerOrderAdapter용 주문 응답."""

    broker_order_id: str
    client_order_id: str
    status: BrokerOrderStatus
    accepted_quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    message: str | None
    requested_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BrokerAccountSnapshot:
    """공통 BrokerOrderAdapter용 계좌 스냅샷."""

    account_key: str
    cash_balance: Decimal
    available_cash: Decimal
    total_asset_value: Decimal
    currency_code: str
    fetched_at: datetime
