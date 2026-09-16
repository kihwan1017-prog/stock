"""AI Signal Gate — risk-reducing SELL/EXIT bypass 정책.

AI는 신규 위험(BUY)을 제한할 수 있지만,
강제 위험축소·손절·익절 SELL을 차단해서는 안 된다.

AI Gate 한 단계만 bypass — Risk/OES/holdings/Kill 등은 유지.
"""

from __future__ import annotations

from typing import Any

# MA evaluator / exit monitor에서 실제로 쓰는 reason_code
STOP_LOSS_REASONS = frozenset({"STOP_LOSS"})
TAKE_PROFIT_REASONS = frozenset({"TAKE_PROFIT"})
TRAILING_STOP_REASONS = frozenset({"TRAILING_STOP"})
STRATEGY_POSITION_REDUCING_SELL_REASONS = frozenset(
    {
        # 현물 UPBIT: position.quantity>0 일 때만 emit → short 불가, holdings clip
        "MA_DEAD_CROSS",
    }
)
FORCED_EXIT_REASONS = frozenset(
    {
        "KILL_SWITCH",
        "DAILY_LOSS",
        "FORCE_EXIT",
        "RISK_FORCED_EXIT",
        "EMERGENCY_EXIT",
        "LIQUIDATION",
        "EMERGENCY_LIQUIDATION",
        "MAX_HOLD_TIME",
    }
)

# 명시적 bypass 대상 (문자열 산재 금지 — 여기서만 관리)
AI_GATE_BYPASS_REASON_MAP: dict[str, str] = {
    **{r: "AI_GATE_BYPASS_STOP_LOSS" for r in STOP_LOSS_REASONS},
    **{r: "AI_GATE_BYPASS_TAKE_PROFIT" for r in TAKE_PROFIT_REASONS},
    **{r: "AI_GATE_BYPASS_TRAILING_STOP" for r in TRAILING_STOP_REASONS},
    **{
        r: "AI_GATE_BYPASS_STRATEGY_POSITION_REDUCING_SELL"
        for r in STRATEGY_POSITION_REDUCING_SELL_REASONS
    },
    **{r: "AI_GATE_BYPASS_RISK_EXIT" for r in FORCED_EXIT_REASONS},
}


def normalize_signal_reason(reason_code: str | None) -> str:
    return str(reason_code or "").strip().upper()


def is_risk_reducing_exit_reason(reason_code: str | None) -> bool:
    reason = normalize_signal_reason(reason_code)
    return reason in AI_GATE_BYPASS_REASON_MAP


def should_bypass_ai_gate(signal: Any) -> tuple[bool, str | None]:
    """AI Gate bypass 여부.

    Returns:
        (bypass, reason_code) — bypass=False면 reason_code=None
    """

    action = getattr(signal, "action", None)
    action_u = str(
        getattr(action, "value", action) or ""
    ).strip().upper()
    if action_u not in {"SELL", "EXIT"}:
        return False, None

    reason = normalize_signal_reason(
        getattr(signal, "reason_code", None)
    )
    bypass_code = AI_GATE_BYPASS_REASON_MAP.get(reason)
    if bypass_code:
        return True, bypass_code
    return False, None


def describe_exit_ai_gate_policy() -> dict[str, Any]:
    """Admin/문서용 정책 스냅샷."""

    return {
        "priority": [
            "KillSwitch/Emergency",
            "RiskForcedExit/StopLoss/TakeProfit",
            "AI Gate",
            "Strategy Entry BUY",
        ],
        "bypass_reasons": sorted(AI_GATE_BYPASS_REASON_MAP.keys()),
        "bypass_codes": sorted(set(AI_GATE_BYPASS_REASON_MAP.values())),
        "ma_dead_cross": (
            "BYPASS — spot long-only; emit only when qty>0; "
            "holdings clip after gate"
        ),
        "generic_sell": "NO_BYPASS — still gated",
        "buy": "NO_BYPASS — HOLD blocks entry",
        "note": (
            "bypass is AI Gate only; Risk/OES/holdings/"
            "Kill/Activation/DailyRisk remain"
        ),
    }
