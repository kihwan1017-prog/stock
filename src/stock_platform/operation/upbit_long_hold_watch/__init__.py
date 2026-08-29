# -*- coding: utf-8 -*-
"""UPBIT AUTO long-hold observability (Alert V2) — no REAL Time Exit."""

from __future__ import annotations

from typing import Any


def select_latest_checkpoint(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_long_hold_watch.checkpoints import (
        select_latest_checkpoint as _impl,
    )

    return _impl(*args, **kwargs)


def long_hold_badge(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_long_hold_watch.checkpoints import (
        long_hold_badge as _impl,
    )

    return _impl(*args, **kwargs)


def format_long_hold_alert(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_long_hold_watch.service import (
        format_long_hold_alert as _impl,
    )

    return _impl(*args, **kwargs)


def evaluate_long_hold_positions(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_long_hold_watch.service import (
        evaluate_long_hold_positions as _impl,
    )

    return _impl(*args, **kwargs)


def run_long_hold_watch_once(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_long_hold_watch.service import (
        run_long_hold_watch_once as _impl,
    )

    return _impl(*args, **kwargs)


def build_long_hold_summary(*args: Any, **kwargs: Any):
    from stock_platform.operation.upbit_long_hold_watch.service import (
        build_long_hold_summary as _impl,
    )

    return _impl(*args, **kwargs)


__all__ = [
    "select_latest_checkpoint",
    "long_hold_badge",
    "format_long_hold_alert",
    "evaluate_long_hold_positions",
    "run_long_hold_watch_once",
    "build_long_hold_summary",
]
