"""STEP 11-10 — Consensus 멤버 적격성 (trading/order import 금지)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.entities import AICandidateAssessmentEntity
from stock_platform.ai.candidate_consensus.constants import (
    EXCLUDED_ASSESSMENT_STATUSES,
    INCLUDABLE_ASSESSMENT_STATUSES,
    MAX_MEMBERS,
    MIN_MEMBERS,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.prompt.entities import AIOutputSchemaEntity


def _parse_major(version: str | None) -> str | None:
    if not version:
        return None
    return version.split(".", maxsplit=1)[0]


class AIConsensusEligibilityService:
    """여러 Assessment를 Consensus 멤버로 선별."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def select_members(
        self,
        assessment_ids: list[int],
        *,
        require_reviewed_members: bool = False,
    ) -> dict[str, Any]:
        if not assessment_ids:
            return self._empty_result(
                warnings=["EMPTY_ASSESSMENT_IDS"],
                excluded=[
                    {
                        "id": None,
                        "reason": "ASSESSMENT_IDS_REQUIRED",
                    }
                ],
            )

        unique_ids = list(dict.fromkeys(int(i) for i in assessment_ids))
        rows = list(
            self._session.scalars(
                select(AICandidateAssessmentEntity).where(
                    AICandidateAssessmentEntity.assessment_id.in_(unique_ids)
                )
            ).all()
        )
        by_id = {r.assessment_id: r for r in rows}

        included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        warnings: list[str] = []

        for aid in unique_ids:
            row = by_id.get(aid)
            if row is None:
                excluded.append({"id": aid, "reason": "NOT_FOUND"})
                continue

            status = row.assessment_status
            if status in EXCLUDED_ASSESSMENT_STATUSES:
                excluded.append({"id": aid, "reason": f"STATUS_{status}"})
                continue
            if status not in INCLUDABLE_ASSESSMENT_STATUSES:
                excluded.append({"id": aid, "reason": f"STATUS_{status}"})
                continue

            review = row.review_decision
            if require_reviewed_members and review not in {
                "APPROVED",
                "APPROVED_WITH_WARNINGS",
            }:
                excluded.append({"id": aid, "reason": "REVIEW_REQUIRED"})
                continue

            included.append(self._member_snapshot(row))

        if len(included) > MAX_MEMBERS:
            overflow = included[MAX_MEMBERS:]
            included = included[:MAX_MEMBERS]
            for item in overflow:
                excluded.append({"id": item["assessment_id"], "reason": "MAX_MEMBERS"})
            warnings.append(f"TRUNCATED_TO_{MAX_MEMBERS}")

        if len(included) < MIN_MEMBERS:
            warnings.append(f"INSUFFICIENT_MEMBERS:{len(included)}")

        instrument_meta: dict[str, Any] | None = None
        evidence_bundle_hash: str | None = None

        if included:
            first = included[0]
            instrument_meta = {
                "market_type": first["market_type"],
                "exchange_code": first["exchange_code"],
                "symbol": first["symbol"],
                "instrument_id": first.get("instrument_id"),
                "instrument_key": first.get("instrument_key"),
                "assessment_type": first.get("assessment_type"),
            }
            evidence_bundle_hash = first.get("evidence_bundle_hash")

            ref_market = first["market_type"]
            ref_exchange = first["exchange_code"]
            ref_symbol = first["symbol"]
            ref_instrument_key = first.get("instrument_key")
            ref_evidence = first.get("evidence_bundle_hash")
            ref_schema_id = first.get("output_schema_id")
            ref_schema_major = self._load_schema_major(ref_schema_id)

            for item in included[1:]:
                same_instrument = (
                    item.get("instrument_key") == ref_instrument_key
                    or (
                        item["exchange_code"] == ref_exchange
                        and item["symbol"] == ref_symbol
                    )
                )
                if not same_instrument:
                    excluded.append(
                        {
                            "id": item["assessment_id"],
                            "reason": "INSTRUMENT_MISMATCH",
                        }
                    )
                    included = [
                        x
                        for x in included
                        if x["assessment_id"] != item["assessment_id"]
                    ]
                    continue

                if item["market_type"] != ref_market:
                    excluded.append(
                        {
                            "id": item["assessment_id"],
                            "reason": "MARKET_TYPE_MISMATCH",
                        }
                    )
                    included = [
                        x
                        for x in included
                        if x["assessment_id"] != item["assessment_id"]
                    ]
                    continue

                if ref_evidence and item.get("evidence_bundle_hash") != ref_evidence:
                    excluded.append(
                        {
                            "id": item["assessment_id"],
                            "reason": "EVIDENCE_BUNDLE_MISMATCH",
                        }
                    )
                    included = [
                        x
                        for x in included
                        if x["assessment_id"] != item["assessment_id"]
                    ]
                    continue

                other_schema_id = item.get("output_schema_id")
                if other_schema_id != ref_schema_id:
                    other_major = self._load_schema_major(other_schema_id)
                    if (
                        ref_schema_major
                        and other_major
                        and ref_schema_major != other_major
                    ):
                        warnings.append(
                            f"SCHEMA_MAJOR_MISMATCH:{ref_schema_id}:{other_schema_id}"
                        )
                    else:
                        warnings.append(
                            f"OUTPUT_SCHEMA_DIFF:{ref_schema_id}:{other_schema_id}"
                        )

            if len(included) < MIN_MEMBERS:
                warnings.append(f"INSUFFICIENT_MEMBERS_AFTER_FILTER:{len(included)}")

            if included:
                evidence_bundle_hash = included[0].get("evidence_bundle_hash")

        return {
            "included": included,
            "excluded": excluded,
            "warnings": warnings,
            "instrument": instrument_meta,
            "evidence_bundle_hash": evidence_bundle_hash,
            "eligible": len(included) >= MIN_MEMBERS,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def _load_schema_major(self, schema_id: int | None) -> str | None:
        if schema_id is None:
            return None
        row = self._session.get(AIOutputSchemaEntity, schema_id)
        if row is None:
            return None
        return _parse_major(row.schema_version)

    @staticmethod
    def _member_snapshot(row: AICandidateAssessmentEntity) -> dict[str, Any]:
        safe = row.safe_result or {}
        result_body = (
            safe.get("result") if isinstance(safe.get("result"), dict) else safe
        ) or {}
        return {
            "assessment_id": row.assessment_id,
            "assessment_type": row.assessment_type,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "instrument_id": row.instrument_id,
            "instrument_key": row.instrument_key,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "output_schema_id": row.output_schema_id,
            "provider_code": row.provider_code,
            "model": row.model,
            "assessment_status": row.assessment_status,
            "review_decision": row.review_decision,
            "analytical_score": row.analytical_score,
            "risk_score": row.risk_score,
            "confidence": row.confidence,
            "result_hash": row.result_hash,
            "conflict_status": row.conflict_status,
            "data_quality": row.data_quality,
            "evidence_quality": row.evidence_quality,
            "safe_result": safe,
            "result_body": result_body,
        }

    @staticmethod
    def _empty_result(
        *,
        warnings: list[str],
        excluded: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "included": [],
            "excluded": excluded,
            "warnings": warnings,
            "instrument": None,
            "evidence_bundle_hash": None,
            "eligible": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
