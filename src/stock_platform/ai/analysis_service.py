from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.ai.analysis_repository import (
    CandidateAnalysisRepository,
)
from stock_platform.ai.candidate_ranker import (
    OllamaCandidateRanker,
)
from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.ai.reproducibility import (
    compare_analysis_results,
)


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
        source_run_id: int | None = None,
        parent_analysis_run_id: int | None = None,
    ):
        if source_run_id is None:
            ranking = await self._ranker.rank_latest(
                exchange_code=exchange_code,
                limit=limit,
                contexts=contexts,
                minimum_ai_score=Decimal(
                    str(minimum_ai_score)
                ),
                minimum_confidence=Decimal(
                    str(minimum_confidence)
                ),
                allow_fallback=True,
            )
        else:
            ranking = await self._ranker.rank_for_run(
                source_run_id=source_run_id,
                exchange_code=exchange_code,
                limit=limit,
                contexts=contexts,
                minimum_ai_score=Decimal(
                    str(minimum_ai_score)
                ),
                minimum_confidence=Decimal(
                    str(minimum_confidence)
                ),
                allow_fallback=True,
            )

        run = self._repository.append_analysis(
            ranking=ranking,
            requested_limit=limit,
            contexts=contexts,
            parent_analysis_run_id=parent_analysis_run_id,
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

    def get_run(self, analysis_run_id: int):
        run = self._repository.get_run(analysis_run_id)
        if run is None:
            return None
        return (
            run,
            self._repository.get_results(
                run.analysis_run_id
            ),
        )

    def get_candidate_rationale(
        self,
        *,
        analysis_run_id: int,
        symbol: str,
    ):
        run = self._repository.get_run(analysis_run_id)
        if run is None:
            return None
        result = self._repository.get_result_by_symbol(
            analysis_run_id=analysis_run_id,
            symbol=symbol,
        )
        if result is None:
            return None
        return run, result

    def list_runs(
        self,
        *,
        exchange_code: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ):
        return self._repository.list_runs(
            exchange_code=exchange_code,
            limit=limit,
            offset=offset,
        )

    def get_metrics(
        self,
        *,
        exchange_code: str | None = None,
        days: int = 7,
    ):
        return self._repository.summarize_metrics(
            exchange_code=exchange_code,
            days=days,
        )

    async def reproduce(
        self,
        *,
        analysis_run_id: int,
    ):
        baseline = self.get_run(analysis_run_id)
        if baseline is None:
            raise LookupError(
                f"AI analysis not found: "
                f"analysis_run_id={analysis_run_id}"
            )
        base_run, base_rows = baseline

        reproduced_run, ranking = await self.execute_and_save(
            exchange_code=base_run.exchange_code,
            limit=base_run.requested_limit,
            contexts=dict(base_run.context_snapshot or {}),
            source_run_id=base_run.source_candidate_run_id,
            parent_analysis_run_id=base_run.analysis_run_id,
        )

        comparison = compare_analysis_results(
            baseline=[
                {
                    "rank": row.rank_no,
                    "symbol": row.symbol,
                    "ai_score": row.ai_score,
                    "action": row.action_code,
                }
                for row in base_rows
            ],
            reproduced=[
                {
                    "rank": item.rank,
                    "symbol": item.symbol,
                    "ai_score": item.ai_score,
                    "action": item.action,
                }
                for item in ranking.candidates
            ],
        )
        return {
            "baseline_run": base_run,
            "reproduced_run": reproduced_run,
            "ranking": ranking,
            "comparison": comparison,
            "same_context_hash": (
                base_run.context_hash
                == reproduced_run.context_hash
            ),
        }
