from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.screener.run_repository import (
    CandidateRunRepository,
)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    rank: int
    symbol: str
    ai_score: Decimal
    action: str
    confidence: Decimal
    reasons: list[str]
    risks: list[str]


@dataclass(frozen=True, slots=True)
class CandidateRankingResult:
    exchange_code: str
    source_run_id: int
    model: str
    candidates: list[RankedCandidate]


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "symbol": {"type": "string"},
                    "ai_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "WATCH",
                            "REVIEW",
                            "AVOID",
                        ],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "risks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "rank",
                    "symbol",
                    "ai_score",
                    "action",
                    "confidence",
                    "reasons",
                    "risks",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
당신은 자동매매 시스템의 보수적인 후보 검토 보조자입니다.

입력에는 규칙 기반 점수와 기술적 조건만 포함됩니다.
수익을 보장하거나 매수를 지시하지 마세요.
제공되지 않은 뉴스, 공시, 재무정보를 지어내지 마세요.
출력은 반드시 지정된 JSON 스키마를 따르세요.

판단 기준:
- 규칙 기반 총점
- 통과 규칙 개수
- 거래량, 추세, RSI, MACD, 돌파, 변동성 세부점수
- 정보 부족은 위험요소로 기록
"""


class OllamaCandidateRanker:
    """저장된 후보선정 결과를 Ollama로 재평가한다."""

    def __init__(
        self,
        session: Session,
        ollama_client: OllamaClient,
        model_name: str,
    ) -> None:
        self._repository = CandidateRunRepository(session)
        self._ollama_client = ollama_client
        self._model_name = model_name

    async def rank_latest(
        self,
        *,
        exchange_code: str,
        limit: int = 10,
    ) -> CandidateRankingResult:
        if not 1 <= limit <= 30:
            raise ValueError("limit must be between 1 and 30")

        normalized_exchange = exchange_code.strip().upper()

        run = self._repository.get_latest_run(
            exchange_code=normalized_exchange
        )
        if run is None:
            raise LookupError(
                f"Candidate run not found: {normalized_exchange}"
            )

        rows = self._repository.get_results(run.run_id)
        if not rows:
            raise LookupError(
                f"Candidate results are empty: run_id={run.run_id}"
            )

        input_rows = [
            {
                "rule_rank": row.rank_no,
                "symbol": row.symbol,
                "trade_date": row.trade_date.isoformat(),
                "rule_total_score": float(row.total_score),
                "rules_passed_count": row.rules_passed_count,
                "all_rules_passed": row.all_rules_passed,
                "rule_result": row.rule_result,
                "score_breakdown": row.score_breakdown,
            }
            for row in rows
        ]

        user_prompt = (
            f"다음 {normalized_exchange} 후보 중 최대 {limit}개를 "
            "보수적으로 재정렬하세요.\n"
            "입력 데이터 외 사실은 사용하지 마세요.\n"
            "후보 데이터:\n"
            + json.dumps(
                input_rows,
                ensure_ascii=False,
                indent=2,
            )
        )

        response = await self._ollama_client.chat_structured(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=RESPONSE_SCHEMA,
        )

        ranked = self._validate_response(
            response=response,
            valid_symbols={row.symbol for row in rows},
            limit=limit,
        )

        return CandidateRankingResult(
            exchange_code=normalized_exchange,
            source_run_id=run.run_id,
            model=self._model_name,
            candidates=ranked,
        )

    @staticmethod
    def _validate_response(
        *,
        response: dict[str, Any],
        valid_symbols: set[str],
        limit: int,
    ) -> list[RankedCandidate]:
        raw_candidates = response.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError(
                "Ollama response candidates must be a list"
            )

        result: list[RankedCandidate] = []
        seen: set[str] = set()

        for item in raw_candidates:
            if not isinstance(item, dict):
                continue

            symbol = str(item.get("symbol", "")).strip().upper()
            if symbol not in valid_symbols or symbol in seen:
                continue

            seen.add(symbol)

            result.append(
                RankedCandidate(
                    rank=len(result) + 1,
                    symbol=symbol,
                    ai_score=Decimal(
                        str(item.get("ai_score", 0))
                    ),
                    action=str(
                        item.get("action", "REVIEW")
                    ).upper(),
                    confidence=Decimal(
                        str(item.get("confidence", 0))
                    ),
                    reasons=[
                        str(value)
                        for value in item.get("reasons", [])
                    ],
                    risks=[
                        str(value)
                        for value in item.get("risks", [])
                    ],
                )
            )

            if len(result) >= limit:
                break

        if not result:
            raise ValueError(
                "Ollama response did not contain valid candidates"
            )

        return result
