from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.analysis_models import (
    CandidateAnalysisResult,
    CandidateAnalysisRun,
)
from stock_platform.ai.candidate_ranker import (
    CandidateRankingResult,
    RankedCandidate,
)
from stock_platform.ai.reproducibility import build_context_hash


class CandidateAnalysisRepository:
    """AI 후보 평가 실행과 결과 저장소 (append-only)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_analysis(
        self,
        *,
        ranking: CandidateRankingResult,
        requested_limit: int,
        contexts: dict[str, dict],
        parent_analysis_run_id: int | None = None,
        status_code: str = "COMPLETED",
    ) -> CandidateAnalysisRun:
        context_hash = build_context_hash(
            source_candidate_run_id=ranking.source_run_id,
            model_name=ranking.model,
            prompt_version=ranking.prompt_version,
            requested_limit=requested_limit,
            contexts=contexts,
        )
        error_rate = (
            ranking.error_count / ranking.request_count
            if ranking.request_count > 0
            else 0.0
        )
        run = CandidateAnalysisRun(
            source_candidate_run_id=ranking.source_run_id,
            exchange_code=ranking.exchange_code,
            model_name=ranking.model,
            requested_limit=requested_limit,
            selected_count=len(ranking.candidates),
            status_code=status_code,
            prompt_version=ranking.prompt_version,
            context_hash=context_hash,
            used_fallback=ranking.used_fallback,
            duration_ms=ranking.duration_ms,
            error_count=ranking.error_count,
            request_count=ranking.request_count,
            parent_analysis_run_id=parent_analysis_run_id,
            context_snapshot=contexts,
            metrics={
                "error_rate": round(error_rate, 4),
                "used_fallback": ranking.used_fallback,
                "duration_ms": ranking.duration_ms,
            },
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
                    rationale=_build_rationale(candidate),
                )
            )

        self._session.commit()
        self._session.refresh(run)
        return run

    # 하위 호환: 기존 호출부
    def replace_analysis(
        self,
        *,
        ranking: CandidateRankingResult,
        requested_limit: int,
        contexts: dict[str, dict],
    ) -> CandidateAnalysisRun:
        return self.append_analysis(
            ranking=ranking,
            requested_limit=requested_limit,
            contexts=contexts,
        )

    def get_run(
        self,
        analysis_run_id: int,
    ) -> CandidateAnalysisRun | None:
        return self._session.get(
            CandidateAnalysisRun,
            analysis_run_id,
        )

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

    def list_runs(
        self,
        *,
        exchange_code: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[CandidateAnalysisRun]:
        stmt = select(CandidateAnalysisRun)
        if exchange_code:
            stmt = stmt.where(
                CandidateAnalysisRun.exchange_code
                == exchange_code.upper()
            )
        stmt = (
            stmt.order_by(
                CandidateAnalysisRun.created_at.desc(),
                CandidateAnalysisRun.analysis_run_id.desc(),
            )
            .offset(max(0, offset))
            .limit(max(1, min(limit, 100)))
        )
        return list(self._session.scalars(stmt))

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

    def get_result_by_symbol(
        self,
        *,
        analysis_run_id: int,
        symbol: str,
    ) -> CandidateAnalysisResult | None:
        return self._session.scalar(
            select(CandidateAnalysisResult).where(
                CandidateAnalysisResult.analysis_run_id
                == analysis_run_id,
                CandidateAnalysisResult.symbol
                == symbol.upper(),
            )
        )

    def summarize_metrics(
        self,
        *,
        exchange_code: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(
            days=max(1, min(days, 90))
        )
        stmt = select(CandidateAnalysisRun).where(
            CandidateAnalysisRun.created_at >= since
        )
        if exchange_code:
            stmt = stmt.where(
                CandidateAnalysisRun.exchange_code
                == exchange_code.upper()
            )
        runs = list(self._session.scalars(stmt))
        if not runs:
            return {
                "window_days": days,
                "exchange_code": exchange_code,
                "total_runs": 0,
                "fallback_rate": 0.0,
                "error_rate": 0.0,
                "avg_duration_ms": None,
                "completed_count": 0,
                "failed_count": 0,
            }

        total_runs = len(runs)
        fallback_count = sum(
            1 for run in runs if run.used_fallback
        )
        request_total = sum(
            max(1, run.request_count) for run in runs
        )
        error_total = sum(run.error_count for run in runs)
        durations = [
            run.duration_ms
            for run in runs
            if run.duration_ms is not None
        ]
        failed_count = sum(
            1
            for run in runs
            if run.status_code.upper() in {"FAILED", "ERROR"}
        )
        return {
            "window_days": days,
            "exchange_code": exchange_code,
            "total_runs": total_runs,
            "fallback_rate": round(
                fallback_count / total_runs,
                4,
            ),
            "error_rate": round(
                error_total / request_total,
                4,
            ),
            "avg_duration_ms": (
                round(sum(durations) / len(durations), 2)
                if durations
                else None
            ),
            "completed_count": total_runs - failed_count,
            "failed_count": failed_count,
            "fallback_count": fallback_count,
            "request_count": request_total,
            "error_count": error_total,
        }


def _build_rationale(candidate: RankedCandidate) -> dict[str, Any]:
    return {
        "decision": candidate.decision,
        "positive_reasons": candidate.positive_reasons or [],
        "negative_reasons": candidate.negative_reasons or [],
        "risk_flags": candidate.risk_flags or [],
        "invalidation_conditions": (
            candidate.invalidation_conditions or []
        ),
        "suggested_holding_period": (
            candidate.suggested_holding_period
        ),
        "selection_source": candidate.selection_source,
    }
