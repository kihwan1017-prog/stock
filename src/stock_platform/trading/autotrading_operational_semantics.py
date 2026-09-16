"""Autotrading operational status semantics — RUNNING / ENTRY_RESTRICTED / SYSTEM_BLOCKED.

Trading policy unchanged. UI/ops-status 표현 분리용.
"""

from __future__ import annotations

from typing import Any, Literal

OperationalTier = Literal["RUNNING", "ENTRY_RESTRICTED", "SYSTEM_BLOCKED"]

# funnel FIRST_ZERO — informational only (READY=true 허용, 차단 UI 금지)
INFORMATIONAL_FIRST_ZERO_REASONS = frozenset(
    {
        "NO_CANDIDATE_SNAPSHOT",
        "NO_GOLDEN_CROSS_SIGNAL",
        "NO_SIGNAL",
        "MARKET_CLOSED",
        "SHORT_MA_NOT_ABOVE_LONG_MA",
        "ENTRY_PASS",
        "SIGNAL_EMITTED",
        "BEGIN_ENTRY",
    }
)

# 실제 안전 장애 → SYSTEM_BLOCKED
SYSTEM_BLOCKER_CODES = frozenset(
    {
        "LIVE_OFF",
        "ARM_OFF",
        "ARM_OFF_OR_EXPIRED",
        "ACTIVATION_INACTIVE",
        "KILL_SWITCH_ACTIVE",
        "PARTIAL_RESTORE",
        "CONTROL_STATE_MISMATCH",
        "EXECUTION_STATE_MISMATCH",
        "GHOST_OPEN_BINDING",
        "FILLED_EXIT_WITH_OPEN_BINDING",
        "EXIT_DOWN_WITH_OPEN_POSITION",
        "EXECUTION_STACK_DOWN",
        "FEED_UNHEALTHY",
        "MARKET_FEED_UNHEALTHY",
        "LIVE_ARM_ACTIVATION_INCOMPLETE",
        "WAITING_SLOT_STARVATION_BROKEN",
        "UBA_INACTIVE",
        "ACCOUNT_PAUSED",
        "TRADING_PAUSED",
        "RECOVERY_CONFLICT",
        "AMBIGUOUS_ORDER",
        "SUBMISSION_UNKNOWN",
        "CREDENTIAL_FAILURE",
    }
)

SYSTEM_HEALTH_REASONS = frozenset(
    {
        "PARTIAL_RESTORE",
        "CONTROL_STATE_MISMATCH",
        "EXECUTION_STATE_MISMATCH",
        "GHOST_OPEN_BINDING",
        "EXIT_DOWN_WITH_OPEN_POSITION",
        "EXECUTION_STACK_DOWN",
        "FEED_UNHEALTHY",
        "LIVE_ARM_ACTIVATION_INCOMPLETE",
        "WAITING_SLOT_STARVATION_BROKEN",
        "MASTER_GATE_BLOCKERS",
    }
)

TIER_LABELS_KO = {
    "RUNNING": "자동매매 정상",
    "ENTRY_RESTRICTED": "청산 주문 체결 대기",
    "SYSTEM_BLOCKED": "자동매매 차단",
}

BLOCKER_LABELS_KO = {
    "LIVE_OFF": "LIVE 비활성",
    "ARM_OFF": "ARM 비활성",
    "ARM_OFF_OR_EXPIRED": "ARM 만료",
    "ACTIVATION_INACTIVE": "세션 활성화 만료",
    "KILL_SWITCH_ACTIVE": "Kill Switch",
    "PARTIAL_RESTORE": "실행 스택 불완전",
    "MARKET_FEED_UNHEALTHY": "시세 피드 장애",
    "FEED_UNHEALTHY": "시세 피드 장애",
    "EXECUTION_STACK_DOWN": "실행 스택 중단",
    "RECOVERY_CONFLICT": "복구 충돌",
    "AMBIGUOUS_ORDER": "주문 상태 불명확",
    "SUBMISSION_UNKNOWN": "주문 제출 상태 불명",
    "ACCOUNT_PAUSED": "계좌 일시정지",
    "TRADING_PAUSED": "거래 일시정지",
    "EXIT_PENDING_ZERO_FILL_STUCK": "청산 주문 체결 대기",
    "LIVE_NOT_APPROVED": "LIVE 미승인",
    "AUTO_EXIT_QUOTE_STALE": "청산 시세 지연",
    "POSITION_MISMATCH": "포지션 검증 불일치",
}


def _infra_healthy_for_exit_wait(
    *,
    live_on: bool,
    arm_on: bool,
    activation_active: bool,
    partial_restore: bool,
    stack_down: bool,
    feed_healthy: bool,
    exit_monitor_running: bool,
) -> bool:
    return bool(
        live_on
        and arm_on
        and activation_active
        and not partial_restore
        and not stack_down
        and feed_healthy
        and exit_monitor_running
    )


def is_informational_first_zero(
    first_zero_reason: str | None,
    *,
    health_state: str | None = None,
) -> bool:
    """READY=true일 때 funnel FIRST_ZERO만으로 차단 UI 금지."""

    if not first_zero_reason:
        return False
    reason = str(first_zero_reason).strip().upper()
    if reason in INFORMATIONAL_FIRST_ZERO_REASONS:
        return True
    if str(health_state or "").upper() == "READY":
        return reason.startswith("NO_") or reason.endswith("_SIGNAL")
    return False


