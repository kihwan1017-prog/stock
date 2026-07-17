from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.screener.models import CandidateScore
from stock_platform.screener.persistence_models import CandidateResult, CandidateRun


class CandidateRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_run(
        self,
        *,
        exchange_code: str,
        as_of_date: date,
        run_type: str,
        requested_count: int,
        evaluated_count: int,
        skipped_count: int,
        minimum_score: Decimal,
        require_all_rules: bool,
        candidates: list[CandidateScore],
    ) -> CandidateRun:
        existing = self._session.scalar(
            select(CandidateRun).where(
                CandidateRun.exchange_code == exchange_code,
                CandidateRun.as_of_date == as_of_date,
                CandidateRun.run_type == run_type,
            )
        )

        if existing is not None:
            self._session.execute(delete(CandidateResult).where(CandidateResult.run_id == existing.run_id))
            run = existing
            run.requested_count = requested_count
            run.evaluated_count = evaluated_count
            run.skipped_count = skipped_count
            run.selected_count = len(candidates)
            run.minimum_score = minimum_score
            run.require_all_rules = require_all_rules
            run.status_code = "COMPLETED"
        else:
            run = CandidateRun(
                exchange_code=exchange_code,
                as_of_date=as_of_date,
                run_type=run_type,
                requested_count=requested_count,
                evaluated_count=evaluated_count,
                skipped_count=skipped_count,
                selected_count=len(candidates),
                minimum_score=minimum_score,
                require_all_rules=require_all_rules,
                status_code="COMPLETED",
            )
            self._session.add(run)
            self._session.flush()

        for rank_no, candidate in enumerate(candidates, start=1):
            self._session.add(CandidateResult(
                run_id=run.run_id,
                rank_no=rank_no,
                exchange_code=candidate.exchange_code,
                symbol=candidate.symbol,
                trade_date=candidate.trade_date,
                total_score=candidate.total_score,
                rules_passed_count=candidate.rules.passed_count,
                all_rules_passed=candidate.rules.passed,
                rule_result=candidate.rules.to_dict(),
                score_breakdown=candidate.breakdown.to_dict(),
            ))

        self._session.commit()
        self._session.refresh(run)
        return run

    def get_latest_run(self, *, exchange_code: str) -> CandidateRun | None:
        return self._session.scalar(
            select(CandidateRun)
            .where(CandidateRun.exchange_code == exchange_code)
            .order_by(CandidateRun.as_of_date.desc(), CandidateRun.run_id.desc())
            .limit(1)
        )

    def get_results(self, run_id: int) -> list[CandidateResult]:
        stmt = select(CandidateResult).where(CandidateResult.run_id == run_id).order_by(CandidateResult.rank_no.asc())
        return list(self._session.scalars(stmt))
