"""In-process execution trace context — begin_entry 등 signal 없는 구간 연계."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_current: ContextVar[dict[str, Any] | None] = ContextVar(
    "upbit_entry_execution_trace_ctx", default=None
)


def set_current(ctx: dict[str, Any] | None) -> None:
    _current.set(ctx)


def get_current() -> dict[str, Any] | None:
    return _current.get()


def clear_current() -> None:
    _current.set(None)
