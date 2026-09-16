"""Frozen WRK-016 Momentum eligibility (no threshold retune)."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_momentum_validation.constants import (
    FROZEN_MOMENTUM,
)
from stock_platform.operation.upbit_positive_edge_entry.families import (
    evaluate_families,
)
from stock_platform.operation.upbit_positive_edge_entry.regime import (
    MarketRegime,
)


def momentum_hit(feat: dict[str, Any], *, regime: MarketRegime | str) -> tuple[bool, float]:
    """WRK-016 evaluate_families → MOMENTUM only. Threshold 재튜닝 금지."""

    hits = evaluate_families(feat, regime=regime)
    for h in hits:
        if h.family == "MOMENTUM":
            return True, float(h.score)
    return False, 0.0


def frozen_rule_dict() -> dict[str, Any]:
    return dict(FROZEN_MOMENTUM)
