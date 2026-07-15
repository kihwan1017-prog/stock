from datetime import time
from decimal import Decimal

from stock_platform.risk_engine.engine import (
    RealtimeRiskEngine,
)
from stock_platform.risk_engine.models import RiskPolicy


realtime_risk_engine = RealtimeRiskEngine()

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
