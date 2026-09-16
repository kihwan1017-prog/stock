"""Trading Decision input/prompt contract.

recommendation은 주문 명령이 아니다.
SHADOW는 실제 주문에 영향을 주지 않는다는 뜻이지, 항상 HOLD라는 뜻이 아니다.
"""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_market_context.schemas import (
    LlmContextInput,
    LlmContextOutput,
)

# 새 버전만 추가 — v1 문자열은 prompt_versions에 보존
TRADING_SYSTEM_PROMPT_V2 = (
    "당신은 UPBIT TRADING Decision 역할입니다. "
    "지금은 SHADOW 모드입니다. SHADOW는 결과가 실제 주문·LIVE·ARM·Risk 한도에 "
    "영향을 주지 않는다는 뜻이지, 항상 HOLD하라는 뜻이 아닙니다. "
    "실제 판단 결과를 그대로 반환하십시오. "
    "recommendation은 주문 실행 명령이 아닙니다. "
    "ALLOW는 downstream Risk Engine이 신규 진입을 평가할 수 있는 후보라는 의미입니다. "
    "HOLD는 신규 진입 후보로 넘기지 않는다는 의미입니다. "
    "REDUCE는 노출 축소 권고입니다. "
    "최종 진입 허용권은 downstream Risk Engine에 있습니다. "
    "kill_switch, stale, invalid_price, risk_exceeded, authorization_expired 같은 "
    "hard safety violation은 반드시 HOLD입니다. "
    "news와 RAG는 optional입니다. available=false여도 시장·분석 근거가 충분하면 "
    "그 자체로 HOLD 사유가 아닙니다. "
    "입력에 없는 사실을 만들지 마십시오. 미래 수익률은 모릅니다. JSON만 반환하십시오."
)

TRADING_USER_INSTRUCTION_V2 = (
    "아래 decision_contract와 입력을 보고 recommendation을 반환하십시오. "
    "Entry Quality, Early Dump Risk, Fee Churn Risk를 평가하십시오. "
    "SHADOW이므로 결과는 실제 주문으로 이어지지 않습니다. "
    "판단을 숨기거나 항상 HOLD로 바꾸지 마십시오."
)

# 모델이 이 문구를 ALLOW 금지로 읽지 않도록 유지해야 하는 금지 패턴
FORBIDDEN_PROMPT_PHRASES = (
    "가능하면 ALLOW",
    "적극적으로 매수",
    "더 자주 ALLOW",
    "수익을 극대화",
)


def _as_bool(value: Any) -> bool:
    """명시적 truthy만 True. 없는 값은 False."""

    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)) and value == 1:
        return True
    return False


def _finite_positive_number(value: Any) -> bool | None:
    """가격/수량 유효성. 없으면 None, 잘못된 값이면 False."""

    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number != number or number in (float("inf"), float("-inf")):
        return False
    return number > 0


def _signed_change(technical: dict[str, Any], returns: dict[str, Any]) -> float | None:
    raw = technical.get("signed_change_rate")
    if raw is None:
        raw = returns.get("pre_entry_return_5m")
    if raw is None:
        raw = returns.get("daily_signed_change_rate")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _direction_label(change: float | None) -> str | None:
    """이미 있는 수익률 숫자를 방향 라벨로만 표시. 새 전략이 아님."""

    if change is None:
        return None
    if change >= 0.03:
        return "POSITIVE"
    if change <= -0.03:
        return "NEGATIVE"
    return "SIDEWAYS"


def extract_safety_flags(
    market_context: dict[str, Any],
    *,
    price_valid: bool | None,
) -> dict[str, Any]:
    """upstream/market_context에 있는 안전 플래그만 정규화."""

    kill_switch = _as_bool(market_context.get("kill_switch"))
    stale = _as_bool(
        market_context.get("stale") or market_context.get("stale_market_data")
    )
    risk_exceeded = _as_bool(
        market_context.get("risk_exceeded")
        or market_context.get("risk_limit_exceeded")
    )
    authorization_expired = _as_bool(
        market_context.get("auth_expired")
        or market_context.get("authorization_expired")
    )
    if market_context.get("authorization_valid") is False:
        authorization_expired = True
    invalid_price = price_valid is False
    hard_safety_violation = bool(
        kill_switch
        or stale
        or risk_exceeded
        or authorization_expired
        or invalid_price
    )
    return {
        "kill_switch": kill_switch,
        "stale": stale,
        "risk_exceeded": risk_exceeded,
        "authorization_expired": authorization_expired,
        "authorization_valid": market_context.get("authorization_valid"),
        "invalid_price": invalid_price,
        "price_valid": price_valid,
        "fresh": False if stale else market_context.get("fresh"),
        "hard_safety_violation": hard_safety_violation,
    }


