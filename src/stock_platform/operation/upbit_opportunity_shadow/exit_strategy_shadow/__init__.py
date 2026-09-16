"""UPBIT Exit Strategy Shadow V1 — research observation only."""

from __future__ import annotations

from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
    RULE_VERSION,
    variant_grid,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.hooks import (
    enroll_binding_on_open,
    finalize_binding_on_close,
)

__all__ = [
    "RULE_VERSION",
    "variant_grid",
    "enroll_binding_on_open",
    "finalize_binding_on_close",
]