def classify_operational_status(
    *,
    live_on: bool,
    arm_on: bool,
    activation_active: bool,
    partial_restore: bool,
    stack_down: bool,
    feed_healthy: bool,
    exit_monitor_running: bool,
    health_state: str,
    health_reasons: list[str],
    blockers: list[str],
    exit_pending_stuck: dict[str, Any] | None = None,
    exit_pending_watchdog: dict[str, Any] | None = None,
    first_zero_reason: str | None = None,
    ambiguous_open: bool = False,
    recovery_conflict: bool = False,
    account_paused: bool = False,
) -> dict[str, Any]:
    """운영 3-tier semantics — fail-closed for real safety blockers."""

    reasons: list[str] = []
    system_blockers: list[str] = []

    if not live_on:
        system_blockers.append("LIVE_OFF")
    if not arm_on:
        system_blockers.append("ARM_OFF")
    if not activation_active:
        system_blockers.append("ACTIVATION_INACTIVE")
    if partial_restore:
        system_blockers.append("PARTIAL_RESTORE")
    if stack_down:
        system_blockers.append("EXECUTION_STACK_DOWN")
    if not feed_healthy:
        system_blockers.append("MARKET_FEED_UNHEALTHY")
    if not exit_monitor_running and (exit_pending_stuck or {}).get("stuck"):
        system_blockers.append("EXIT_DOWN_WITH_OPEN_POSITION")
    if ambiguous_open:
        system_blockers.append("AMBIGUOUS_ORDER")
    if recovery_conflict:
        system_blockers.append("RECOVERY_CONFLICT")
    if account_paused:
        system_blockers.append("ACCOUNT_PAUSED")

    for b in blockers:
        code = str(b or "").strip().upper()
        if code in SYSTEM_BLOCKER_CODES and code not in system_blockers:
            system_blockers.append(code)

    for hr in health_reasons:
        code = str(hr or "").strip().upper()
        if code in SYSTEM_HEALTH_REASONS and code not in system_blockers:
            system_blockers.append(code)
        if code == "EXIT_PENDING_ZERO_FILL_STUCK":
            reasons.append(code)

    hs = str(health_state or "").upper()
    if hs == "BROKEN":
        if "HEALTH_BROKEN" not in system_blockers:
            system_blockers.append("HEALTH_BROKEN")
    elif hs == "DEGRADED":
        # DEGRADED — EXIT_PENDING만이면 entry restricted 후보
        non_exit = [
            r
            for r in health_reasons
            if str(r).upper() != "EXIT_PENDING_ZERO_FILL_STUCK"
        ]
        if non_exit and not system_blockers:
            for r in non_exit:
                if str(r).upper() in SYSTEM_HEALTH_REASONS:
                    system_blockers.append(str(r).upper())

    exit_stuck = bool((exit_pending_stuck or {}).get("stuck"))
    exit_watch = exit_pending_watchdog or {}
    has_exit_wait = exit_stuck or bool(exit_watch.get("items"))

    infra_ok = _infra_healthy_for_exit_wait(
        live_on=live_on,
        arm_on=arm_on,
        activation_active=activation_active,
        partial_restore=partial_restore,
        stack_down=stack_down,
        feed_healthy=feed_healthy,
        exit_monitor_running=exit_monitor_running,
    )

    tier: OperationalTier
    entry_restricted = False
    entry_restricted_reason: str | None = None

    if system_blockers:
        tier = "SYSTEM_BLOCKED"
    elif has_exit_wait and infra_ok and not ambiguous_open:
        tier = "ENTRY_RESTRICTED"
        entry_restricted = True
        entry_restricted_reason = "EXIT_PENDING_ZERO_FILL_STUCK"
        reasons.append("EXIT_PENDING_ZERO_FILL_STUCK")
    elif is_informational_first_zero(first_zero_reason, health_state=hs):
        tier = "RUNNING"
    else:
        tier = "RUNNING"

    primary_blocker = system_blockers[0] if system_blockers else None
    if tier == "ENTRY_RESTRICTED":
        primary_blocker = entry_restricted_reason

    return {
        "operational_tier": tier,
        "operational_label_ko": TIER_LABELS_KO[tier],
        "system_blocked": tier == "SYSTEM_BLOCKED",
        "entry_restricted": entry_restricted,
        "entry_restricted_reason": entry_restricted_reason,
        "system_blockers": system_blockers,
        "informational_first_zero": is_informational_first_zero(
            first_zero_reason, health_state=hs
        ),
        "primary_blocker_ko": (
            BLOCKER_LABELS_KO.get(str(primary_blocker or ""), primary_blocker)
        ),
        "primary_blocker_code": primary_blocker,
        "exit_pending_zero_fill_class": (
            _exit_pending_class(exit_watch, exit_pending_stuck)
        ),
    }


def _exit_pending_class(
    watchdog: dict[str, Any] | None,
    stuck: dict[str, Any] | None,
) -> str | None:
    items = (watchdog or {}).get("items") or (stuck or {}).get("items") or []
    if not items:
        return None
    primary = items[0] if isinstance(items[0], dict) else {}
    return str(primary.get("watchdog_state") or primary.get("state") or "")
