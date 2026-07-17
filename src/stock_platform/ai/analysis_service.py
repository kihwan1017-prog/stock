from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.ai.analysis_repository import (
    CandidateAnalysisRepository,
)
from stock_platform.ai.candidate_ranker import (
    OllamaCandidateRanker,
)
from stock_platform.ai.ollama_client import OllamaClient


class CandidateAnalysisService:
    """Ollama 평가 실행과 DB 저장을 조정한다."""

    def __init__(
        self,
        session: Session,
        ollama_client: OllamaClient,
        model_name: str,
    ) -> None:
        self._ranker = OllamaCandidateRanker(
            session=session,
            ollama_client=ollama_client,
            model_name=model_name,
        )
        self._repository = (
            CandidateAnalysisRepository(session)
        )

    async def execute_and_save(
        self,
        *,
        exchange_code: str,
        limit: int,
        contexts: dict[str, dict],
        minimum_ai_score: float = 60,
        minimum_confidence: float = 0.5,
    ):
        from decimal import Decimal

        ranking = await self._ranker.rank_latest(
            exchange_code=exchange_code,
            limit=limit,
            contexts=contexts,
            minimum_ai_score=Decimal(str(minimum_ai_score)),
            minimum_confidence=Decimal(str(minimum_confidence)),
            allow_fallback=True,
        )

        run = self._repository.replace_analysis(
            ranking=ranking,
            requested_limit=limit,
            contexts=contexts,
        )

        return run, ranking

    def get_latest(self, *, exchange_code: str):
        run = self._repository.get_latest_run(
            exchange_code=exchange_code.upper()
        )
        if run is None:
            return None

        return (
            run,
            self._repository.get_results(
                run.analysis_run_id
            ),
        )
