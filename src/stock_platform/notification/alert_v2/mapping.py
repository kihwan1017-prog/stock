"""기존 event_type → V2 preference / top category 매핑 (event rename 금지)."""

from __future__ import annotations

from typing import Any

from stock_platform.notification.alert_v2.categories import (
    AlertPreferenceKey,
    AlertTopCategory,
)

# event_type → preference key (side/market으로 세분화 필요 시 resolve에서 처리)
_EVENT_PREFERENCE: dict[str, AlertPreferenceKey] = {
    "SYSTEM_START": AlertPreferenceKey.SYSTEM_OPERATION,
    "SYSTEM_STOP": AlertPreferenceKey.SYSTEM_OPERATION,
    "SYSTEM_RESTART": AlertPreferenceKey.SYSTEM_OPERATION,
    "MONITORING_ALERT": AlertPreferenceKey.SYSTEM_OPERATION,
    "KILL_SWITCH": AlertPreferenceKey.SYSTEM_OPERATION,
    "DAILY_LOSS": AlertPreferenceKey.SYSTEM_OPERATION,
    "BROKER_DISCONNECTED": AlertPreferenceKey.SYSTEM_OPERATION,
    "BROKER_RECONNECTED": AlertPreferenceKey.SYSTEM_OPERATION,
    "RECOVERY_FAILED": AlertPreferenceKey.SYSTEM_OPERATION,
    "RECONCILIATION_MISMATCH": AlertPreferenceKey.SYSTEM_OPERATION,
    "UPBIT_SCANNER_FAILURE": AlertPreferenceKey.SYSTEM_OPERATION,
    "RUNTIME_ERROR": AlertPreferenceKey.SYSTEM_OPERATION,
    "SCHEDULER_ERROR": AlertPreferenceKey.SYSTEM_OPERATION,
    "AUTOTRADING_DAILY_REPORT": AlertPreferenceKey.SYSTEM_OPERATION,
    "ORDER_REJECTED": AlertPreferenceKey.UPBIT_ORDER_EXCEPTION,  # market refine
    "AI_GATE_RECOMMENDATION_CHANGED": AlertPreferenceKey.UPBIT_AI_DECISION,
    "UPBIT_PORTFOLIO_SLOT_ASSIGNED": AlertPreferenceKey.AUTO_SLOT,
    "UPBIT_PORTFOLIO_CANDIDATE_REPLACED": AlertPreferenceKey.AUTO_SLOT,
    "UPBIT_SCANNER_CANDIDATE": AlertPreferenceKey.CANDIDATE_ANALYSIS,
    "UPBIT_SCANNER_SHADOW_OPENED": AlertPreferenceKey.SHADOW_ANALYSIS,
    "UPBIT_SCANNER_SHADOW_RESULT": AlertPreferenceKey.SHADOW_ANALYSIS,
    "UPBIT_SHADOW_COHORT_30_REVIEW_READY": AlertPreferenceKey.SHADOW_ANALYSIS,
    "STOP_LOSS": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "TAKE_PROFIT": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "TRAILING_STOP": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "MA_EXIT": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "MA_DEAD_CROSS": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "MA_DEAD_CROSS_EXIT": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "POSITION_CLOSED": AlertPreferenceKey.UPBIT_AUTO_SELL,
    "ORDER_FILLED": AlertPreferenceKey.UPBIT_AUTO_BUY,  # side refine
    "ORDER_PARTIAL_FILLED": AlertPreferenceKey.UPBIT_AUTO_BUY,
    "TEST_NOTIFICATION": AlertPreferenceKey.SYSTEM_OPERATION,
}


def _market_of(detail: dict[str, Any] | None) -> str:
    d = detail or {}
    raw = str(
        d.get("telegram_market")
        or d.get("market")
        or d.get("broker_code")
        or d.get("market_code")
        or ""
    ).strip().upper()
    if raw in {"UPBIT", "CRYPTO"}:
        return "UPBIT"
    if raw in {"KIWOOM", "KRX", "STOCK"}:
        return "KIWOOM"
    return "COMMON"


