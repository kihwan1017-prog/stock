"""STEP 11-8 — Evaluation Dataset Service."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.constants import QUALITY_DISCLAIMER
from stock_platform.ai.review.entities import (
    AIEvaluationDatasetEntity,
    AIEvaluationDatasetItemEntity,
)
from stock_platform.ai.review.service import AIReviewError


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AIEvaluationDatasetService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _public(self, row: AIEvaluationDatasetEntity) -> dict[str, Any]:
        item_count = len(
            list(
                self._session.scalars(
                    select(AIEvaluationDatasetItemEntity).where(
                        AIEvaluationDatasetItemEntity.dataset_id
                        == row.dataset_id,
                        AIEvaluationDatasetItemEntity.status == "ACTIVE",
                    )
                )
            )
        )
        return {
            "id": row.dataset_id,
            "code": row.code,
            "name": row.name,
            "task_type": row.task_type,
            "description": row.description,
            "status": row.status,
            "dataset_version": row.dataset_version,
            "source_policy": row.source_policy,
            "checksum": row.checksum,
            "item_count": item_count,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def create(
        self,
        *,
        actor: str,
        code: str,
        name: str,
        task_type: str,
        description: str = "",
    ) -> dict[str, Any]:
        existing = self._session.scalar(
            select(AIEvaluationDatasetEntity)
            .where(AIEvaluationDatasetEntity.code == code)
            .order_by(AIEvaluationDatasetEntity.dataset_version.desc())
            .limit(1)
        )
        version = (existing.dataset_version + 1) if existing else 1
        row = AIEvaluationDatasetEntity(
            code=code.strip()[:80],
            name=name[:200],
            task_type=task_type,
            description=description[:4000],
            status="DRAFT",
            dataset_version=version,
            created_by=actor,
        )
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return {"dataset": self._public(row)}

    def list_datasets(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AIEvaluationDatasetEntity)
            .order_by(AIEvaluationDatasetEntity.dataset_id.desc())
            .limit(min(limit, 200))
        ).all()
        return [self._public(r) for r in rows]

    def get(self, dataset_id: int) -> dict[str, Any]:
        row = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        return self._public(row)

    def update_meta(
        self,
        dataset_id: int,
        *,
        actor: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        row = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        if row.status == "ACTIVE":
            raise AIReviewError(
                "ACTIVE_IMMUTABLE",
                "ACTIVE dataset cannot be edited; create new version",
            )
        if name:
            row.name = name[:200]
        if description is not None:
            row.description = description[:4000]
        self._session.commit()
        return {"dataset": self._public(row)}

    def add_item(
        self,
        dataset_id: int,
        *,
        actor: str,
        input_reference_hash: str | None = None,
        source_analysis_id: int | None = None,
        source_document_key: str | None = None,
        snapshot_key: str | None = None,
        expected_result: dict[str, Any] | None = None,
        expected_schema_version: str | None = None,
        grading_rubric: dict[str, Any] | None = None,
        data_classification: str = "PUBLIC",
    ) -> dict[str, Any]:
        row = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        if row.status == "ACTIVE":
            raise AIReviewError(
                "ACTIVE_IMMUTABLE", "cannot add items to ACTIVE dataset"
            )
        payload = {
            "source_analysis_id": source_analysis_id,
            "source_document_key": source_document_key,
            "snapshot_key": snapshot_key,
            "expected_result": expected_result or {},
            "rubric": grading_rubric or {},
        }
        href = input_reference_hash or hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        dup = self._session.scalar(
            select(AIEvaluationDatasetItemEntity).where(
                AIEvaluationDatasetItemEntity.dataset_id == dataset_id,
                AIEvaluationDatasetItemEntity.input_reference_hash == href,
            )
        )
        if dup is not None:
            raise AIReviewError("DUPLICATE_ITEM", "item hash already exists")

        item = AIEvaluationDatasetItemEntity(
            dataset_id=dataset_id,
            source_analysis_id=source_analysis_id,
            source_document_key=source_document_key,
            snapshot_key=snapshot_key,
            input_reference_hash=href[:64],
            expected_result=sanitize_for_log(expected_result or {}),
            expected_schema_version=expected_schema_version,
            grading_rubric=sanitize_for_log(grading_rubric or {}),
            data_classification=data_classification,
            status="ACTIVE",
            created_by=actor,
        )
        self._session.add(item)
        self._session.commit()
        return {
            "item": {
                "id": item.item_id,
                "input_reference_hash": item.input_reference_hash,
                "data_classification": item.data_classification,
                "status": item.status,
            }
        }

    def validate(self, dataset_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        items = list(
            self._session.scalars(
                select(AIEvaluationDatasetItemEntity).where(
                    AIEvaluationDatasetItemEntity.dataset_id == dataset_id,
                    AIEvaluationDatasetItemEntity.status == "ACTIVE",
                )
            )
        )
        if not items:
            raise AIReviewError("EMPTY_DATASET", "no active items")
        for item in items:
            if not item.expected_result and not item.grading_rubric:
                raise AIReviewError(
                    "ITEM_INVALID",
                    f"item {item.item_id} needs expected_result or rubric",
                )
            if item.data_classification in {"CONFIDENTIAL", "RESTRICTED"}:
                # 외부 전송 금지 표시만 — validate는 통과 가능
                pass
        raw = json.dumps(
            [i.input_reference_hash for i in items], sort_keys=True
        )
        row.checksum = hashlib.sha256(raw.encode()).hexdigest()
        row.status = "VALIDATED"
        self._session.commit()
        return {"dataset": self._public(row)}

    def activate(self, dataset_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        if row.status not in {"VALIDATED", "ACTIVE"}:
            raise AIReviewError(
                "NOT_VALIDATED", "validate before activate"
            )
        row.status = "ACTIVE"
        self._session.commit()
        return {"dataset": self._public(row)}

    def archive(self, dataset_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        row.status = "ARCHIVED"
        self._session.commit()
        return {"dataset": self._public(row)}

    def list_items(self, dataset_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AIEvaluationDatasetItemEntity).where(
                AIEvaluationDatasetItemEntity.dataset_id == dataset_id
            )
        ).all()
        return [
            {
                "id": r.item_id,
                "input_reference_hash": r.input_reference_hash,
                "source_analysis_id": r.source_analysis_id,
                "data_classification": r.data_classification,
                "status": r.status,
            }
            for r in rows
        ]
