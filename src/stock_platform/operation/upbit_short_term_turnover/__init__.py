"""Upbit short-term turnover research — shadow / backtest only.

Production execution · LIVE · ARM · WRK-014 policy 변경 금지.
"""

from stock_platform.operation.upbit_short_term_turnover.metrics import (
    apply_round_trip_costs,
    max_drawdown,
    profit_factor,
    trades_per_day_stats,
)
from stock_platform.operation.upbit_short_term_turnover.profiles import (
    PROFILE_SPECS,
    ResearchProfile,
)
from stock_platform.operation.upbit_short_term_turnover.slot_shadow import (
    SlotCountMode,
    count_entry_slots,
    simulate_auto_only_admission,
)

__all__ = [
    "PROFILE_SPECS",
    "ResearchProfile",
    "SlotCountMode",
    "apply_round_trip_costs",
    "count_entry_slots",
    "max_drawdown",
    "profit_factor",
    "simulate_auto_only_admission",
    "trades_per_day_stats",
]
