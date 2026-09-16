"""Delivery gate — preference + provenance. Fail-open on errors."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.notification.alert_v2.mapping import resolve_preference_key
from stock_platform.notification.alert_v2.preferences import is_preference_enabled
from stock_platform.notification.alert_v2.provenance import (
    allow_auto_trade_alert,
    classify_trade_provenance,
)


_TRADE_EVENTS = frozenset(
    {
        "ORDER_FILLED",
        "ORDER_PARTIAL_FILLED",
        "POSITION_CLOSED",
        "STOP_LOSS",
        "TAKE_PROFIT",
        "TRAILING_STOP",
        "MA_EXIT",
        "MA_DEAD_CROSS",
        "MA_DEAD_CROSS_EXIT",
    }
)


def should_deliver_trading_alert(
    *,
    event_type: str,
    detail: dict[str, Any] | None,
    session: Session | None = None,
) -> tuple[bool, str]:
    """(allowed, reason). preference OFF → False. DB 오류 → True (fail-open)."""

    et = str(event_type or "").strip().upper()
    d = detail or {}

    # AUTO 체결 알림은 provenance 필수
    if et in _TRADE_EVENTS and not d.get("skip_provenance_check"):
        # ORDER_REJECTED 등은 trade fill 아님
        side = str(d.get("side") or "").upper()
        if et in {"ORDER_FILLED", "ORDER_PARTIAL_FILLED", "POSITION_CLOSED"} or side in {
            "BUY",
            "SELL",
        }:
            prov = classify_trade_provenance(d)
            if prov == "TEST":
                return False, "TEST_SMOKE_EXCLUDED"
            if prov == "MANUAL":
                return False, "MANUAL_EXCLUDED"
            if prov == "UNKNOWN":
                # 명시 AUTO 아닐 때 AUTO 카테고리로 포장 금지
                if d.get("require_auto_provenance", True):
                    # fill path가 order_source를 안 넣으면 기존 호환: strategy 있으면 AUTO
                    if not allow_auto_trade_alert(d):
                        return False, "UNKNOWN_PROVENANCE_EXCLUDED"

    try:
        pref = resolve_preference_key(et, detail=d)
        if pref is None:
            return True, "NO_PREFERENCE_MAP"
        if not is_preference_enabled(session, pref):
            return False, f"PREFERENCE_OFF:{pref.value}"
        return True, f"PREFERENCE_ON:{pref.value}"
    except Exception:  # noqa: BLE001
        return True, "PREFERENCE_CHECK_FAIL_OPEN"
