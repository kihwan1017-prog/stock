"""LIVE Shadow Mode — 실주문 전송 없이 Signal→Risk→Intent 검증.

Fail Closed: live_shadow_mode_enabled 기본 False.
Shadow ON이면 LIVE broker submit/cancel/replace HTTP 0.
"""

from __future__ import annotations

from typing import Any

from stock_platform.common.settings import get_settings

# 관측용 — 테스트에서 Broker 전송 시도 횟수 검증
_broker_submit_blocked_count = 0
_broker_mutate_attempt_count = 0


def reset_shadow_counters() -> None:
    global _broker_submit_blocked_count, _broker_mutate_attempt_count
    _broker_submit_blocked_count = 0
    _broker_mutate_attempt_count = 0


def shadow_counters() -> dict[str, int]:
    return {
        "broker_submit_blocked": _broker_submit_blocked_count,
        "broker_mutate_attempts": _broker_mutate_attempt_count,
    }


def is_live_shadow_mode(settings: Any | None = None) -> bool:
    s = settings or get_settings()
    return bool(getattr(s, "live_shadow_mode_enabled", False))


def mark_shadow_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = dict(metadata or {})
    meta["environment"] = "LIVE"
    meta["shadow"] = True
    meta["shadow_mode"] = "LIVE_SHADOW"
    meta["broker_submit"] = "BLOCKED"
    return meta


def shadow_block_dispatch_result(*, event_type: str) -> dict[str, Any]:
    """Outbox dispatcher가 어댑터 호출 없이 반환하는 차단 결과."""

    global _broker_submit_blocked_count, _broker_mutate_attempt_count
    _broker_mutate_attempt_count += 1
    _broker_submit_blocked_count += 1
    return {
        "accepted": False,
        "status": "SHADOW_BLOCKED",
        "broker_order_id": None,
        "reject_code": "LIVE_SHADOW_MODE",
        "reject_message": (
            f"LIVE shadow mode blocked broker {event_type}; "
            "no order/cancel/replace API call"
        ),
        "submitted_at": None,
        "shadow_blocked": True,
    }


def should_block_live_broker_call(payload: dict[str, Any] | None) -> bool:
    """LIVE 환경에서 Shadow Flag 또는 payload.shadow 이면 전송 차단."""

    data = payload or {}
    env = str(data.get("environment") or "PAPER").upper()
    if env != "LIVE":
        return False
    if bool(data.get("shadow")) or str(data.get("shadow_mode") or "").upper() == "LIVE_SHADOW":
        return True
    return is_live_shadow_mode()
