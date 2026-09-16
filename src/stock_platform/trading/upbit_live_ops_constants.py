"""STEP 8-9C — Upbit LIVE 준비용 권장 Risk / 상수."""

from __future__ import annotations

from decimal import Decimal

# Admin이 UPBIT UBA 생성·Risk 5000 시 계좌 오버레이.
# Risk Engine(ResolvedRiskPolicy)이 실제로 평가하는 필드와 일치시킨다.
UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT = Decimal("5000")
UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS = 1
UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT = 1
# 소액 스모크: 기존 보유·당일 손익에 막히지 않도록 Engine 사용 필드도 함께 설정
UPBIT_LIVE_RECOMMENDED_MAX_INVESTMENT_RATIO = Decimal("1.0")
UPBIT_LIVE_RECOMMENDED_DAILY_MAX_LOSS_AMOUNT = Decimal("10000000")
UPBIT_LIVE_RECOMMENDED_MAX_POSITION_AMOUNT = Decimal("10000000")
UPBIT_LIVE_RECOMMENDED_MAX_POSITION_WEIGHT = Decimal("1.0")
UPBIT_LIVE_RECOMMENDED_MAX_TOTAL_INVESTMENT_AMOUNT = Decimal("10000000")


def upbit_live_recommended_risk_payload() -> dict[str, Decimal | int]:
    return {
        "max_order_amount": UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT,
        "max_open_orders": UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS,
        "daily_order_limit": UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT,
        "max_investment_ratio": UPBIT_LIVE_RECOMMENDED_MAX_INVESTMENT_RATIO,
        "daily_max_loss_amount": UPBIT_LIVE_RECOMMENDED_DAILY_MAX_LOSS_AMOUNT,
        "max_position_amount": UPBIT_LIVE_RECOMMENDED_MAX_POSITION_AMOUNT,
        "max_position_weight": UPBIT_LIVE_RECOMMENDED_MAX_POSITION_WEIGHT,
        "max_total_investment_amount": (
            UPBIT_LIVE_RECOMMENDED_MAX_TOTAL_INVESTMENT_AMOUNT
        ),
    }
