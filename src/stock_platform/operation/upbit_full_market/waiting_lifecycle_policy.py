"""UPBIT WAITING slot lifecycle policy — release/replacement thresholds (strategy 변경 없음)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.operation.upbit_full_market.constants import (
    DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS,
)
from stock_platform.operation.upbit_full_market.slot_replacement import (
    PERSISTENT_BLOCK_REASONS,
    load_replacement_policy,
)

# entry gate — 일시적 (MA/RSI), 전략 threshold 변경 없음
TEMPORARY_BLOCK_REASONS = frozenset(PERSISTENT_BLOCK_REASONS)

TERMINAL_BLOCK_REASONS = frozenset(
    {
        "CANDIDATE_STALE",
        "CANDIDATE_EXPIRED",
        "SYMBOL_UNAVAILABLE",
        "DATA_INVALID",
        "RISK_PERMANENTLY_INVALID",
        "BINDING_INVALID",
        "AI_SELECTION_NOT_ALLOW",
    }
)

REASON_SOFT_STALE_NO_SIGNAL = "SOFT_STALE_NO_ENTRY_SIGNAL"
REASON_HARD_EXPIRE_NO_SIGNAL = "HARD_EXPIRE_NO_ENTRY_SIGNAL"
REASON_CONSECUTIVE_BLOCK_RELEASE = "CONSECUTIVE_NO_SIGNAL_RELEASE"


@dataclass(frozen=True, slots=True)
class WaitingLifecyclePolicy:
    """WAITING revalidation / release / replacement eligibility."""

    revalidation_interval_seconds: float = 300.0
    soft_stale_seconds: float = 1800.0
    hard_expire_no_signal_seconds: float = 5400.0
    consecutive_no_signal_threshold: int = 3
    starvation_degraded_seconds: float = 900.0
    starvation_broken_seconds: float = 3600.0
    hold_seconds: float = 1800.0
    max_wait_seconds: float = DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS
    switch_min_score_delta: float = 8.0


def classify_waiting_block_reason(reason: str | None) -> str:
    """TEMPORARY | TERMINAL | UNKNOWN — 실제 코드 reason만 사용."""

    code = str(reason or "").upper().strip()
    if not code:
        return "UNKNOWN"
    if code in TERMINAL_BLOCK_REASONS:
        return "TERMINAL"
    if code in TEMPORARY_BLOCK_REASONS:
        return "TEMPORARY"
    return "UNKNOWN"


def load_waiting_lifecycle_policy(
    *,
    settings: Any,
    risk_group_policy_json: dict[str, Any] | None = None,
) -> WaitingLifecyclePolicy:
    """settings + policy JSON — migration 없음."""

    blob = dict(risk_group_policy_json or {})
    repl = load_replacement_policy(
        settings=settings,
        risk_group_policy_json=blob,
    )

    def _f(key: str, attr: str, default: float) -> float:
        if key in blob and blob[key] is not None:
            try:
                return float(blob[key])
            except (TypeError, ValueError):
                pass
        raw = getattr(settings, attr, None)
        try:
            return float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    def _i(key: str, attr: str, default: int) -> int:
        if key in blob and blob[key] is not None:
            try:
                return int(blob[key])
            except (TypeError, ValueError):
                pass
        raw = getattr(settings, attr, None)
        try:
            return int(raw) if raw is not None else int(default)
        except (TypeError, ValueError):
            return int(default)

    soft = _f(
        "waiting_soft_stale_seconds",
        "upbit_waiting_soft_stale_seconds",
        1800.0,
    )
    hard = _f(
        "waiting_hard_expire_no_signal_seconds",
        "upbit_waiting_hard_expire_no_signal_seconds",
        5400.0,
    )
    hard = min(hard, repl.max_wait_seconds)
    soft = min(soft, hard)
    return WaitingLifecyclePolicy(
        revalidation_interval_seconds=_f(
            "waiting_revalidation_interval_seconds",
            "upbit_waiting_revalidation_interval_seconds",
            300.0,
        ),
        soft_stale_seconds=soft,
        hard_expire_no_signal_seconds=hard,
        consecutive_no_signal_threshold=_i(
            "waiting_consecutive_no_signal_threshold",
            "upbit_waiting_consecutive_no_signal_threshold",
            3,
        ),
        starvation_degraded_seconds=_f(
            "waiting_starvation_degraded_seconds",
            "upbit_waiting_starvation_degraded_seconds",
            900.0,
        ),
        starvation_broken_seconds=_f(
            "waiting_starvation_broken_seconds",
            "upbit_waiting_starvation_broken_seconds",
            3600.0,
        ),
        hold_seconds=repl.hold_seconds,
        max_wait_seconds=repl.max_wait_seconds,
        switch_min_score_delta=repl.switch_min_score_delta,
    )
