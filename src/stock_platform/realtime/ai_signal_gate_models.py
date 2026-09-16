"""UPBIT 자동매매 AI Signal Gate 계약 — LLM은 주문 생성하지 않음."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class AiSignalGateDecision(StrEnum):
    """MA Signal 보조 판단. BUY/SELL 생성 금지."""

    ALLOW = "ALLOW"
    HOLD = "HOLD"
    REDUCE = "REDUCE"


@dataclass(frozen=True, slots=True)
class AiSignalGateResult:
    decision: AiSignalGateDecision
    confidence: Decimal
    reason_code: str
    summary: str = ""
    risk_level: str | None = None
    news_sentiment: str | None = None
    recommendation: str | None = None
    analysis_at: datetime | None = None
    age_seconds: float | None = None
    stale: bool = False
    provider: str | None = None
    model: str | None = None
    market_analysis_id: int | None = None
    size_multiplier: Decimal = Decimal("1")
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "confidence": str(self.confidence),
            "reason_code": self.reason_code,
            "summary": self.summary,
            "risk_level": self.risk_level,
            "news_sentiment": self.news_sentiment,
            "recommendation": self.recommendation,
            "analysis_at": (
                self.analysis_at.isoformat() if self.analysis_at else None
            ),
            "age_seconds": self.age_seconds,
            "stale": self.stale,
            "provider": self.provider,
            "model": self.model,
            "market_analysis_id": self.market_analysis_id,
            "size_multiplier": str(self.size_multiplier),
            "detail": self.detail,
        }
