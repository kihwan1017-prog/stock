from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from stock_platform.ai.analysis_service import (
    CandidateAnalysisService,
)
from stock_platform.ai.context_builder import CandidateContextBuilder
from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.screener.run_repository import (
    CandidateRunRepository,
)


class CandidateAnalysisOrchestrator:
    """
    최신 규칙 기반 후보의 뉴스·공시 컨텍스트를 자동 구성하고
    Ollama 평가 결과를 저장한다.
    """

    def __init__(
        self,
        *,
        session: Session,
        ollama_client: OllamaClient,
        model_name: str,
    ) -> None:
        self._candidate_repository = CandidateRunRepository(session)
        self._context_builder = CandidateContextBuilder(session)
        self._analysis_service = CandidateAnalysisService(
            session=session,
            ollama_client=ollama_client,
            model_name=model_name,
        )

    async def execute(
        self,
        *,
        exchange_code: str,
        limit: int = 5,
        news_limit: int = 20,
        disclosure_limit: int = 20,
        lookback_days: int = 90,
        minimum_ai_score: float = 60,
        minimum_confidence: float = 0.5,
    ):
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10")

        normalized_exchange = exchange_code.strip().upper()

        candidate_run = self._candidate_repository.get_latest_run(
            exchange_code=normalized_exchange
        )
        if candidate_run is None:
            raise LookupError(
                f"Candidate run not found: {normalized_exchange}"
            )

        candidate_rows = self._candidate_repository.get_results(
            candidate_run.run_id
        )
        if not candidate_rows:
            raise LookupError(
                f"Candidate results are empty: "
                f"run_id={candidate_run.run_id}"
            )

        # 규칙 상위 10 → AI 최종 limit(기본 5)
        selected_rows = candidate_rows[:10]
        contexts: dict[str, dict] = {}

        for row in selected_rows:
            contexts[row.symbol] = self._context_builder.build(
                exchange_code=normalized_exchange,
                symbol=row.symbol,
                as_of_date=candidate_run.as_of_date,
                news_limit=news_limit,
                disclosure_limit=disclosure_limit,
                lookback_days=lookback_days,
            )

        run, ranking = await self._analysis_service.execute_and_save(
            exchange_code=normalized_exchange,
            limit=limit,
            contexts=contexts,
            minimum_ai_score=minimum_ai_score,
            minimum_confidence=minimum_confidence,
        )

        return {
            "analysis_run": run,
            "ranking": ranking,
            "contexts": contexts,
        }
