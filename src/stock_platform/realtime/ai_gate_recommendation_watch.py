"""AI Gate recommendation 변화 감시 — LIVE 자동 시작 없음.

HOLD→ALLOW/REDUCE 시에만 Audit + Notification.
실거래/LIVE/ARM/Runtime/Worker/AI LIVE Gate는 변경하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

EVENT_RECOMMENDATION_CHANGED = "AI_GATE_RECOMMENDATION_CHANGED"
STATUS_WAITING_HOLD = "WAITING_AI_HOLD"
STATUS_READY = "AI_READY_FOR_LIVE_PREFLIGHT"
STATUS_BLOCKED_FEED = "BLOCKED_MARKET_FEED"
STATUS_BLOCKED_ACTIVATION = "BLOCKED_ACTIVATION"
STATUS_BLOCKED_STALE = "BLOCKED_AI_STALE"
STATUS_BLOCKED_MISSING = "BLOCKED_AI_MISSING"
STATUS_HOLD = "AI_HOLD_CURRENTLY"

ENTRY_READY_RECS = frozenset({"ALLOW", "REDUCE"})


def normalize_recommendation(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def is_entry_ready_recommendation(value: Any) -> bool:
    return normalize_recommendation(value) in ENTRY_READY_RECS


def recommendation_changed(
    previous: Any, current: Any
) -> bool:
    prev = normalize_recommendation(previous)
    curr = normalize_recommendation(current)
    if curr is None:
        return False
    return prev != curr


def should_notify_recommendation_change(
    previous: Any, current: Any
) -> bool:
    """HOLD→HOLD 등 동일 반복은 알림 없음. 실제 변화만."""

    if not recommendation_changed(previous, current):
        return False
    # ALLOW/REDUCE로 바뀌거나, ALLOW/REDUCE에서 이탈할 때도 운영 인지
    return (
        is_entry_ready_recommendation(current)
        or is_entry_ready_recommendation(previous)
    )


def evaluate_ai_ready_for_live_preflight(
    *,
    recommendation: Any,
    fresh: bool,
    analysis_status: str | None,
    market_feed_ok: bool,
    activation_ok: bool,
) -> dict[str, Any]:
    """ALLOW/REDUCE + 인프라 조건 → AI_READY_FOR_LIVE_PREFLIGHT.

    LIVE/ARM을 켜지 않는다. 판정/표시만.
    Feed/Activation 차단은 entry-ready(ALLOW/REDUCE)일 때만 적용.
    """

    rec = normalize_recommendation(recommendation)
    status_u = str(analysis_status or "").strip().upper()
    validated = status_u in {
        "VALIDATED_ANALYSIS",
        "VALIDATED_WITH_WARNINGS",
    }

    if not validated or rec is None:
        return {
            "status": STATUS_BLOCKED_MISSING,
            "ready": False,
            "recommendation": rec,
            "blockers": ["AI_MISSING_OR_INVALID"],
            "live_auto_start": False,
            "note": "operator approval required; no LIVE/ARM auto change",
        }

    if not fresh:
        return {
            "status": STATUS_BLOCKED_STALE,
            "ready": False,
            "recommendation": rec,
            "blockers": ["AI_STALE"],
            "live_auto_start": False,
            "note": "operator approval required; no LIVE/ARM auto change",
        }

    if rec not in ENTRY_READY_RECS:
        return {
            "status": STATUS_HOLD if rec == "HOLD" else STATUS_WAITING_HOLD,
            "ready": False,
            "recommendation": rec,
            "blockers": [],
            "live_auto_start": False,
            "note": "waiting for ALLOW/REDUCE; scheduler continues",
        }

    # ALLOW / REDUCE — Feed·Activation 필수
    blockers: list[str] = []
    if not market_feed_ok:
        blockers.append("MARKET_FEED_UNHEALTHY")
    if not activation_ok:
        blockers.append("ACTIVATION_NOT_ACTIVE")
    if blockers:
        if "MARKET_FEED_UNHEALTHY" in blockers:
            status = STATUS_BLOCKED_FEED
        else:
            status = STATUS_BLOCKED_ACTIVATION
        return {
            "status": status,
            "ready": False,
            "recommendation": rec,
            "blockers": blockers,
            "live_auto_start": False,
            "note": "operator approval required; no LIVE/ARM auto change",
        }

    return {
        "status": STATUS_READY,
        "ready": True,
        "recommendation": rec,
        "blockers": [],
        "live_auto_start": False,
        "note": "AI ready for Final LIVE Preflight; do not auto-start LIVE",
    }


def emit_recommendation_changed(
    session: Session,
    *,
    previous: str | None,
    current: str,
    user_broker_account_id: int | None,
    strategy_id: int | None,
    symbol: str,
    analysis_id: int | None,
    trend: str | None,
    momentum: str | None,
    volatility: str | None,
    confidence: Any,
    analysis_at: str | None,
    preflight_status: str,
) -> dict[str, Any]:
    """Audit + Notification. LIVE 상태 변경 없음."""

    if not should_notify_recommendation_change(previous, current):
        return {
            "emitted": False,
            "reason": "NO_CHANGE_OR_HOLD_REPEAT",
        }

    detail = {
        "user_broker_account_id": user_broker_account_id,
        "strategy_id": strategy_id,
        "symbol": str(symbol).upper(),
        "previous_recommendation": normalize_recommendation(previous),
        "new_recommendation": normalize_recommendation(current),
        "analysis_id": analysis_id,
        "trend": trend,
        "momentum": momentum,
        "volatility": volatility,
        "confidence": confidence,
        "analysis_at": analysis_at,
        "preflight_status": preflight_status,
        "live_auto_start": False,
    }

    try:
        from stock_platform.order.live_safety_audit import (
            emit_live_safety_audit,
        )

        emit_live_safety_audit(
            session,
            event_type=EVENT_RECOMMENDATION_CHANGED,
            actor="job:upbit-autotrading-ai-analysis",
            run_id=None,
            user_id=None,
            account_id=user_broker_account_id,
            strategy_id=str(strategy_id) if strategy_id else None,
            symbol=str(symbol).upper(),
            detail=detail,
            commit=False,
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning(
            "ai_gate_recommendation_audit_failed",
            error=type(exc).__name__,
        )

    try:
        from stock_platform.notification.events import (
            NotificationEventType,
        )
        from stock_platform.notification.publisher import (
            notification_publisher,
        )

        title = "AI Gate recommendation changed"
        message = (
            f"{symbol.upper()} {normalize_recommendation(previous) or 'NONE'}"
            f" → {normalize_recommendation(current)} "
            f"({preflight_status})"
        )
        notification_publisher.publish(
            event_type=str(
                getattr(
                    NotificationEventType,
                    "AI_GATE_RECOMMENDATION_CHANGED",
                    EVENT_RECOMMENDATION_CHANGED,
                )
            ),
            title=title,
            message=message,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ai_gate_recommendation_notify_failed",
            error=type(exc).__name__,
        )

    logger.info(
        "ai_gate_recommendation_changed",
        previous=normalize_recommendation(previous),
        current=normalize_recommendation(current),
        analysis_id=analysis_id,
        preflight_status=preflight_status,
        uba=user_broker_account_id,
    )
    return {"emitted": True, "detail": detail}


def resolve_watch_scope(
    session: Session,
    *,
    symbol: str,
) -> dict[str, Any]:
    """활성 UPBIT strategy link에서 UBA/strategy 해석 (없으면 settings)."""

    from stock_platform.common.settings import get_settings
    from stock_platform.strategy_deployment.definition_entities import (
        AccountStrategyLinkEntity,
        StrategyDefinitionEntity,
    )
    from stock_platform.trading.account_models import UserBrokerAccount
    from sqlalchemy import select

    settings = get_settings()
    uba_id = int(
        getattr(settings, "realtime_live_user_broker_account_id", 0) or 0
    )
    strategy_id: int | None = None
    sym = symbol.upper()

    try:
        links = list(
            session.scalars(
                select(AccountStrategyLinkEntity).where(
                    AccountStrategyLinkEntity.is_active.is_(True),
                )
            )
        )
        for link in links:
            uba = session.get(
                UserBrokerAccount, int(link.user_broker_account_id)
            )
            if uba is None or str(uba.broker_code or "").upper() != "UPBIT":
                continue
            if not bool(uba.is_active) or getattr(uba, "deleted_at", None):
                continue
            strategy = session.get(
                StrategyDefinitionEntity, int(link.strategy_id)
            )
            if strategy is None:
                continue
            payload = getattr(strategy, "parameter_payload", None) or {}
            if not isinstance(payload, dict):
                payload = {}
            hint = str(
                payload.get("symbol") or payload.get("market") or ""
            ).strip().upper()
            if hint and hint != sym:
                continue
            uba_id = int(uba.user_broker_account_id)
            strategy_id = int(strategy.strategy_id)
            break
    except Exception:  # noqa: BLE001
        pass

    return {
        "user_broker_account_id": uba_id or None,
        "strategy_id": strategy_id,
        "symbol": sym,
    }


def snapshot_ai_live_preflight_for_uba(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    ai_snap: dict[str, Any] | None,
    market_feed_ok: bool,
    activation_ok: bool,
) -> dict[str, Any]:
    """Readiness용 조회 전용 스냅샷."""

    latest = (ai_snap or {}).get("latest") or {}
    rec = latest.get("recommendation") or (ai_snap or {}).get(
        "recommendation"
    )
    fresh = not bool((ai_snap or {}).get("stale", True))
    if "fresh" in (ai_snap or {}) and isinstance(ai_snap.get("fresh"), bool):
        fresh = bool(ai_snap.get("fresh"))
    # gate snap uses stale flag; latest may be nested
    if latest:
        # age/stale from parent snap preferred
        fresh = not bool((ai_snap or {}).get("stale", True))

    evaluated = evaluate_ai_ready_for_live_preflight(
        recommendation=rec,
        fresh=fresh,
        analysis_status=latest.get("analysis_status"),
        market_feed_ok=bool(market_feed_ok),
        activation_ok=bool(activation_ok),
    )
    return {
        **evaluated,
        "user_broker_account_id": int(user_broker_account_id),
        "symbol": str(symbol).upper(),
        "analysis_id": latest.get("market_analysis_id"),
        "analysis_at": latest.get("analysis_at"),
        "trend": latest.get("trend"),
        "momentum": latest.get("momentum"),
        "volatility": latest.get("volatility"),
        "confidence": latest.get("confidence"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "orders_created": 0,
        "live_changed": False,
        "arm_changed": False,
    }
