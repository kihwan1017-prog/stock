from datetime import time
from decimal import Decimal

from stock_platform.risk_engine.engine import (
    RealtimeRiskEngine,
)
from stock_platform.risk_engine.models import RiskPolicy


realtime_risk_engine = RealtimeRiskEngine()

# 주문 경로 강제 정책 (보수적 기본값).
# Admin setting_catalog `risk_max_order_amount` 기본도 동일(100000)로 맞춤.
# DB 설정 오버레이는 후속(운영 검증 후) — 현재는 코드 정책이 단일 소스.
realtime_risk_policy = RiskPolicy(
    max_order_amount=Decimal("100000"),
    max_order_quantity=Decimal("1000000"),
    max_open_positions=5,
    max_investment_ratio=Decimal("0.70"),
    max_daily_loss=Decimal("300000"),
    trading_start_time=time(9, 0),
    trading_end_time=time(15, 20),
    enforce_krx_market_hours=True,
    emergency_stop_enabled=False,
    allow_sell_during_emergency_stop=True,
)
