from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.ai.analysis_models import (
    CandidateAnalysisResult,
    CandidateAnalysisRun,
)
from stock_platform.ai.candidate_ranker import (
    CandidateRankingResult,
)


class CandidateAnalysisRepository:
    """AI 후보 평가 실행과 결과 저장소."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_analysis(
        self,
        *,
        ranking: CandidateRankingResult,
        requested_limit: int,
        contexts: dict[str, dict],
    ) -> CandidateAnalysisRun:
        existing = self._session.scalar(
            select(CandidateAnalysisRun).where(
                CandidateAnalysisRun.source_candidate_run_id
                == ranking.source_run_id,
                CandidateAnalysisRun.model_name
                == ranking.model,
            )
        )

        if existing is not None:
            self._session.execute(
                delete(CandidateAnalysisResult).where(
                    CandidateAnalysisResult.analysis_run_id
                    == existing.analysis_run_id
                )
            )
            run = existing
            run.exchange_code = ranking.exchange_code
            run.requested_limit = requested_limit
            run.selected_count = len(ranking.candidates)
            run.status_code = "COMPLETED"
            run.context_snapshot = contexts
        else:
            run = CandidateAnalysisRun(
                source_candidate_run_id=ranking.source_run_id,
                exchange_code=ranking.exchange_code,
                model_name=ranking.model,
                requested_limit=requested_limit,
                selected_count=len(ranking.candidates),
                status_code="COMPLETED",
                context_snapshot=contexts,
            )
            self._session.add(run)
            self._session.flush()

        for candidate in ranking.candidates:
            self._session.add(
                CandidateAnalysisResult(
                    analysis_run_id=run.analysis_run_id,
                    rank_no=candidate.rank,
                    symbol=candidate.symbol,
                    ai_score=candidate.ai_score,
                    action_code=candidate.action,
                    confidence=candidate.confidence,
                    reasons=candidate.reasons,
                    risks=candidate.risks,
                    context_used=contexts.get(
                        candidate.symbol,
                        {},
                    ),
                )
            )

        self._session.commit()
        self._session.refresh(run)
        return run

    def get_latest_run(
        self,
        *,
        exchange_code: str,
    ) -> CandidateAnalysisRun | None:
        return self._session.scalar(
            select(CandidateAnalysisRun)
            .where(
                CandidateAnalysisRun.exchange_code
                == exchange_code
            )
            .order_by(
                CandidateAnalysisRun.created_at.desc(),
                CandidateAnalysisRun.analysis_run_id.desc(),
            )
            .limit(1)
        )

    def get_results(
        self,
        analysis_run_id: int,
    ) -> list[CandidateAnalysisResult]:
        stmt = (
            select(CandidateAnalysisResult)
            .where(
                CandidateAnalysisResult.analysis_run_id
                == analysis_run_id
            )
            .order_by(
                CandidateAnalysisResult.rank_no.asc()
            )
        )
        return list(self._session.scalars(stmt))
