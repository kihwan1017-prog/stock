from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
@dataclass(frozen=True, slots=True)
class StrategyContext:
    market:str; symbol:str; last_price:Decimal
    moving_average_5:Decimal|None=None
    moving_average_20:Decimal|None=None
    rsi_14:Decimal|None=None
@dataclass(frozen=True, slots=True)
class StrategySignal:
    action:str; score:Decimal; reason:str
class Strategy(Protocol):
    name:str
    def evaluate(self, context:StrategyContext)->StrategySignal: ...