def build_trading_decision_payload(
    inp: LlmContextInput,
    *,
    analysis_summary: dict[str, Any] | None,
    heuristic: LlmContextOutput | None = None,
    rag_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Trading LLM 입력. 없는 optional 데이터는 실패가 아니라 available=false."""

    market = inp.market_context if isinstance(inp.market_context, dict) else {}
    technical = inp.technical if isinstance(inp.technical, dict) else {}
    returns = inp.returns if isinstance(inp.returns, dict) else {}
    candidate_raw = dict(inp.candidate or {})
    # candidate.recommendation은 출력 enum과 이름이 같아 HOLD 편향을 만들 수 있음
    scanner_recommendation = candidate_raw.pop("recommendation", None)
    analysis = analysis_summary if isinstance(analysis_summary, dict) else {}
    news_items = [n for n in (inp.news or []) if isinstance(n, dict)]
    rag_items = [e for e in (rag_examples or []) if isinstance(e, dict)]

    price = (
        technical.get("trade_price")
        or candidate_raw.get("last_price")
        or candidate_raw.get("price")
    )
    price_valid = _finite_positive_number(price)
    change = _signed_change(technical, returns)
    safety = extract_safety_flags(market, price_valid=price_valid)

    execution = inp.execution_strength if isinstance(inp.execution_strength, dict) else {}
    execution_available = bool(execution) and str(execution.get("status") or "") not in {
        "DATALAB_DEFERRED",
        "MISSING",
        "QUALITY_MISSING",
    }

    compact = {
        "decision_contract": {
            "recommendation_is_order": False,
            "shadow_means_always_hold": False,
            "allow_meaning": "CANDIDATE_FOR_DOWNSTREAM_RISK_EVALUATION",
            "hold_meaning": "DO_NOT_FORWARD_AS_NEW_ENTRY",
            "reduce_meaning": "REDUCE_EXPOSURE",
            "final_entry_authority": "DOWNSTREAM_RISK_ENGINE",
            "hard_safety_requires_hold": True,
            "optional_news_rag_not_required": True,
        },
        "context_as_of": inp.context_as_of,
        "candidate": {
            "symbol": candidate_raw.get("symbol"),
            "rank": candidate_raw.get("rank"),
            "score": candidate_raw.get("score"),
            "last_price": candidate_raw.get("last_price") or price,
            "scanner_recommendation": scanner_recommendation,
            "scanner_recommendation_non_binding": True,
        },
        "technical": {
            "rsi": technical.get("rsi14"),
            "ma_separation_pct": technical.get("ma_separation_pct"),
            "volume_ratio": technical.get("volume_surge"),
            "signed_change_rate": change,
            "trade_price": price,
            "range_pct": technical.get("range_pct"),
            "turnover": technical.get("turnover") or returns.get("acc_trade_price_24h"),
            "pre_entry_return": returns.get("pre_entry_return_5m"),
        },
        "market_structure": {
            "trend": technical.get("trend") or _direction_label(change),
            "momentum": technical.get("momentum") or _direction_label(change),
            "volatility": technical.get("volatility")
            or ("HIGH" if (technical.get("range_pct") or 0) >= 0.08 else None),
            "liquidity": market.get("liquidity"),
            "quality": market.get("quality"),
        },
        "safety": safety,
        "optional_context": {
            "news": {
                "available": bool(news_items),
                "count": len(news_items),
                "absence_is_not_automatic_hold": True,
            },
            "rag": {
                "available": bool(rag_items),
                "count": len(rag_items),
                "absence_is_not_automatic_hold": True,
            },
            "execution_strength": {
                "available": execution_available,
                "status": execution.get("status"),
            },
        },
        "analysis": {
            "available": bool(analysis),
            "ok": analysis.get("ok"),
            "tone": analysis.get("tone"),
            "market_summary": analysis.get("market_summary")
            or analysis.get("market_state"),
            "asset_summary": analysis.get("asset_summary")
            or analysis.get("asset_state"),
            "news_summary": analysis.get("news_summary") or analysis.get("news_state"),
            "risk_factors": analysis.get("risk_factors") or analysis.get("risk_flags"),
            "confidence": analysis.get("confidence"),
            "model": analysis.get("model"),
        },
        "rag_examples": [
            {
                "case_id": example.get("case_id"),
                "similarity_score": example.get("similarity_score"),
                "entry_summary": example.get("entry_summary"),
                "actual_label": example.get("actual_label"),
                "mfe": example.get("mfe"),
                "mae": example.get("mae"),
            }
            for example in rag_items[:5]
        ],
        "heuristic_reference": (
            {
                "non_binding": True,
                "do_not_copy": True,
                "recommendation": heuristic.recommendation,
                "entry_quality_score": heuristic.entry_quality_score,
                "risk_flags": heuristic.risk_flags,
            }
            if heuristic is not None
            else None
        ),
        "affects_real_orders": False,
        "lookahead_forbidden": True,
        "current_future_outcome_forbidden": True,
    }
    return compact


def build_trading_user_prompt(payload: dict[str, Any]) -> str:
    """system prompt와 분리된 user payload."""

    import json

    return TRADING_USER_INSTRUCTION_V2 + "\n" + json.dumps(
        payload, ensure_ascii=False, default=str
    )


def prompt_forbids_aggressive_allow(text: str) -> bool:
    """ALLOW를 유도하는 금지 문구가 없는지 확인."""

    return not any(phrase in text for phrase in FORBIDDEN_PROMPT_PHRASES)
