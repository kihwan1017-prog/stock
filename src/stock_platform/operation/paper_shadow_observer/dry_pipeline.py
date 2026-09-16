"""Market → Analysis → Trading SHADOW → Gate dry → Risk dry.

OES/Outbox/Broker에 연결하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from stock_platform.operation.paper_shadow_observer.guard import (
    assert_observation_only,
)
from stock_platform.operation.paper_shadow_observer.quality import classify_quality
from stock_platform.operation.upbit_market_context.schemas import LlmContextInput
from stock_platform.realtime.ai_signal_gate import _map_recommendation
from stock_platform.realtime.ai_signal_gate_models import AiSignalGateDecision

AnalysisFn = Callable[[LlmContextInput, str], dict[str, Any]]
TradingFn = Callable[[LlmContextInput, dict[str, Any]], dict[str, Any]]


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def ticker_to_input(row: dict[str, Any]) -> LlmContextInput:
    symbol = str(row.get("market") or row.get("symbol") or "")
    price = _num(row.get("trade_price"))
    change = _num(row.get("signed_change_rate"))
    high = _num(row.get("high_price"))
    low = _num(row.get("low_price"))
    turnover = _num(row.get("acc_trade_price_24h"))
    rng = ((high - low) / price) if price and high and low and price > 0 else None
    return LlmContextInput(
        context_as_of=datetime.now(timezone.utc).isoformat(),
        candidate={
            "symbol": symbol,
            "rank": row.get("acc_trade_rank") or row.get("rank"),
            "score": 0.55 if (change or 0) > 0 else 0.35,
            "last_price": price,
        },
        technical={
            "rsi14": 55.0 if (change or 0) > 0 else 45.0,
            "signed_change_rate": change,
            "trade_price": price,
            "range_pct": rng,
            "turnover": turnover,
            "volume_surge": 1.0,
            "ma_separation_pct": (change or 0) * 100,
        },
        market_context={
            "source": "UPBIT_PUBLIC_TICKER",
            "fresh": True,
            "kill_switch": False,
            "stale": False,
            "risk_exceeded": False,
            "authorization_valid": True,
            "quality": "AVAILABLE",
        },
        asset_context={"symbol": symbol, "ticker": row},
        returns={"pre_entry_return_5m": change},
        news=[],
        research_only=True,
        may_create_orders=False,
    )


def dry_ai_gate(trading: dict[str, Any]) -> dict[str, Any]:
    """기존 Gate 매핑을 재사용. DB persist 없음."""

    if not trading.get("ok"):
        return {
            "decision": AiSignalGateDecision.HOLD.value,
            "reason_code": "AI_ANALYSIS_MISSING",
            "summary": "trading inference unavailable",
        }
    confidence = Decimal(str(trading.get("confidence") or 0))
    decision = _map_recommendation(
        trading.get("recommendation"),
        confidence=confidence,
        min_confidence=Decimal("0.4"),
        risk_level=None,
    )
    return {
        "decision": decision.value,
        "reason_code": f"AI_GATE_{decision.value}",
        "summary": str(trading.get("reason_ko") or "")[:240],
        "confidence": float(confidence),
    }


def dry_risk(
    *,
    gate: dict[str, Any],
    trading: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Kill/stale/limit/gate HOLD면 DENY. 주문은 만들지 않는다."""

    flags = extra or {}
    deny_reasons: list[str] = []
    if flags.get("kill_switch"):
        deny_reasons.append("KILL_SWITCH")
    if flags.get("stale"):
        deny_reasons.append("STALE_MARKET")
    if flags.get("risk_exceeded"):
        deny_reasons.append("RISK_LIMIT")
    if flags.get("authorization_expired"):
        deny_reasons.append("AUTHORIZATION_EXPIRED")
    if str(gate.get("decision") or "").upper() != "ALLOW":
        deny_reasons.append("AI_GATE_NOT_ALLOW")
    if str(trading.get("recommendation") or "").upper() != "ALLOW":
        deny_reasons.append("TRADING_NOT_ALLOW")
    if deny_reasons:
        return {
            "decision": "DENY",
            "reasons": deny_reasons,
            "final_entry": "ENTRY_NOT_ALLOWED",
        }
    return {
        "decision": "ALLOW",
        "reasons": ["DRY_CANDIDATE_ONLY"],
        "final_entry": "ENTRY_NOT_SUBMITTED",
    }


