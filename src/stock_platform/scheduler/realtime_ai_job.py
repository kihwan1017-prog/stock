from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.realtime.ai_runner import (
    realtime_ai_review_runner,
)


class RealtimeAiReviewJob:
    async def execute(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = await (
            realtime_ai_review_runner.review_symbol(
                exchange_code=str(
                    payload["exchange_code"]
                ),
                symbol=str(payload["symbol"]),
                current_price=Decimal(
                    str(payload["current_price"])
                ),
                news_limit=int(
                    payload.get("news_limit", 10)
                ),
                disclosure_limit=int(
                    payload.get(
                        "disclosure_limit",
                        10,
                    )
                ),
                lookback_days=int(
                    payload.get("lookback_days", 30)
                ),
            )
        )

        return {
            "exchange_code": result.exchange_code,
            "symbol": result.symbol,
            "action": result.action.value,
            "score": str(result.score),
            "confidence": str(result.confidence),
            "summary": result.summary,
            "risk_factors": result.risk_factors,
            "reviewed_at": (
                result.reviewed_at.isoformat()
            ),
        }
