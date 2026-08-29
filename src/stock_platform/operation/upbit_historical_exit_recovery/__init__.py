# -*- coding: utf-8 -*-
"""UPBIT historical orphan exit — DETECT_ONLY / dry-run (no intent INSERT)."""

from __future__ import annotations

from typing import Any


def list_historical_exit_recovery_candidates(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_historical_exit_recovery.service import (
        list_historical_exit_recovery_candidates as _impl,
    )

    return _impl(*args, **kwargs)


def dry_run_historical_exit_recovery(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_historical_exit_recovery.service import (
        dry_run_historical_exit_recovery as _impl,
    )

    return _impl(*args, **kwargs)


__all__ = [
    "list_historical_exit_recovery_candidates",
    "dry_run_historical_exit_recovery",
]