def observe_one(
    row: dict[str, Any],
    *,
    run_analysis: AnalysisFn,
    run_trading: TradingFn,
    extra_safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """한 종목 관찰. 주문/outbox/broker 호출 없음."""

    assert_observation_only()
    symbol = str(row.get("market") or row.get("symbol") or "")
    inp = ticker_to_input(row)
    analysis_error = None
    trading_error = None
    fallback = False
    try:
        analysis = run_analysis(inp, symbol)
    except Exception as exc:  # noqa: BLE001
        analysis = {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}
        analysis_error = analysis["error"]
        fallback = True
    try:
        trading = run_trading(inp, analysis if isinstance(analysis, dict) else {})
    except Exception as exc:  # noqa: BLE001
        trading = {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160], "affects_real": False}
        trading_error = trading["error"]
        fallback = True

    if not isinstance(analysis, dict):
        analysis = {"ok": False}
        fallback = True
    if not isinstance(trading, dict):
        trading = {"ok": False, "affects_real": False}
        fallback = True
    if not analysis.get("ok") or not trading.get("ok"):
        fallback = True

    gate = dry_ai_gate(trading)
    risk = dry_risk(gate=gate, trading=trading, extra=extra_safety)
    change = _num(row.get("signed_change_rate"))
    price = _num(row.get("trade_price"))
    high = _num(row.get("high_price"))
    low = _num(row.get("low_price"))
    rng = ((high - low) / price) if price and high and low and price > 0 else None
    quality = classify_quality(
        symbol=symbol,
        change_rate=change,
        range_pct=rng,
        fee_churn_risk=trading.get("fee_churn_risk"),
        recommendation=trading.get("recommendation"),
    )
    rec = str(trading.get("recommendation") or "").upper() or None
    if fallback and rec == "ALLOW":
        # 실패 경로에서 ALLOW가 나오면 관찰 결과를 HOLD로 고정
        rec = None
        trading = {**trading, "ok": False, "recommendation": None}
        gate = {
            "decision": AiSignalGateDecision.HOLD.value,
            "reason_code": "SHADOW_FAIL_CLOSED",
            "summary": "inference failure must not ALLOW",
        }
        risk = {
            "decision": "DENY",
            "reasons": ["SHADOW_FAIL_CLOSED"],
            "final_entry": "ENTRY_NOT_ALLOWED",
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "market_type": "CRYPTO",
        "market_context_summary": {
            "source": "UPBIT_PUBLIC_TICKER",
            "change": change,
            "price": price,
            "range_pct": rng,
            "turnover": _num(row.get("acc_trade_price_24h")),
        },
        "analysis_ok": bool(analysis.get("ok")),
        "analysis_tone": analysis.get("tone"),
        "analysis_confidence": analysis.get("confidence"),
        "analysis_result": {
            "market_summary": (analysis.get("market_summary") or "")[:240],
            "asset_summary": (analysis.get("asset_summary") or "")[:240],
        },
        "trading_ok": bool(trading.get("ok")),
        "trading_recommendation": rec,
        "trading_confidence": trading.get("confidence"),
        "reason_codes": trading.get("reason_codes") or [],
        "risk_flags": trading.get("risk_flags") or [],
        "reason_ko": (trading.get("reason_ko") or "")[:240],
        "ai_gate": gate,
        "risk_dry": risk,
        "final_entry": risk.get("final_entry"),
        "latency": {
            "analysis_ms": analysis.get("latency_ms"),
            "trading_ms": trading.get("latency_ms"),
        },
        "provider": "ollama",
        "model": trading.get("model") or analysis.get("model"),
        "error": analysis_error or trading_error,
        "fallback": fallback,
        "quality": quality,
        "affects_real": bool(trading.get("affects_real")),
        "order_created": 0,
        "outbox_created": 0,
        "broker_order_call": 0,
    }
