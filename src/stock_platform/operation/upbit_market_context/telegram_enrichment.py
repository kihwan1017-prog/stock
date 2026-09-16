"""Telegram enrichment snippets — spam 금지, optional short fields only."""

from __future__ import annotations

from typing import Any


def market_mood_ko(advancing_ratio: float | None, fear_greed: int | None) -> str:
    if advancing_ratio is not None:
        if advancing_ratio >= 0.6:
            return "강세"
        if advancing_ratio <= 0.4:
            return "약세"
    if fear_greed is not None:
        if fear_greed >= 70:
            return "탐욕"
        if fear_greed <= 30:
            return "공포"
    return "중립"


def build_optional_telegram_suffix(ctx: dict[str, Any]) -> str | None:
    """기존 후보 메시지에 붙일 짧은 한 줄. 매 tick 강제 발송 금지(호출측 책임)."""

    mood = market_mood_ko(ctx.get("advancing_ratio"), ctx.get("fear_greed"))
    weekly = ctx.get("weekly_return_pct")
    llm_risk = ctx.get("llm_risk_short")  # e.g. 추격매수/과열
    parts = [f"시장:{mood}"]
    if weekly is not None:
        parts.append(f"주간:{weekly:+.2f}%")
    if llm_risk:
        parts.append(f"LLM위험:{llm_risk}")
    strength = ctx.get("execution_bias")  # 매수우위/매도우위
    if strength:
        parts.append(f"체결:{strength}")
    if len(parts) <= 1 and mood == "중립":
        return None
    return " · ".join(parts)
