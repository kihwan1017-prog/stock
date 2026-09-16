# -*- coding: utf-8 -*-
"""CONTROLLED_AUTO_RESIDUAL_CLEANUP — explicit residual cleanup (PREVIEW/APPLY)."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_auto_residual_cleanup.approval import (
    ApprovalError,
    CleanupApproval,
    issue_cleanup_approval,
    preview_result_hash,
)
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
from stock_platform.operation.upbit_auto_residual_cleanup.production_apply import (
    SOURCE_OPERATOR_EXPLICIT,
    create_operator_approval,
    execute_production_cleanup,
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
    "ApprovalError",
    "CleanupApproval",
    "ProductionBrokerSubmitDisabled",
    "ResidualCleanupContext",
    "SOURCE_OPERATOR_EXPLICIT",
    "apply_cleanup",
    "apply_verified_fill_to_residual",
    "assert_architecture_invariants",
    "create_operator_approval",
    "evaluate_eligibility",
    "execute_production_cleanup",
    "issue_cleanup_approval",
    "prepare_cleanup",
    "preview_cleanup",
    "preview_residual_cleanup",
    "preview_result_hash",
    "provenance_current_qty",
    "resolve_cleanup_sell_quantity",
]
