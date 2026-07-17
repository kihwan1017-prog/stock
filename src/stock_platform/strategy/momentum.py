from decimal import Decimal
from .base import StrategyContext, StrategySignal
class MomentumStrategy:
    name="momentum"
    def evaluate(self, context:StrategyContext)->StrategySignal:
        if context.moving_average_5 is None or context.moving_average_20 is None:
            return StrategySignal("HOLD",Decimal("0"),"insufficient indicators")
        if context.moving_average_5>context.moving_average_20:
            return StrategySignal("BUY",Decimal("0.7"),"MA5 above MA20")
        if context.moving_average_5<context.moving_average_20:
            return StrategySignal("SELL",Decimal("0.7"),"MA5 below MA20")
        return StrategySignal("HOLD",Decimal("0"),"moving averages equal")
