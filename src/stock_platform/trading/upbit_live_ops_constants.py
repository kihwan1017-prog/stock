"""STEP 8-9C — Upbit LIVE 준비용 권장 Risk / 상수."""

from __future__ import annotations

from decimal import Decimal

# Admin이 UPBIT UBA 생성 시 계좌 Risk 오버레이 기본값
# (시스템 전역 기본값을 바꾸지 않고 계좌 단위만 적용)
UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT = Decimal("5000")
UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS = 1
UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT = 1


def upbit_live_recommended_risk_payload() -> dict[str, Decimal | int]:
    return {
        "max_order_amount": UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT,
        "max_open_orders": UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS,
        "daily_order_limit": UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT,
    }
