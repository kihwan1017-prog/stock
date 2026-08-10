"""MA Signal → AI Context Gate → Risk/OES.

LLM/Market Analysis는 보조 판단만 수행한다.
BUY/SELL 생성·Risk 한도 확대·LIVE/ARM 우회 금지.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.realtime.ai_signal_gate_models import (
    AiSignalGateDecision,
    AiSignalGateResult,
)
from stock_platform.realtime.ai_signal_gate_policy import (
    is_ai_signal_gate_active,
)
from stock_platform.realtime.strategy_models import RealtimeSignal


logger = structlog.get_logger(__name__)

# fingerprint → 최근 gate 결과 (프로세스 메모리)
_GATE_CACHE: dict[str, tuple[datetime, AiSignalGateResult]] = {}
_MAX_CACHE = 2000

_ZERO = Decimal("0")
_ONE = Decimal("1")


def clear_ai_signal_gate_cache_for_tests() -> None:
    _GATE_CACHE.clear()


def evaluate_ai_signal_gate(
    session: Session,
    signal: RealtimeSignal,
    *,
    environment: str,
    now: datetime | None = None,
) -> AiSignalGateResult:
    """신호에 대한 AI Gate 판정.

    Paper/Shadow Gate ON, LIVE Gate 기본 OFF.
    LIVE + fail_closed + unavailable/stale → HOLD.
    SELL도 Gate를 통과하되 수량 상한은 executor 보유량 clip.
    """

    settings = get_settings()
    if not is_ai_signal_gate_active(environment, settings=settings):
        return AiSignalGateResult(
            decision=AiSignalGateDecision.ALLOW,
            confidence=_ONE,
            reason_code="AI_GATE_DISABLED",
            summary="AI signal gate off for this environment",
        )

    # Paper scope는 broker_code=PAPER 이지만 exchange=UPBIT 시세/전략을 씀.
    # Gate는 브로커 라벨이 아니라 UPBIT/CRYPTO 시장 신호에 적용한다.
    broker = str(
        getattr(signal, "broker_code", None) or ""
    ).upper()
    exchange = str(signal.exchange_code or "").upper()
    market_type = str(getattr(signal, "market_type", None) or "").upper()
    upbit_like = (
        broker in {"UPBIT", "CRYPTO"}
        or exchange in {"UPBIT", "CRYPTO"}
        or market_type in {"CRYPTO", "UPBIT"}
    )
    if not upbit_like:
        return AiSignalGateResult(
            decision=AiSignalGateDecision.ALLOW,
            confidence=_ONE,
            reason_code="AI_GATE_BROKER_SKIP",
            summary="Non-UPBIT broker skipped by AI gate",
        )

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    fp = str(getattr(signal, "fingerprint", "") or "").strip()
    ttl = float(
        getattr(settings, "autotrading_ai_analysis_ttl_seconds", 900.0) or 900.0
    )
    if fp and fp in _GATE_CACHE:
        cached_at, cached = _GATE_CACHE[fp]
        age = (now_utc - cached_at).total_seconds()
        if age <= ttl:
            return cached

    live_fail_closed = bool(
        getattr(settings, "autotrading_ai_live_fail_closed", True)
    )
    min_conf = Decimal(
        str(getattr(settings, "autotrading_ai_min_confidence", 0.4) or 0.4)
    )
    reduce_ratio = Decimal(
        str(getattr(settings, "autotrading_ai_reduce_ratio", 0.5) or 0.5)
    )
    if reduce_ratio <= _ZERO or reduce_ratio > _ONE:
        reduce_ratio = Decimal("0.5")

    try:
        analysis = _load_latest_analysis(
            session,
            exchange_code=str(signal.exchange_code or "UPBIT").upper(),
            symbol=str(signal.symbol or "").upper(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ai_signal_gate_load_failed",
            error=type(exc).__name__,
            symbol=getattr(signal, "symbol", None),
        )
        return _unavailable(
            environment=environment,
            live_fail_closed=live_fail_closed,
            reason="AI_ANALYSIS_LOAD_FAILED",
            summary=f"analysis load failed: {type(exc).__name__}",
        )

    if analysis is None:
        return _unavailable(
            environment=environment,
            live_fail_closed=live_fail_closed,
            reason="AI_ANALYSIS_MISSING",
            summary="no validated market analysis for symbol",
        )

    analysis_at = analysis.get("analysis_at")
    age_sec: float | None = None
    stale = False
    if isinstance(analysis_at, datetime):
        at = analysis_at
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        age_sec = max(0.0, (now_utc - at.astimezone(timezone.utc)).total_seconds())
        stale = age_sec > ttl

    if stale:
        result = AiSignalGateResult(
            decision=AiSignalGateDecision.HOLD,
            confidence=_ZERO,
            reason_code="AI_ANALYSIS_STALE",
            summary="AI analysis older than TTL — LIVE orders blocked",
            analysis_at=analysis_at if isinstance(analysis_at, datetime) else None,
            age_seconds=age_sec,
            stale=True,
            provider=analysis.get("provider"),
            model=analysis.get("model"),
            market_analysis_id=analysis.get("market_analysis_id"),
            recommendation=analysis.get("recommendation"),
            risk_level=analysis.get("risk_level"),
            news_sentiment=analysis.get("news_sentiment"),
        )
        _store_cache(fp, now_utc, result)
        return result

    conf = _as_decimal(analysis.get("confidence"), default=_ZERO)
    decision = _map_recommendation(
        analysis.get("recommendation"),
        confidence=conf,
        min_confidence=min_conf,
        risk_level=analysis.get("risk_level"),
    )
    size_mult = _ONE
    if decision == AiSignalGateDecision.REDUCE:
        size_mult = reduce_ratio

    # malformed / empty recommendation under LIVE → HOLD
    if (
        str(environment).upper() == "LIVE"
        and live_fail_closed
        and decision == AiSignalGateDecision.ALLOW
        and not str(analysis.get("recommendation") or "").strip()
        and conf < min_conf
    ):
        decision = AiSignalGateDecision.HOLD

    result = AiSignalGateResult(
        decision=decision,
        confidence=conf,
        reason_code=f"AI_GATE_{decision.value}",
        summary=str(analysis.get("summary") or "")[:500],
        risk_level=analysis.get("risk_level"),
        news_sentiment=analysis.get("news_sentiment"),
        recommendation=analysis.get("recommendation"),
        analysis_at=analysis_at if isinstance(analysis_at, datetime) else None,
        age_seconds=age_sec,
        stale=False,
        provider=analysis.get("provider"),
        model=analysis.get("model"),
        market_analysis_id=analysis.get("market_analysis_id"),
        size_multiplier=size_mult,
        detail={
            "trend": analysis.get("trend"),
            "momentum": analysis.get("momentum"),
            "volatility": analysis.get("volatility"),
        },
    )
    _store_cache(fp, now_utc, result)
    return result


def snapshot_ai_signal_gate_status(
    session: Session,
    *,
    exchange_code: str = "UPBIT",
    symbol: str = "KRW-XRP",
) -> dict[str, Any]:
    """Admin readiness용 AI Gate 상태 스냅샷 (조회 전용)."""

    settings = get_settings()
    enabled = bool(
        getattr(settings, "autotrading_ai_signal_gate_enabled", False)
    )
    live_enabled = bool(
        getattr(settings, "autotrading_ai_signal_gate_live_enabled", False)
    )
    shadow_enabled = bool(
        getattr(settings, "autotrading_ai_signal_gate_shadow_enabled", True)
    )
    ttl = float(
        getattr(settings, "autotrading_ai_analysis_ttl_seconds", 900.0) or 900.0
    )
    analysis = None
    try:
        analysis = _load_latest_analysis(
            session,
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": enabled,
            "live_enabled": live_enabled,
            "shadow_enabled": shadow_enabled,
            "paper_active": enabled,
            "ok": False,
            "error": type(exc).__name__,
            "ttl_seconds": ttl,
            "provider_policy": "ollama_preferred_mock_for_tests",
            "live_fail_closed": bool(
                getattr(settings, "autotrading_ai_live_fail_closed", True)
            ),
        }

    now = datetime.now(timezone.utc)
    age = None
    stale = True
    if analysis and isinstance(analysis.get("analysis_at"), datetime):
        at = analysis["analysis_at"]
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - at.astimezone(timezone.utc)).total_seconds())
        stale = age > ttl

    return {
        "enabled": enabled,
        "live_enabled": live_enabled,
        "shadow_enabled": shadow_enabled,
        "paper_active": enabled,
        "ok": bool(analysis) and not stale,
        "ttl_seconds": ttl,
        "live_fail_closed": bool(
            getattr(settings, "autotrading_ai_live_fail_closed", True)
        ),
        "min_confidence": str(
            getattr(settings, "autotrading_ai_min_confidence", 0.4)
        ),
        "reduce_ratio": str(
            getattr(settings, "autotrading_ai_reduce_ratio", 0.5)
        ),
        "latest": analysis,
        "age_seconds": age,
        "stale": stale if analysis else True,
        "policy": {
            "paper_mock": "gate when enabled",
            "shadow": "gate when shadow_enabled",
            "live": "gate only when live_enabled (default OFF)",
            "allow": "continue to Risk/OES",
            "hold": "no order",
            "reduce": "scale order_amount within policy",
            "sell": "gate applies; quantity clipped to holdings",
            "llm_cannot": [
                "create BUY/SELL alone",
                "raise risk limits",
                "bypass LIVE/ARM/Kill",
                "sell above holdings",
            ],
        },
    }


def _unavailable(
    *,
    environment: str,
    live_fail_closed: bool,
    reason: str,
    summary: str,
) -> AiSignalGateResult:
    if str(environment).upper() == "LIVE" and live_fail_closed:
        return AiSignalGateResult(
            decision=AiSignalGateDecision.HOLD,
            confidence=_ZERO,
            reason_code=reason,
            summary=summary,
        )
    # Paper/Shadow — Strategy-only fallback
    return AiSignalGateResult(
        decision=AiSignalGateDecision.ALLOW,
        confidence=_ZERO,
        reason_code=f"{reason}_FALLBACK_ALLOW",
        summary=f"{summary} (non-LIVE fallback ALLOW)",
    )


def _load_latest_analysis(
    session: Session,
    *,
    exchange_code: str,
    symbol: str,
) -> dict[str, Any] | None:
    from stock_platform.ai.market_analysis.entities import (
        AIMarketAnalysisEntity,
    )

    row = session.scalars(
        select(AIMarketAnalysisEntity)
        .where(
            AIMarketAnalysisEntity.exchange_code == exchange_code,
            AIMarketAnalysisEntity.symbol == symbol,
            AIMarketAnalysisEntity.analysis_status.in_(
                (
                    "VALIDATED_ANALYSIS",
                    "VALIDATED_WITH_WARNINGS",
                )
            ),
        )
        .order_by(
            desc(AIMarketAnalysisEntity.analyzed_at),
            desc(AIMarketAnalysisEntity.market_analysis_id),
        )
        .limit(1)
    ).first()
    if row is None:
        return None

    # Safe Result only — result_payload 원문 사용 금지
    payload = dict(getattr(row, "safe_result", None) or {})
    recommendation = (
        payload.get("recommendation")
        or payload.get("action")
        or payload.get("gate_decision")
        or payload.get("suggested_action")
    )
    confidence = payload.get("confidence")
    if confidence is None:
        confidence = getattr(row, "confidence", None)

    analysis_at = (
        getattr(row, "analyzed_at", None)
        or getattr(row, "snapshot_at", None)
        or getattr(row, "updated_at", None)
        or getattr(row, "created_at", None)
    )
    return {
        "market_analysis_id": int(row.market_analysis_id),
        "symbol": row.symbol,
        "analysis_at": analysis_at,
        "recommendation": (
            str(recommendation).upper() if recommendation else None
        ),
        "confidence": confidence,
        "summary": (
            payload.get("summary")
            or payload.get("reasoning_summary")
            or payload.get("reasons")
        ),
        "risk_level": (
            payload.get("risk_level")
            or payload.get("risk")
            or getattr(row, "volatility_level", None)
        ),
        "news_sentiment": payload.get("news_sentiment")
        or payload.get("sentiment"),
        "trend": (
            payload.get("trend")
            or payload.get("market_trend")
            or getattr(row, "trend_classification", None)
        ),
        "momentum": payload.get("momentum"),
        "volatility": (
            payload.get("volatility")
            or getattr(row, "volatility_level", None)
        ),
        "provider": getattr(row, "provider_code", None)
        or payload.get("provider"),
        "model": getattr(row, "model", None) or payload.get("model"),
        "analysis_status": row.analysis_status,
        "timeframe": row.timeframe,
    }


def _map_recommendation(
    recommendation: str | None,
    *,
    confidence: Decimal,
    min_confidence: Decimal,
    risk_level: str | None,
) -> AiSignalGateDecision:
    raw = str(recommendation or "").strip().upper()
    # RealtimeAiAction / common synonyms
    if raw in {"HOLD", "WATCH", "EXIT", "BLOCK", "DENY", "REJECT"}:
        return AiSignalGateDecision.HOLD
    if raw in {"REDUCE", "SCALE_DOWN", "PARTIAL"}:
        return AiSignalGateDecision.REDUCE
    if raw in {"ALLOW", "KEEP", "BUY", "LONG", "PASS", "APPROVE"}:
        if confidence < min_confidence:
            return AiSignalGateDecision.HOLD
        if str(risk_level or "").upper() in {"CRITICAL", "EXTREME", "HIGH"}:
            return AiSignalGateDecision.REDUCE
        return AiSignalGateDecision.ALLOW
    if not raw:
        if confidence < min_confidence:
            return AiSignalGateDecision.HOLD
        return AiSignalGateDecision.HOLD
    # unknown → HOLD (Fail Closed for AI-gated path)
    return AiSignalGateDecision.HOLD


def _as_decimal(value: Any, *, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return default


def _store_cache(
    fingerprint: str,
    now: datetime,
    result: AiSignalGateResult,
) -> None:
    if not fingerprint:
        return
    if len(_GATE_CACHE) >= _MAX_CACHE:
        _GATE_CACHE.clear()
    _GATE_CACHE[fingerprint] = (now, result)
