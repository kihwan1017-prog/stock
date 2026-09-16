"""STEP 11-5 — Request 상태 전이 가드."""

from __future__ import annotations

from stock_platform.ai.execution.constants import (
    REQUEST_TRANSITIONS,
    TERMINAL_REQUEST,
    RequestStatus,
)


class InvalidStateTransition(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Invalid transition {current} → {target}")
        self.current = current
        self.target = target


def assert_request_transition(current: str, target: str) -> None:
    cur = RequestStatus(current)
    tgt = RequestStatus(target)
    if cur in TERMINAL_REQUEST:
        raise InvalidStateTransition(current, target)
    allowed = REQUEST_TRANSITIONS.get(cur, frozenset())
    if tgt not in allowed:
        raise InvalidStateTransition(current, target)
