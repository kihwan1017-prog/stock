"""Telegram market routing + ANALYSIS suppression policy.

Telegram output만 제어한다. Scanner/LLM/RAG/Trading 경로는 변경하지 않는다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

KST = ZoneInfo("Asia/Seoul")

# edge-trigger 상태 (프로세스 로컬 — restart 후 동일 상태면 1회 재발 가능, Dedup TTL로 완화)
_EDGE_STATE: dict[str, str] = {}
_EDGE_LOCK = threading.Lock()


class TelegramMarket(StrEnum):
    UPBIT = "UPBIT"
    KIWOOM = "KIWOOM"
    COMMON = "COMMON"


class TelegramCategory(StrEnum):
    SYSTEM = "SYSTEM"
    TRADING = "TRADING"
    ANALYSIS = "ANALYSIS"
    CRITICAL = "CRITICAL"


# event_type → category (기존 event rename 금지, mapping only)
_ANALYSIS_EVENTS = frozenset(
    {
        "AI_ANALYSIS_COMPLETE",
        "AI_GATE_RECOMMENDATION_CHANGED",
        "AI_TIMEOUT",
        "UPBIT_SCANNER_CANDIDATE",
        "UPBIT_SCANNER_SHADOW_OPENED",
        "UPBIT_SCANNER_SHADOW_RESULT",
        "UPBIT_PORTFOLIO_SLOT_ASSIGNED",
        "UPBIT_PORTFOLIO_CANDIDATE_REPLACED",
        "UPBIT_SHADOW_EVALUATION_MISMATCH",
        "UPBIT_SHADOW_COHORT_30_REVIEW_READY",
        "BACKTEST_COMPLETE",
    }
)

_TRADING_EVENTS = frozenset(
    {
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "ORDER_PARTIAL_FILLED",
        "ORDER_CANCELLED",
        "ORDER_REJECTED",
        "STOP_LOSS",
        "TAKE_PROFIT",
        "TRAILING_STOP",
        "RELATIVE_LOSS",
        "POSITION_CLOSED",
        "REALIZED_PNL",
        "PORTFOLIO_BULLISH_STATE_ENTRY",
        "LIVE_ORDER_SUBMITTED",
        "MA_EXIT",
        "MA_DEAD_CROSS",
        "MA_DEAD_CROSS_EXIT",
    }
)

_CRITICAL_EVENTS = frozenset(
    {
        "KILL_SWITCH",
        "DAILY_LOSS",
        "BROKER_DISCONNECTED",
        "BROKER_TIMEOUT",
        "DATABASE_ERROR",
        "SCHEDULER_ERROR",
        "RECOVERY_FAILED",
        "SUBMISSION_UNKNOWN",
        "RECONCILIATION_MISMATCH",
        "UPBIT_SCANNER_FAILURE",  # feed/scan failure는 CRITICAL 취급 가능하나 WARN — keep CRITICAL for safety alerts
        "POST_FILL_MISMATCH",
        "POST_FILL_VERIFY_FAILED",
        "POST_FILL_VERIFY_EXPIRED",
        "POSITION_MISMATCH",
        "CASH_MISMATCH",
        "LOOP_DETECTED",
        "ANOMALY_ORDER_RATE",
    }
)


@dataclass(frozen=True, slots=True)
class TelegramDecision:
    allowed: bool
    reason: str
    market: str
    category: str
    chat_route: str  # UPBIT | KIWOOM | FALLBACK


def map_telegram_category(event_type: str) -> TelegramCategory:
    et = str(event_type or "").strip().upper()
    if et in _CRITICAL_EVENTS or et.endswith("_CRITICAL"):
        return TelegramCategory.CRITICAL
    if et in _ANALYSIS_EVENTS:
        return TelegramCategory.ANALYSIS
    if et in _TRADING_EVENTS:
        return TelegramCategory.TRADING
    # MONITORING / LIVE / ARM / lifecycle → SYSTEM
    return TelegramCategory.SYSTEM


def resolve_telegram_market(
    *,
    event_type: str,
    detail: dict[str, Any] | None,
) -> TelegramMarket:
    """detail/broker/event prefix로 시장 추론."""

    d = detail or {}
    explicit = str(
        d.get("telegram_market")
        or d.get("market")
        or d.get("broker_code")
        or d.get("market_code")
        or ""
    ).strip().upper()
    if explicit in {"UPBIT", "CRYPTO"}:
        return TelegramMarket.UPBIT
    if explicit in {"KIWOOM", "KRX", "STOCK"}:
        return TelegramMarket.KIWOOM

    et = str(event_type or "").upper()
    if et.startswith("UPBIT_") or "UPBIT" in et:
        return TelegramMarket.UPBIT
    if et.startswith("KIWOOM_") or "KIWOOM" in et or "KRX" in et:
        return TelegramMarket.KIWOOM

    # UBA id 힌트 (운영 관례: 1380 UPBIT / 1381 KIWOOM — 하드코딩 의존 최소화)
    uba = d.get("user_broker_account_id") or d.get("uba_id") or d.get("account_id")
    if uba is not None:
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.trading.account_models import UserBrokerAccount

            session = get_session_factory()()
            try:
                row = session.get(UserBrokerAccount, int(uba))
                bc = str(getattr(row, "broker_code", "") or "").upper()
                if bc == "UPBIT":
                    return TelegramMarket.UPBIT
                if bc == "KIWOOM":
                    return TelegramMarket.KIWOOM
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            pass

    return TelegramMarket.COMMON


def resolve_telegram_chat_id(market: TelegramMarket | str) -> tuple[str, str]:
    """(chat_id, route_label). secret 원문은 호출측에서 마스킹."""

    from stock_platform.common.settings import get_settings

    settings = get_settings()
    fallback = str(settings.telegram_chat_id or "").strip()
    upbit = str(getattr(settings, "telegram_upbit_chat_id", "") or "").strip()
    kiwoom = str(getattr(settings, "telegram_kiwoom_chat_id", "") or "").strip()
    m = str(market or "").upper()
    if m == TelegramMarket.UPBIT.value:
        if upbit:
            return upbit, "UPBIT"
        return fallback, "FALLBACK"
    if m == TelegramMarket.KIWOOM.value:
        if kiwoom:
            return kiwoom, "KIWOOM"
        return fallback, "FALLBACK"
    return fallback, "FALLBACK"


def mask_chat_id(chat_id: str) -> str | None:
    raw = str(chat_id or "").strip()
    if not raw:
        return None
    if len(raw) <= 4:
        return "****"
    return f"{raw[:2]}…{raw[-2:]}"


def _upbit_daily_usage(session: Session, uba_id: int | None) -> dict[str, Any]:
    from stock_platform.operation.upbit_full_market.constants import (
        DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
    )
    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
        resolve_portfolio_daily_entry_limit,
    )
    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
        summarize_portfolio_daily_entries,
    )

    uid = int(uba_id) if uba_id is not None else 1380
    try:
        limit = resolve_portfolio_daily_entry_limit(session, uid)
    except Exception:  # noqa: BLE001
        limit = int(DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT)
    return summarize_portfolio_daily_entries(
        session, uid, daily_limit=limit
    )


def _kiwoom_trading_ready(
    session: Session, uba_id: int | None
) -> tuple[bool, str | None, dict[str, Any]]:
    """장중 + LIVE/ARM/Activation/Runtime 대략 SoT."""

    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        PHASE_TRADING,
        KiwoomTradingDayLifecycleService,
    )

    uid = int(uba_id) if uba_id is not None else 1381
    snap: dict[str, Any] = {"uba_id": uid}
    try:
        life = KiwoomTradingDayLifecycleService(session).status_dict(uid)
        snap.update(
            {
                "lifecycle_phase": life.get("lifecycle_phase"),
                "live": life.get("live"),
                "arm": life.get("arm"),
                "is_trading_day": life.get("is_trading_day"),
                "market_session": life.get("market_session"),
                "active_lease_status": life.get("active_lease_status"),
            }
        )
        phase = str(life.get("lifecycle_phase") or "").upper()
        if phase != PHASE_TRADING:
            return False, "MARKET_CLOSED", snap
        if not life.get("is_trading_day"):
            return False, "NOT_TRADING_DAY", snap
        if str(life.get("market_session") or "").upper() not in {
            "OPEN",
            "REGULAR",
            "TRADING",
        }:
            # some payloads use session type
            mh = life.get("market") or {}
            if not (mh.get("in_regular_session") is True):
                if str(life.get("market_session") or "").upper() != "OPEN":
                    return False, "MARKET_CLOSED", snap
        if not life.get("live"):
            return False, "LIVE_OFF", snap
        if not life.get("arm"):
            return False, "ARM_OFF", snap
        if str(life.get("active_lease_status") or "").upper() != "ACTIVE":
            # activation via lease
            pass
        # runtime
        try:
            from stock_platform.trading.upbit_24x7_control import (
                runtime_status_for_uba,
            )

            rt = runtime_status_for_uba(
                user_broker_account_id=uid, broker_code="KIWOOM"
            )
            snap["runtime"] = rt.get("status")
            if str(rt.get("status") or "").upper() != "RUNNING":
                return False, "RUNTIME_STOPPED", snap
        except Exception:  # noqa: BLE001
            snap["runtime"] = "UNKNOWN"
        return True, None, snap
    except Exception as exc:  # noqa: BLE001
        return False, f"KIWOOM_STATUS_ERROR:{type(exc).__name__}", snap


def evaluate_telegram_policy(
    *,
    event_type: str,
    detail: dict[str, Any] | None = None,
    session: Session | None = None,
) -> TelegramDecision:
    """중앙 Telegram allow/suppress 판정."""

    d = dict(detail or {})
    market = resolve_telegram_market(event_type=event_type, detail=d)
    category = map_telegram_category(event_type)
    _, route = resolve_telegram_chat_id(market)

    # CRITICAL / TRADING / SYSTEM — ANALYSIS suppress와 무관하게 허용
    if category in {
        TelegramCategory.CRITICAL,
        TelegramCategory.TRADING,
        TelegramCategory.SYSTEM,
    }:
        return TelegramDecision(
            allowed=True,
            reason="CATEGORY_ALWAYS",
            market=market.value,
            category=category.value,
            chat_route=route,
        )

    # ANALYSIS only below
    owns_session = False
    sess = session
    if sess is None:
        try:
            from stock_platform.database.session import get_session_factory

            sess = get_session_factory()()
            owns_session = True
        except Exception:  # noqa: BLE001
            return TelegramDecision(
                allowed=True,
                reason="POLICY_SESSION_UNAVAILABLE_FAIL_OPEN",
                market=market.value,
                category=category.value,
                chat_route=route,
            )

    try:
        uba = d.get("user_broker_account_id") or d.get("uba_id")
        if market == TelegramMarket.UPBIT:
            usage = _upbit_daily_usage(sess, int(uba) if uba is not None else None)
            if bool(usage.get("blocking")) or int(usage.get("entry_count") or 0) >= int(
                usage.get("entry_limit") or 10
            ):
                return TelegramDecision(
                    allowed=False,
                    reason="DAILY_ENTRY_LIMIT_REACHED",
                    market=market.value,
                    category=category.value,
                    chat_route=route,
                )
            return TelegramDecision(
                allowed=True,
                reason="UPBIT_ENTRY_AVAILABLE",
                market=market.value,
                category=category.value,
                chat_route=route,
            )

        if market == TelegramMarket.KIWOOM:
            ok, reason, _snap = _kiwoom_trading_ready(
                sess, int(uba) if uba is not None else None
            )
            if not ok:
                return TelegramDecision(
                    allowed=False,
                    reason=reason or "KIWOOM_NOT_READY",
                    market=market.value,
                    category=category.value,
                    chat_route=route,
                )
            return TelegramDecision(
                allowed=True,
                reason="KIWOOM_TRADING_READY",
                market=market.value,
                category=category.value,
                chat_route=route,
            )

        # COMMON ANALYSIS — suppress 보수적으로 허용하지 않음? fail-open for ops
        return TelegramDecision(
            allowed=True,
            reason="COMMON_ANALYSIS_FAIL_OPEN",
            market=market.value,
            category=category.value,
            chat_route=route,
        )
    finally:
        if owns_session and sess is not None:
            sess.close()


def _edge_key(market: str, name: str) -> str:
    day = datetime.now(KST).date().isoformat()
    return f"{market}|{name}|{day}"


def maybe_emit_upbit_daily_limit_edge(
    *,
    usage: dict[str, Any],
    uba_id: int = 1380,
) -> str | None:
    """AVAILABLE↔DAILY_LIMIT_REACHED edge SYSTEM 1회."""

    blocking = bool(usage.get("blocking"))
    count = int(usage.get("entry_count") or 0)
    limit = int(usage.get("entry_limit") or 10)
    key = _edge_key("UPBIT", "DAILY_LIMIT")
    with _EDGE_LOCK:
        prev = _EDGE_STATE.get(key)
        if blocking:
            if prev == "REACHED":
                return None
            _EDGE_STATE[key] = "REACHED"
            event = "REACHED"
        else:
            if prev != "REACHED":
                # never reached today — or already AVAILABLE
                if prev == "AVAILABLE":
                    return None
                _EDGE_STATE[key] = "AVAILABLE"
                return None
            _EDGE_STATE[key] = "AVAILABLE"
            event = "AVAILABLE"

    try:
        from stock_platform.notification.publisher import notification_publisher

        if event == "REACHED":
            notification_publisher.publish(
                event_type="MONITORING_ALERT",
                title="[UPBIT][SYSTEM] 일일 신규진입 한도",
                message=(
                    "일일 신규진입 한도에 도달했습니다.\n"
                    "신규 매수 분석 알림을 중지합니다.\n"
                    "기존 포지션 청산 감시는 계속됩니다.\n"
                    f"현재: {count}/{limit}"
                ),
                detail={
                    "telegram_market": "UPBIT",
                    "broker_code": "UPBIT",
                    "user_broker_account_id": int(uba_id),
                    "kind": "DAILY_LIMIT_REACHED",
                    "entry_count": count,
                    "entry_limit": limit,
                },
            )
            return "DAILY_LIMIT_REACHED"
        notification_publisher.publish(
            event_type="MONITORING_ALERT",
            title="[UPBIT][SYSTEM] 일일 한도 갱신",
            message=(
                "일일 신규진입 한도가 갱신되었습니다.\n"
                "자동매매 분석 알림을 재개합니다.\n"
                f"현재: {count}/{limit}"
            ),
            detail={
                "telegram_market": "UPBIT",
                "broker_code": "UPBIT",
                "user_broker_account_id": int(uba_id),
                "kind": "DAILY_LIMIT_AVAILABLE",
                "entry_count": count,
                "entry_limit": limit,
            },
        )
        return "DAILY_LIMIT_AVAILABLE"
    except Exception:  # noqa: BLE001
        return None


def maybe_emit_kiwoom_market_edge(
    *,
    ready: bool,
    uba_id: int = 1381,
    context: dict[str, Any] | None = None,
) -> str | None:
    """MARKET_OPEN_AND_READY ↔ MARKET_CLOSED edge SYSTEM 1회."""

    key = _edge_key("KIWOOM", "MARKET")
    with _EDGE_LOCK:
        prev = _EDGE_STATE.get(key)
        state = "OPEN_READY" if ready else "CLOSED"
        if prev == state:
            return None
        _EDGE_STATE[key] = state

    try:
        from stock_platform.notification.publisher import notification_publisher

        ctx = context or {}
        if ready:
            notification_publisher.publish(
                event_type="MONITORING_ALERT",
                title="[KIWOOM][SYSTEM] 정규장 자동매매 시작",
                message=(
                    "정규장 자동매매가 시작되었습니다.\n"
                    "분석 알림을 재개합니다."
                ),
                detail={
                    "telegram_market": "KIWOOM",
                    "broker_code": "KIWOOM",
                    "user_broker_account_id": int(uba_id),
                    "kind": "MARKET_OPEN_AND_READY",
                    **{k: ctx.get(k) for k in ("lifecycle_phase", "runtime") if k in ctx},
                },
            )
            return "MARKET_OPEN_AND_READY"
        notification_publisher.publish(
            event_type="MONITORING_ALERT",
            title="[KIWOOM][SYSTEM] 정규장 종료",
            message=(
                "정규장이 종료되었습니다.\n"
                "분석 알림을 중지합니다.\n"
                "시스템/장애 알림은 계속됩니다."
            ),
            detail={
                "telegram_market": "KIWOOM",
                "broker_code": "KIWOOM",
                "user_broker_account_id": int(uba_id),
                "kind": "MARKET_CLOSED",
                **{k: ctx.get(k) for k in ("lifecycle_phase", "runtime") if k in ctx},
            },
        )
        return "MARKET_CLOSED"
    except Exception:  # noqa: BLE001
        return None


def build_telegram_routing_status(
    session: Session | None = None,
) -> dict[str, Any]:
    """READ ONLY status (secrets masked)."""

    from stock_platform.common.settings import get_settings

    settings = get_settings()
    owns = False
    sess = session
    if sess is None:
        from stock_platform.database.session import get_session_factory

        sess = get_session_factory()()
        owns = True
    try:
        upbit_usage = _upbit_daily_usage(sess, 1380)
        upbit_analysis_ok = not bool(upbit_usage.get("blocking"))
        kiwoom_ok, kiwoom_reason, kiwoom_snap = _kiwoom_trading_ready(sess, 1381)
        upbit_chat, upbit_route = resolve_telegram_chat_id(TelegramMarket.UPBIT)
        kiwoom_chat, kiwoom_route = resolve_telegram_chat_id(TelegramMarket.KIWOOM)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bot_configured": bool(
                settings.telegram_enabled and settings.telegram_bot_token
            ),
            "fallback_chat_configured": bool(str(settings.telegram_chat_id or "").strip()),
            "upbit": {
                "configured": bool(upbit_chat),
                "chat_id_masked": mask_chat_id(upbit_chat),
                "route": upbit_route,
                "analysis_allowed": upbit_analysis_ok,
                "suppression_reason": (
                    None if upbit_analysis_ok else "DAILY_ENTRY_LIMIT_REACHED"
                ),
                "daily_entry": {
                    "count": upbit_usage.get("entry_count"),
                    "limit": upbit_usage.get("entry_limit"),
                    "blocking": upbit_usage.get("blocking"),
                },
                "system_allowed": True,
                "trading_allowed": True,
                "critical_allowed": True,
            },
            "kiwoom": {
                "configured": bool(kiwoom_chat),
                "chat_id_masked": mask_chat_id(kiwoom_chat),
                "route": kiwoom_route,
                "analysis_allowed": kiwoom_ok,
                "suppression_reason": None if kiwoom_ok else kiwoom_reason,
                "snapshot": {
                    k: kiwoom_snap.get(k)
                    for k in (
                        "lifecycle_phase",
                        "live",
                        "arm",
                        "market_session",
                        "runtime",
                        "is_trading_day",
                    )
                },
                "system_allowed": True,
                "critical_allowed": True,
            },
        }
    finally:
        if owns and sess is not None:
            sess.close()
