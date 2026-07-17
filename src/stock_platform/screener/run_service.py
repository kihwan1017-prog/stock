from __future__ import annotations

from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session

from stock_platform.screener.batch_service import CandidateBatchService
from stock_platform.screener.persistence_models import CandidateResult, CandidateRun
from stock_platform.screener.run_repository import CandidateRunRepository


class CandidateRunService:
    def __init__(self, session: Session) -> None:
        self._batch_service = CandidateBatchService(session)
        self._repository = CandidateRunRepository(session)

    def execute_and_save(
        self,
        *,
        exchange_code: str,
        as_of_date: date,
        limit: int = 10,
        minimum_score: Decimal = Decimal("0"),
        require_all_rules: bool = False,
        run_type: str = "DAILY",
    ) -> CandidateRun:
        result = self._batch_service.screen(
            exchange_code=exchange_code,
            as_of_date=as_of_date,
            limit=limit,
            minimum_score=float(minimum_score),
            require_all_rules=require_all_rules,
        )
        return self._repository.replace_run(
            exchange_code=result.exchange_code,
            as_of_date=result.as_of_date,
            run_type=run_type,
            requested_count=result.requested_count,
            evaluated_count=result.evaluated_count,
            skipped_count=result.skipped_count,
            minimum_score=minimum_score,
            require_all_rules=require_all_rules,
            candidates=result.selected,
        )

    def get_latest(self, *, exchange_code: str) -> tuple[CandidateRun, list[CandidateResult]] | None:
        run = self._repository.get_latest_run(exchange_code=exchange_code.upper())
        if run is None:
            return None
        return run, self._repository.get_results(run.run_id)
