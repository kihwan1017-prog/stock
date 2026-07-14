from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.common.settings import get_settings
from stock_platform.realtime.ai_models import (
    RealtimeAiAction,
    RealtimeAiReviewRequest,
    RealtimeAiReviewResult,
)


class RealtimeAiReviewService:
    """실시간 보유 종목을 뉴스·공시 컨텍스트로 재평가한다."""

    def __init__(
        self,
        *,
        session: Session,
        ollama_client: OllamaClient,
    ) -> None:
        self._session = session
        self._ollama_client = ollama_client
        self._settings = get_settings()

    async def review(
        self,
        request: RealtimeAiReviewRequest,
    ) -> RealtimeAiReviewResult:
        context = await self._load_context(request)
        prompt = self._build_prompt(
            request=request,
            context=context,
        )

        response = await self._ollama_client.generate(
            model=self._settings.ollama_model,
            prompt=prompt,
            format="json",
            options={
                "temperature": 0.1,
            },
        )

        payload = self._parse_response(response)

        return RealtimeAiReviewResult(
            exchange_code=request.exchange_code.upper(),
            symbol=request.symbol.upper(),
            action=RealtimeAiAction(
                str(payload.get("action", "WATCH")).upper()
            ),
            score=Decimal(str(payload.get("score", 50))),
            confidence=Decimal(
                str(payload.get("confidence", 0.5))
            ),
            summary=str(
                payload.get(
                    "summary",
                    "AI 재평가 결과가 없습니다.",
                )
            ),
            risk_factors=[
                str(item)
                for item in payload.get(
                    "risk_factors",
                    [],
                )
            ],
            reviewed_at=datetime.now(timezone.utc),
        )

    async def _load_context(
        self,
        request: RealtimeAiReviewRequest,
    ) -> dict[str, Any]:
        """
        기존 뉴스·공시 저장 구조 차이를 흡수하기 위해 최소 컨텍스트를
        반환한다. 프로젝트의 Repository에 맞춰 이 메서드를 확장한다.
        """
        return {
            "exchange_code": request.exchange_code.upper(),
            "symbol": request.symbol.upper(),
            "current_price": str(request.current_price),
            "current_quantity": str(request.current_quantity),
            "average_entry_price": (
                str(request.average_entry_price)
                if request.average_entry_price is not None
                else None
            ),
            "news": [],
            "disclosures": [],
            "lookback_days": request.lookback_days,
        }

    @staticmethod
    def _build_prompt(
        *,
        request: RealtimeAiReviewRequest,
        context: dict[str, Any],
    ) -> str:
        return (
            "당신은 자동매매 위험관리 보조 모델입니다.\n"
            "아래 종목의 최신 상황을 평가하고 JSON만 반환하세요.\n"
            "실제 주문을 지시하지 말고 보수적으로 판단하세요.\n\n"
            "허용 action: KEEP, REDUCE, EXIT, WATCH\n"
            "score: 0~100\n"
            "confidence: 0~1\n"
            "summary: 한글 요약\n"
            "risk_factors: 문자열 배열\n\n"
            f"context={json.dumps(context, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_response(
        response: Any,
    ) -> dict[str, Any]:
        if isinstance(response, dict):
            if isinstance(response.get("response"), str):
                return json.loads(response["response"])
            return response

        if isinstance(response, str):
            return json.loads(response)

        raise ValueError(
            "Unsupported Ollama response format"
        )
