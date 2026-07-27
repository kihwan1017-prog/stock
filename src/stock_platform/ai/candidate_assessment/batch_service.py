"""STEP 11-9 — Candidate Assessment Batch (명시적 instrument 목록만)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.constants import (
    HARD_BATCH_CAP,
    MAX_BATCH_EXTERNAL,
    MAX_BATCH_MOCK,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.candidate_assessment.service import (
    AICandidateAssessmentError,
    AICandidateAssessmentService,
)


class AICandidateAssessmentBatchService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AICandidateAssessmentService(session)

    def create_batch(
        self,
        *,
        actor: str,
        reason: str,
        market_type: str,
        exchange_code: str,
        instruments: list[dict[str, Any]],
        execution_mode: str,
        provider_code: str,
        model: str | None,
        prompt_version_id: int | None,
        include_news: bool = True,
        include_disclosure: bool = True,
        include_chart: bool = True,
        include_market: bool = True,
        require_reviewed_evidence: bool = False,
        confirm: bool,
        idempotency_key: str,
        estimated_max_tokens: int | None = None,
        estimated_max_cost: float | None = None,
    ) -> dict[str, Any]:
        if execution_mode == "EXTERNAL" and not confirm:
            raise AICandidateAssessmentError(
                "CONFIRM_REQUIRED", "external batch requires confirm=true"
            )
        if not instruments:
            raise AICandidateAssessmentError(
                "EMPTY_INSTRUMENTS", "explicit instrument list required"
            )

        cap = (
            MAX_BATCH_EXTERNAL
            if execution_mode == "EXTERNAL"
            else MAX_BATCH_MOCK
        )
        cap = min(cap, HARD_BATCH_CAP)
        if len(instruments) > cap:
            raise AICandidateAssessmentError(
                "BATCH_LIMIT", f"max {cap} instruments for {execution_mode}"
            )

        created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, inst in enumerate(instruments):
            symbol = str(inst.get("symbol") or "").strip()
            instrument_id = inst.get("instrument_id")
            if not symbol:
                errors.append(
                    {
                        "index": idx,
                        "code": "SYMBOL_REQUIRED",
                        "message": "symbol required per instrument",
                    }
                )
                continue
            try:
                item = self._svc.create(
                    actor=actor,
                    reason=reason,
                    market_type=market_type,
                    exchange_code=exchange_code,
                    symbol=symbol,
                    instrument_id=int(instrument_id)
                    if instrument_id is not None
                    else None,
                    execution_mode=execution_mode,
                    provider_code=provider_code,
                    model=model,
                    prompt_version_id=prompt_version_id,
                    include_news=include_news,
                    include_disclosure=include_disclosure,
                    include_chart=include_chart,
                    include_market=include_market,
                    require_reviewed_evidence=require_reviewed_evidence,
                    idempotency_key=f"{idempotency_key}:{idx}"[:64],
                )
                created.append(item["assessment"])
            except AICandidateAssessmentError as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "instrument_id": instrument_id,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )

        if created:
            self._svc._history(
                created[0]["id"],
                action="AI_CANDIDATE_BATCH_CREATED",
                actor=actor,
                reason=reason,
                detail={
                    "count": len(created),
                    "errors": len(errors),
                    "market_type": market_type,
                    "exchange_code": exchange_code,
                    "estimated_max_tokens": estimated_max_tokens,
                    "estimated_max_cost": estimated_max_cost,
                },
            )
            self._session.commit()

        return {
            "created_count": len(created),
            "error_count": len(errors),
            "items": created,
            "errors": errors,
            "cap": cap,
            "auto_execute": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
