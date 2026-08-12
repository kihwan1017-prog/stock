"""Telegram / Notification — Alert-only, LIVE 자동 시작 없음."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.notification.events import NotificationEventType
from stock_platform.notification.publisher import notification_publisher

logger = structlog.get_logger(__name__)

EVENT_SCANNER_CANDIDATE = "UPBIT_SCANNER_CANDIDATE"


def _ensure_event_type() -> str:
    return str(
        getattr(
            NotificationEventType,
            "UPBIT_SCANNER_CANDIDATE",
            EVENT_SCANNER_CANDIDATE,
        )
    )


def publish_scanner_alerts(
    *,
    candidates: list[dict[str, Any]],
    notify_hold: bool,
    run_meta: dict[str, Any],
) -> dict[str, Any]:
    """ALLOW/REDUCE 우선 알림. HOLD는 기본 스킵. 없으면 Top-N 요약 1건."""

    emitted = 0
    skipped_hold = 0
    skipped_cooldown = 0
    errors = 0
    summary_emitted = False

    priority = {"ALLOW": 0, "REDUCE": 1, "HOLD": 2}
    ordered = sorted(
        candidates,
        key=lambda c: (
            priority.get(str(c.get("recommendation") or "HOLD").upper(), 9),
            int(c.get("rank") or 99),
        ),
    )

    for item in ordered:
        if item.get("cooldown_suppressed"):
            skipped_cooldown += 1
            continue
        rec = str(item.get("recommendation") or "HOLD").upper()
        if rec == "HOLD" and not notify_hold:
            skipped_hold += 1
            continue
        if rec not in {"ALLOW", "REDUCE"} and not notify_hold:
            skipped_hold += 1
            continue

        symbol = str(item.get("symbol") or "")
        title = f"UPBIT Opportunity #{item.get('rank')} {symbol}"
        message = (
            f"[UPBIT Opportunity]\n"
            f"#{item.get('rank')} {symbol}\n"
            f"Scanner Score: {item.get('score')}\n"
            f"Price: {item.get('price')}\n"
            f"MA spread%: {item.get('ma_spread_pct')}\n"
            f"Momentum5m%: {item.get('momentum_5m_pct')}\n"
            f"RSI: {item.get('rsi14')}\n"
            f"AI: {rec}\n"
            f"Confidence: {item.get('confidence')}\n"
            f"Risk: {item.get('risk_level')}\n"
            f"Alert only\n"
            f"LIVE auto start: false"
        )
        detail = {
            "source": "upbit_opportunity_scanner_v0",
            "live_auto_start": False,
            "orders_created": 0,
            "runtime_mutated": False,
            "candidate": item,
            "run_meta": {
                k: run_meta.get(k)
                for k in (
                    "universe_count",
                    "liquidity_pass_count",
                    "technical_candidate_count",
                    "elapsed_ms",
                )
            },
        }
        try:
            notification_publisher.publish(
                event_type=_ensure_event_type(),
                title=title,
                message=message,
                detail=detail,
            )
            emitted += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning(
                "upbit_scanner_notify_failed",
                symbol=symbol,
                error=type(exc).__name__,
            )

    # HOLD-only / AI blocked 시에도 운영 가시성용 요약 1건
    # cooldown 억제된 후보만 남은 경우에는 반복 요약 금지
    alertable = [c for c in candidates if not c.get("cooldown_suppressed")]
    if emitted == 0 and alertable:
        lines = ["[UPBIT Opportunity Scanner Top-N]", "Alert only / LIVE auto start: false"]
        for item in alertable[:5]:
            lines.append(
                f"#{item.get('rank')} {item.get('symbol')} "
                f"score={item.get('score')} AI={item.get('recommendation') or 'N/A'}"
                f"{(' err=' + str(item.get('ai_error'))) if item.get('ai_error') else ''}"
            )
        try:
            notification_publisher.publish(
                event_type=_ensure_event_type(),
                title="UPBIT Opportunity Scanner Top-N",
                message="\n".join(lines),
                detail={
                    "source": "upbit_opportunity_scanner_v0_summary",
                    "live_auto_start": False,
                    "orders_created": 0,
                    "candidates": alertable,
                    "run_meta": {
                        k: run_meta.get(k)
                        for k in (
                            "universe_count",
                            "liquidity_pass_count",
                            "technical_candidate_count",
                            "ai_calls",
                            "elapsed_ms",
                        )
                    },
                },
            )
            summary_emitted = True
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning(
                "upbit_scanner_summary_notify_failed",
                error=type(exc).__name__,
            )

    return {
        "emitted": emitted,
        "summary_emitted": summary_emitted,
        "skipped_hold": skipped_hold,
        "skipped_cooldown": skipped_cooldown,
        "errors": errors,
    }
