"""STEP 11-10 — Consensus Batch (명시적 instrument→assessment_ids 맵만)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_consensus.constants import (
    MAX_BATCH_DETERMINISTIC,
    MAX_BATCH_EXTERNAL_SYNTHESIS,
    MAX_BATCH_MOCK_SYNTHESIS,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.candidate_consensus.service import (
    AIConsensusError,
    AIConsensusService,
)


class AIConsensusBatchService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AIConsensusService(session)

    def create_batch(
        self,
        *,
        actor: str,
        reason: str,
        instrument_assessments: dict[str, list[int]],
        calculation_mode: str = "DETERMINISTIC_ONLY",
        require_reviewed_members: bool = False,
        synthesis_provider_code: str | None = None,
        confirm: bool = False,
        auto_calculate: bool = False,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        instrument_assessments: instrument_key → assessment_id 목록
        예: {"KRX:005930": [1, 2, 3], "UPBIT:KRW-BTC": [4, 5]}
        """

        if not instrument_assessments:
            raise AIConsensusError(
                "EMPTY_INSTRUMENTS", "explicit instrument→assessment map required"
            )

        if calculation_mode == "DETERMINISTIC_PLUS_SYNTHESIS":
            cap = MAX_BATCH_MOCK_SYNTHESIS
            # external synthesis 는 confirm 필요 — batch 단위에서는 MOCK 기본
            if synthesis_provider_code and synthesis_provider_code.lower() != "mock":
                cap = MAX_BATCH_EXTERNAL_SYNTHESIS
                if not confirm:
                    raise AIConsensusError(
                        "CONFIRM_REQUIRED",
                        "external synthesis batch requires confirm=true",
                    )
        else:
            cap = MAX_BATCH_DETERMINISTIC

        if len(instrument_assessments) > cap:
            raise AIConsensusError(
                "BATCH_LIMIT", f"max {cap} instruments for {calculation_mode}"
            )

        created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, (instrument_key, assessment_ids) in enumerate(
            instrument_assessments.items()
        ):
            if not assessment_ids:
                errors.append(
                    {
                        "instrument_key": instrument_key,
                        "code": "EMPTY_ASSESSMENTS",
                        "message": "assessment_ids required",
                    }
                )
                continue
            try:
                item = self._svc.create(
                    actor=actor,
                    reason=reason,
                    assessment_ids=assessment_ids,
                    calculation_mode=calculation_mode,
                    require_reviewed_members=require_reviewed_members,
                    synthesis_provider_code=synthesis_provider_code,
                    idempotency_key=f"{idempotency_key}:{idx}"[:64],
                )
                consensus = item["consensus"]
                if auto_calculate:
                    calc = self._svc.calculate(
                        consensus["id"],
                        actor=actor,
                        reason=f"batch calculate {instrument_key}",
                    )
                    consensus = calc["consensus"]
                created.append(
                    {
                        "instrument_key": instrument_key,
                        "consensus": consensus,
                    }
                )
            except AIConsensusError as exc:
                errors.append(
                    {
                        "instrument_key": instrument_key,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )

        if created:
            first_id = created[0]["consensus"]["id"]
            self._svc._history(
                first_id,
                action="AI_CONSENSUS_BATCH_CREATED",
                actor=actor,
                reason=reason,
                detail={
                    "count": len(created),
                    "errors": len(errors),
                    "calculation_mode": calculation_mode,
                    "auto_calculate": auto_calculate,
                },
            )
            self._session.commit()

        return {
            "created_count": len(created),
            "error_count": len(errors),
            "items": created,
            "errors": errors,
            "cap": cap,
            "auto_synthesize": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
