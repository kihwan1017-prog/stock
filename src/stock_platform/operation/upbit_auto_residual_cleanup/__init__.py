# -*- coding: utf-8 -*-
"""CONTROLLED_AUTO_RESIDUAL_CLEANUP — explicit residual cleanup (PREVIEW/DRY-RUN)."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    ARCHITECTURE,
    CLEANUP_PATH,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    ResidualCleanupContext,
    evaluate_eligibility,
)
from stock_platform.operation.upbit_auto_residual_cleanup.lifecycle import (
    apply_verified_fill_to_residual,
)
from stock_platform.operation.upbit_auto_residual_cleanup.quantity import (
    provenance_current_qty,
    resolve_cleanup_sell_quantity,
)
from stock_platform.operation.upbit_auto_residual_cleanup.service import (
    ProductionBrokerSubmitDisabled,
    apply_cleanup,
    assert_architecture_invariants,
    prepare_cleanup,
    preview_cleanup,
)


def preview_residual_cleanup(*args: Any, **kwargs: Any):
    return preview_cleanup(*args, **kwargs)


__all__ = [
    "ARCHITECTURE",
    "CLEANUP_PATH",
    "ProductionBrokerSubmitDisabled",
    "ResidualCleanupContext",
    "apply_cleanup",
    "apply_verified_fill_to_residual",
    "assert_architecture_invariants",
    "evaluate_eligibility",
    "prepare_cleanup",
    "preview_cleanup",
    "preview_residual_cleanup",
    "provenance_current_qty",
    "resolve_cleanup_sell_quantity",
]