def resolve_preference_key(
    event_type: str,
    *,
    detail: dict[str, Any] | None = None,
) -> AlertPreferenceKey | None:
    """알림 OFF 판정용 preference. 매핑 없으면 None → SYSTEM_OPERATION fail-open."""

    et = str(event_type or "").strip().upper()
    d = detail or {}
    market = _market_of(d)
    side = str(d.get("side") or d.get("side_code") or "").strip().upper()
    kind = str(d.get("alert_kind") or d.get("runtime_kind") or "").upper()

    if et in {"ORDER_FILLED", "ORDER_PARTIAL_FILLED"}:
        if side == "SELL":
            return (
                AlertPreferenceKey.KIWOOM_AUTO_SELL
                if market == "KIWOOM"
                else AlertPreferenceKey.UPBIT_AUTO_SELL
            )
        return (
            AlertPreferenceKey.KIWOOM_AUTO_BUY
            if market == "KIWOOM"
            else AlertPreferenceKey.UPBIT_AUTO_BUY
        )

    if et == "POSITION_CLOSED" or et in {
        "STOP_LOSS",
        "TAKE_PROFIT",
        "TRAILING_STOP",
        "MA_EXIT",
        "MA_DEAD_CROSS",
        "MA_DEAD_CROSS_EXIT",
    }:
        return (
            AlertPreferenceKey.KIWOOM_AUTO_SELL
            if market == "KIWOOM"
            else AlertPreferenceKey.UPBIT_AUTO_SELL
        )

    if et == "ORDER_REJECTED":
        return (
            AlertPreferenceKey.KIWOOM_ORDER_EXCEPTION
            if market == "KIWOOM"
            else AlertPreferenceKey.UPBIT_ORDER_EXCEPTION
        )

    if et == "AI_GATE_RECOMMENDATION_CHANGED":
        return (
            AlertPreferenceKey.KIWOOM_AI_DECISION
            if market == "KIWOOM"
            else AlertPreferenceKey.UPBIT_AI_DECISION
        )

    if kind in {
        "RUNTIME_START",
        "RUNTIME_STOP",
        "RUNTIME_RECOVERED",
        "STARTED",
        "START",
        "STOPPED_NORMAL",
        "STOPPED_UNEXPECTED",
        "UNEXPECTED_STOP",
        "RECOVERED",
    } or (
        et == "MONITORING_ALERT"
        and str(d.get("subtype") or "").upper().startswith("RUNTIME")
    ):
        return (
            AlertPreferenceKey.KIWOOM_RUNTIME
            if market == "KIWOOM"
            else AlertPreferenceKey.UPBIT_RUNTIME
            if market == "UPBIT"
            else AlertPreferenceKey.SYSTEM_OPERATION
        )

    mapped = _EVENT_PREFERENCE.get(et)
    if mapped is None:
        return AlertPreferenceKey.SYSTEM_OPERATION
    # 시장 보정: UPBIT_* keys when KIWOOM
    if market == "KIWOOM":
        if mapped == AlertPreferenceKey.UPBIT_ORDER_EXCEPTION:
            return AlertPreferenceKey.KIWOOM_ORDER_EXCEPTION
        if mapped == AlertPreferenceKey.UPBIT_AI_DECISION:
            return AlertPreferenceKey.KIWOOM_AI_DECISION
        if mapped == AlertPreferenceKey.UPBIT_AUTO_BUY:
            return AlertPreferenceKey.KIWOOM_AUTO_BUY
        if mapped == AlertPreferenceKey.UPBIT_AUTO_SELL:
            return AlertPreferenceKey.KIWOOM_AUTO_SELL
    return mapped


def resolve_top_category(
    event_type: str,
    *,
    detail: dict[str, Any] | None = None,
) -> AlertTopCategory:
    pref = resolve_preference_key(event_type, detail=detail)
    if pref is None:
        return AlertTopCategory.SYSTEM
    name = pref.value
    if name.startswith("UPBIT_") and name not in {
        AlertPreferenceKey.UPBIT_AI_DECISION.value,
    }:
        # UPBIT_AI is SYSTEM group UX
        if pref in {
            AlertPreferenceKey.UPBIT_RUNTIME,
            AlertPreferenceKey.UPBIT_AUTO_BUY,
            AlertPreferenceKey.UPBIT_AUTO_SELL,
            AlertPreferenceKey.UPBIT_ORDER_EXCEPTION,
        }:
            return AlertTopCategory.UPBIT
    if pref in {
        AlertPreferenceKey.KIWOOM_RUNTIME,
        AlertPreferenceKey.KIWOOM_AUTO_BUY,
        AlertPreferenceKey.KIWOOM_AUTO_SELL,
        AlertPreferenceKey.KIWOOM_ORDER_EXCEPTION,
    }:
        return AlertTopCategory.KIWOOM
    # AI / slot / candidate / shadow / system_operation → SYSTEM UI group
    # but title prefix for trades uses market
    market = _market_of(detail)
    if pref in {
        AlertPreferenceKey.UPBIT_AUTO_BUY,
        AlertPreferenceKey.UPBIT_AUTO_SELL,
        AlertPreferenceKey.UPBIT_RUNTIME,
        AlertPreferenceKey.UPBIT_ORDER_EXCEPTION,
    }:
        return AlertTopCategory.UPBIT
    if market == "UPBIT" and pref in {
        AlertPreferenceKey.UPBIT_AI_DECISION,
    }:
        return AlertTopCategory.SYSTEM
    if market == "KIWOOM" and pref == AlertPreferenceKey.KIWOOM_AI_DECISION:
        return AlertTopCategory.SYSTEM
    return AlertTopCategory.SYSTEM


def title_prefix_for(
    event_type: str,
    *,
    detail: dict[str, Any] | None = None,
) -> str:
    """Telegram 사용자 prefix. AI/슬롯/Shadow/시스템 → [시스템]."""

    from stock_platform.notification.alert_v2.categories import USER_PREFIX

    pref = resolve_preference_key(event_type, detail=detail)
    if pref in {
        AlertPreferenceKey.UPBIT_AI_DECISION,
        AlertPreferenceKey.KIWOOM_AI_DECISION,
        AlertPreferenceKey.AUTO_SLOT,
        AlertPreferenceKey.CANDIDATE_ANALYSIS,
        AlertPreferenceKey.SHADOW_ANALYSIS,
        AlertPreferenceKey.SYSTEM_OPERATION,
    }:
        return USER_PREFIX[AlertTopCategory.SYSTEM]
    top = resolve_top_category(event_type, detail=detail)
    return USER_PREFIX.get(top, USER_PREFIX[AlertTopCategory.SYSTEM])
