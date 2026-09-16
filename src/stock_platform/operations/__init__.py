"""Operation Rehearsal Automation (STEP 8-6-1)."""

from __future__ import annotations

__all__ = [
    "RehearsalOptions",
    "run_operation_rehearsal",
]

from stock_platform.operations.rehearsal.models import RehearsalOptions
from stock_platform.operations.rehearsal.runner import (
    run_operation_rehearsal,
)
