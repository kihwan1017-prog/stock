from datetime import date
from decimal import Decimal

from stock_platform.ai.candidate_ranker import (
    CandidateRankingResult,
    RankedCandidate,
)


def test_ranking_result_payload() -> None:
    result = CandidateRankingResult(
        exchange_code="KRX",
        source_run_id=10,
        model="qwen3.5:4b",
        candidates=[
            RankedCandidate(
                rank=1,
                symbol="005930",
                ai_score=Decimal("88"),
                action="REVIEW",
                confidence=Decimal("0.70"),
                reasons=["기술적 조건 양호"],
                risks=["뉴스 검토 필요"],
            )
        ],
    )

    assert result.source_run_id == 10
    assert result.candidates[0].symbol == "005930"
    assert result.candidates[0].ai_score == Decimal("88")
