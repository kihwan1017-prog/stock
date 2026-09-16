"""LIVE Order Dry-Run — Broker submit 직전 Payload 검증 후 차단.

Fail Closed: live_order_dry_run_enabled 기본 False.
Risk/Kill/Pause/Market session은 LIVE와 동일. submit/cancel/replace HTTP 0.
"""

from __future__ import annotations

from typing import Any

from stock_platform.common.settings import get_settings

_dry_run_blocked_count = 0
_dry_run_mutate_attempt_count = 0


def reset_dry_run_counters() -> None:
    global _dry_run_blocked_count, _dry_run_mutate_attempt_count
    _dry_run_blocked_count = 0
    _dry_run_mutate_attempt_count = 0


def dry_run_counters() -> dict[str, int]:
    return {
        "dry_run_blocked": _dry_run_blocked_count,
        "broker_mutate_attempts": _dry_run_mutate_attempt_count,
    }


def is_live_dry_run_mode(settings: Any | None = None) -> bool:
    s = settings or get_settings()
    return bool(getattr(s, "live_order_dry_run_enabled", False))


def mark_dry_run_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = dict(metadata or {})
    meta["environment"] = "LIVE"
    meta["dry_run"] = True
    meta["dry_run_mode"] = "LIVE_DRY_RUN"
    meta["broker_submit"] = "DRY_RUN_BLOCKED"
    return meta


def should_block_live_dry_run(payload: dict[str, Any] | None) -> bool:
    data = payload or {}
    env = str(data.get("environment") or "PAPER").upper()
    if env != "LIVE":
        return False
    if bool(data.get("dry_run")) or str(
        data.get("dry_run_mode") or ""
    ).upper() == "LIVE_DRY_RUN":
        return True
    return is_live_dry_run_mode()


def validate_pre_submit_payload(payload: dict[str, Any]) -> list[str]:
    """Broker submit 직전 필수 필드 검증. 누락 시 오류 코드 목록."""

    env = str(payload.get("environment") or "PAPER").upper()
    required = (
        "client_order_id",
        "broker_code",
        "exchange_code",
        "symbol",
        "side",
        "order_type",
        "quantity",
    )
    missing: list[str] = []
    for key in required:
        value = payload.get(key)
        if value is None or str(value).strip() == "":
            missing.append(f"MISSING_{key.upper()}")
    # LIVE: UBA 필수 / Paper FK(account_id) 금지
    # PAPER: paper account_id 필수
    if env == "LIVE":
        uba = payload.get("user_broker_account_id")
        if uba is None or str(uba).strip() == "":
            missing.append("MISSING_USER_BROKER_ACCOUNT_ID")
        if payload.get("account_id") not in (None, ""):
            missing.append("LIVE_MUST_NOT_SET_PAPER_ACCOUNT_ID")
    else:
        paper = payload.get("account_id")
        if paper is None or str(paper).strip() == "":
            missing.append("MISSING_ACCOUNT_ID")
    # price: LIMIT만 필수
    order_type = str(payload.get("order_type") or "").upper()
    if order_type == "LIMIT":
        price = payload.get("price")
        if price is None or str(price).strip() == "":
            missing.append("MISSING_PRICE")
    try:
        qty = payload.get("quantity")
        if qty is not None and float(qty) <= 0:
            missing.append("INVALID_QUANTITY")
    except (TypeError, ValueError):
        missing.append("INVALID_QUANTITY")
    return missing


def dry_run_block_dispatch_result(
    *,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Outbox dispatcher가 어댑터 호출 없이 반환하는 Dry-run 차단 결과."""

    global _dry_run_blocked_count, _dry_run_mutate_attempt_count
    _dry_run_mutate_attempt_count += 1
    _dry_run_blocked_count += 1
    errors = validate_pre_submit_payload(payload or {})
    return {
        "accepted": False,
        "status": "DRY_RUN_BLOCKED",
        "broker_order_id": None,
        "reject_code": "DRY_RUN_BLOCKED",
        "reject_message": (
            f"LIVE dry-run blocked broker {event_type}; "
            "pre-submit validated, no API call"
        ),
        "submitted_at": None,
        "dry_run_blocked": True,
        "pre_submit_errors": errors,
        "pre_submit_ok": len(errors) == 0,
    }
