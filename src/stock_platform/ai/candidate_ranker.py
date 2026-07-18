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
    decision: str = "WATCH"
    positive_reasons: list[str] | None = None
    negative_reasons: list[str] | None = None
    risk_flags: list[str] | None = None
    invalidation_conditions: list[str] | None = None
    suggested_holding_period: str | None = None
    selection_source: str = "AI"


@dataclass(frozen=True, slots=True)
class CandidateRankingResult:
    exchange_code: str
    source_run_id: int
    model: str
    candidates: list[RankedCandidate]
    used_fallback: bool = False
    prompt_version: str = "ranker-v2"
    duration_ms: int | None = None
    error_count: int = 0
    request_count: int = 1


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
                    "decision": {
                        "type": "string",
                        "enum": [
                            "SELECT",
                            "WATCH",
                            "REJECT",
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
                    "positive_reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "negative_reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "risks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "risk_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "invalidation_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "suggested_holding_period": {
                        "type": "string",
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
                "additionalProperties": True,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
당신은 자동매매 시스템의 보수적인 후보 검토 보조자입니다.

입력에는 규칙 기반 점수와 사용자가 제공한 뉴스·공시 요약이
포함될 수 있습니다. 제공되지 않은 사실은 절대 만들지 마세요.
수익을 보장하거나 즉시 매수를 지시하지 마세요.
출력은 반드시 지정된 JSON 스키마를 따르세요.

판단 기준:
- 규칙 기반 총점과 세부 점수
- 통과 규칙 개수
- 제공된 뉴스 요약의 긍정·부정 요인
- 제공된 공시 요약의 리스크
- 정보가 없거나 오래됐으면 위험요소로 기록
"""


class OllamaCandidateRanker:
    """저장된 후보를 Ollama로 재평가한다."""

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
        limit: int = 5,
        contexts: dict[str, dict] | None = None,
        minimum_ai_score: Decimal = Decimal("60"),
        minimum_confidence: Decimal = Decimal("0.5"),
        allow_fallback: bool = True,
    ) -> CandidateRankingResult:
        normalized_exchange = exchange_code.strip().upper()
        run = self._repository.get_latest_run(
            exchange_code=normalized_exchange
        )
        if run is None:
            raise LookupError(
                f"Candidate run not found: "
                f"{normalized_exchange}"
            )
        return await self.rank_for_run(
            source_run_id=run.run_id,
            exchange_code=normalized_exchange,
            limit=limit,
            contexts=contexts,
            minimum_ai_score=minimum_ai_score,
            minimum_confidence=minimum_confidence,
            allow_fallback=allow_fallback,
        )

    async def rank_for_run(
        self,
        *,
        source_run_id: int,
        exchange_code: str | None = None,
        limit: int = 5,
        contexts: dict[str, dict] | None = None,
        minimum_ai_score: Decimal = Decimal("60"),
        minimum_confidence: Decimal = Decimal("0.5"),
        allow_fallback: bool = True,
    ) -> CandidateRankingResult:
        import time

        if not 1 <= limit <= 10:
            raise ValueError(
                "limit must be between 1 and 10"
            )

        run = self._repository.get_run(source_run_id)
        if run is None:
            raise LookupError(
                f"Candidate run not found: "
                f"run_id={source_run_id}"
            )

        normalized_exchange = (
            exchange_code or run.exchange_code
        ).strip().upper()
        if run.exchange_code.upper() != normalized_exchange:
            raise ValueError(
                "exchange_code does not match source run"
            )

        normalized_contexts = {
            key.strip().upper(): value
            for key, value in (contexts or {}).items()
        }

        rows = self._repository.get_results(run.run_id)
        if not rows:
            raise LookupError(
                f"Candidate results are empty: "
                f"run_id={run.run_id}"
            )

        # 규칙 상위 10개만 AI 입력
        input_candidates = rows[:10]
        input_rows = [
            {
                "rule_rank": row.rank_no,
                "symbol": row.symbol,
                "trade_date": row.trade_date.isoformat(),
                "rule_total_score": float(row.total_score),
                "rules_passed_count": (
                    row.rules_passed_count
                ),
                "all_rules_passed": (
                    row.all_rules_passed
                ),
                "rule_result": row.rule_result,
                "score_breakdown": row.score_breakdown,
                "context": normalized_contexts.get(
                    row.symbol,
                    {},
                ),
            }
            for row in input_candidates
        ]

        user_prompt = (
            f"다음 {normalized_exchange} 규칙 후보(최대 10) 중 "
            f"최종 {limit}개 이하를 보수적으로 선정하세요.\n"
            f"최소 ai_score={minimum_ai_score}, "
            f"최소 confidence={minimum_confidence}.\n"
            "입력 데이터 외 사실은 사용하지 마세요.\n"
            "후보 외 종목을 반환하지 마세요.\n"
            "후보 데이터:\n"
            + json.dumps(
                input_rows,
                ensure_ascii=False,
                indent=2,
            )
        )

        used_fallback = False
        error_count = 0
        started = time.perf_counter()
        try:
            response = (
                await self._ollama_client.chat_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    response_schema=RESPONSE_SCHEMA,
                )
            )
            ranked = self._validate_response(
                response=response,
                valid_symbols={
                    row.symbol for row in input_candidates
                },
                limit=limit,
                minimum_ai_score=minimum_ai_score,
                minimum_confidence=minimum_confidence,
            )
        except Exception:
            error_count = 1
            if not allow_fallback:
                raise
            used_fallback = True
            ranked = self._rule_fallback(
                rows=input_candidates,
                limit=limit,
                minimum_score=minimum_ai_score,
            )

        duration_ms = int(
            (time.perf_counter() - started) * 1000
        )
        return CandidateRankingResult(
            exchange_code=normalized_exchange,
            source_run_id=run.run_id,
            model=self._model_name,
            candidates=ranked,
            used_fallback=used_fallback,
            duration_ms=duration_ms,
            error_count=error_count,
            request_count=1,
        )

    @staticmethod
    def _rule_fallback(
        *,
        rows: list,
        limit: int,
        minimum_score: Decimal,
    ) -> list[RankedCandidate]:
        selected: list[RankedCandidate] = []
        for row in rows:
            if Decimal(str(row.total_score)) < minimum_score:
                continue
            selected.append(
                RankedCandidate(
                    rank=len(selected) + 1,
                    symbol=row.symbol,
                    ai_score=Decimal(str(row.total_score)),
                    action="REVIEW",
                    confidence=Decimal("0.5"),
                    reasons=["규칙 기반 fallback 선정"],
                    risks=["AI 평가 실패로 규칙 점수만 사용"],
                    decision="SELECT",
                    positive_reasons=["규칙 점수 충족"],
                    negative_reasons=[],
                    risk_flags=["AI_FALLBACK"],
                    invalidation_conditions=[
                        "규칙 점수 하락",
                    ],
                    suggested_holding_period="SHORT",
                    selection_source="RULE_FALLBACK",
                )
            )
            if len(selected) >= limit:
                break

        if not selected:
            raise ValueError(
                "Fallback selection produced no candidates"
            )
        return selected

    @staticmethod
    def _validate_response(
        *,
        response: dict[str, Any],
        valid_symbols: set[str],
        limit: int,
        minimum_ai_score: Decimal = Decimal("0"),
        minimum_confidence: Decimal = Decimal("0"),
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

            symbol = (
                str(item.get("symbol", ""))
                .strip()
                .upper()
            )
            if (
                symbol not in valid_symbols
                or symbol in seen
            ):
                continue

            ai_score = Decimal(str(item.get("ai_score", 0)))
            confidence = Decimal(
                str(item.get("confidence", 0))
            )
            if ai_score < minimum_ai_score:
                continue
            if confidence < minimum_confidence:
                continue

            seen.add(symbol)
            reasons = [
                str(value)
                for value in item.get("reasons", [])
            ]
            risks = [
                str(value)
                for value in item.get("risks", [])
            ]
            positive = item.get("positive_reasons") or reasons
            negative = item.get("negative_reasons") or []
            risk_flags = item.get("risk_flags") or risks

            result.append(
                RankedCandidate(
                    rank=len(result) + 1,
                    symbol=symbol,
                    ai_score=ai_score,
                    action=str(
                        item.get("action", "REVIEW")
                    ).upper(),
                    confidence=confidence,
                    reasons=reasons,
                    risks=risks,
                    decision=str(
                        item.get("decision", "SELECT")
                    ).upper(),
                    positive_reasons=[
                        str(value) for value in positive
                    ],
                    negative_reasons=[
                        str(value) for value in negative
                    ],
                    risk_flags=[
                        str(value) for value in risk_flags
                    ],
                    invalidation_conditions=[
                        str(value)
                        for value in item.get(
                            "invalidation_conditions",
                            [],
                        )
                    ],
                    suggested_holding_period=(
                        str(item["suggested_holding_period"])
                        if item.get("suggested_holding_period")
                        else None
                    ),
                    selection_source="AI",
                )
            )

            if len(result) >= limit:
                break

        if not result:
            raise ValueError(
                "Ollama response did not contain "
                "valid candidates"
            )

        return result
