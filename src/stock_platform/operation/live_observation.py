"""LIVE 재가동 관찰 — observability timeout과 critical safety를 분리한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.operation.observability_http import (
    OBSERVABILITY_TIMEOUT,
    observability_timeout_should_rollback,
)


ACTION_CONTINUE = "CONTINUE"
ACTION_ROLLBACK = "ROLLBACK"


@dataclass
class CriticalSafetySnapshot:
    live_on: bool
    arm_on: bool
    kill_off: bool
    recovery_success: bool
    connected: bool
    credential_verified: bool
    account_paused: bool
    trading_paused: bool
    kiwoom_live_off: bool
    runner_error: str | None = None
    first_fail: str | None = None

    @property
    def ok(self) -> bool:
        if self.first_fail:
            return False
        if not self.live_on:
            return False
        if not self.arm_on:
            return False
        if not self.kill_off:
            return False
        if not self.recovery_success:
            return False
        if not self.connected:
            return False
        if not self.credential_verified:
            return False
        if self.account_paused or self.trading_paused:
            return False
        if not self.kiwoom_live_off:
            return False
        if self.runner_error:
            return False
        return True


@dataclass
class ObservationDecision:
    action: str
    observability: str
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "observability": self.observability,
            "reason": self.reason,
        }


def decide_observation_action(
    *,
    observability_class: str,
    critical: CriticalSafetySnapshot,
) -> ObservationDecision:
    """critical 실패만 rollback. informational timeout은 DEGRADED로 유지."""

    if not critical.ok:
        return ObservationDecision(
            action=ACTION_ROLLBACK,
            observability=observability_class,
            reason=critical.first_fail or "CRITICAL_SAFETY_FAIL",
        )
    if observability_class == OBSERVABILITY_TIMEOUT:
        assert observability_timeout_should_rollback() is False
        return ObservationDecision(
            action=ACTION_CONTINUE,
            observability="OBSERVABILITY_DEGRADED",
            reason=OBSERVABILITY_TIMEOUT,
        )
    return ObservationDecision(
        action=ACTION_CONTINUE,
        observability="OK",
        reason=None,
    )
