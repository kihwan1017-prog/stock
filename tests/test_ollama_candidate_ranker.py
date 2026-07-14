import asyncio
from datetime import date
from types import SimpleNamespace

from stock_platform.ai.candidate_ranker import (
    OllamaCandidateRanker,
)


class FakeRepository:
    def get_latest_run(self, *, exchange_code: str):
        return SimpleNamespace(run_id=7)

    def get_results(self, run_id: int):
        return [
            SimpleNamespace(
                rank_no=1,
                symbol="005930",
                trade_date=date(2026, 7, 13),
                total_score=85,
                rules_passed_count=5,
                all_rules_passed=False,
                rule_result={"volume_surge": True},
                score_breakdown={"total": "85"},
            ),
            SimpleNamespace(
                rank_no=2,
                symbol="000660",
                trade_date=date(2026, 7, 13),
                total_score=80,
                rules_passed_count=4,
                all_rules_passed=False,
                rule_result={"volume_surge": True},
                score_breakdown={"total": "80"},
            ),
        ]


class FakeOllamaClient:
    async def chat_structured(self, **kwargs):
        return {
            "candidates": [
                {
                    "rank": 1,
                    "symbol": "000660",
                    "ai_score": 88,
                    "action": "REVIEW",
                    "confidence": 0.7,
                    "reasons": ["규칙 점수가 높음"],
                    "risks": ["뉴스·공시 정보 없음"],
                },
                {
                    "rank": 2,
                    "symbol": "005930",
                    "ai_score": 82,
                    "action": "WATCH",
                    "confidence": 0.6,
                    "reasons": ["기술적 조건 양호"],
                    "risks": ["추가 검토 필요"],
                },
            ]
        }


def test_rank_latest_filters_and_orders() -> None:
    ranker = OllamaCandidateRanker.__new__(
        OllamaCandidateRanker
    )
    ranker._repository = FakeRepository()
    ranker._ollama_client = FakeOllamaClient()
    ranker._model_name = "qwen3.5:4b"

    result = asyncio.run(
        ranker.rank_latest(
            exchange_code="KRX",
            limit=2,
        )
    )

    assert result.source_run_id == 7
    assert [item.symbol for item in result.candidates] == [
        "000660",
        "005930",
    ]
    assert result.candidates[0].rank == 1
