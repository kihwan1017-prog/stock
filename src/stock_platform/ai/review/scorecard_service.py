"""STEP 11-8 — Scorecard / Calibration (동일 Dataset 기준)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.review.constants import QUALITY_DISCLAIMER
from stock_platform.ai.review.entities import (
    AIAnalysisReviewEntity,
    AIBenchmarkResultEntity,
    AIBenchmarkRunEntity,
    AIEvaluationDatasetEntity,
)


class AIScorecardService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def scorecards(self, *, dataset_id: int | None = None) -> dict[str, Any]:
        stmt = select(AIBenchmarkRunEntity).where(
            AIBenchmarkRunEntity.status == "COMPLETED"
        )
        if dataset_id is not None:
            stmt = stmt.where(AIBenchmarkRunEntity.dataset_id == dataset_id)
        runs = self._session.scalars(
            stmt.order_by(AIBenchmarkRunEntity.benchmark_run_id.desc()).limit(100)
        ).all()
        cards = []
        for r in runs:
            ds = self._session.get(AIEvaluationDatasetEntity, r.dataset_id)
            cards.append(
                {
                    "benchmark_id": r.benchmark_run_id,
                    "dataset_id": r.dataset_id,
                    "dataset_version": ds.dataset_version if ds else None,
                    "task_type": ds.task_type if ds else None,
                    "provider_code": r.provider_code,
                    "model": r.model,
                    "prompt_version_id": r.prompt_version_id,
                    "metrics": r.metrics or {},
                    "sample_count": r.item_count,
                    "estimated_cost": r.estimated_cost,
                    "total_tokens": r.total_tokens,
                }
            )
        return {
            "items": cards,
            "auto_provider_default_change": False,
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def compare(
        self, *, left_benchmark_id: int, right_benchmark_id: int
    ) -> dict[str, Any]:
        left = self._session.get(AIBenchmarkRunEntity, left_benchmark_id)
        right = self._session.get(AIBenchmarkRunEntity, right_benchmark_id)
        if left is None or right is None:
            return {"ok": False, "code": "NOT_FOUND"}
        if left.dataset_id != right.dataset_id:
            return {
                "ok": False,
                "code": "DATASET_MISMATCH",
                "message": "Compare only same dataset version/id",
                "ranking_forbidden": True,
            }
        return {
            "ok": True,
            "left": {
                "id": left.benchmark_run_id,
                "provider": left.provider_code,
                "model": left.model,
                "metrics": left.metrics,
            },
            "right": {
                "id": right.benchmark_run_id,
                "provider": right.provider_code,
                "model": right.model,
                "metrics": right.metrics,
            },
            "same_dataset": True,
            "auto_provider_default_change": False,
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def calibration_summary(self) -> dict[str, Any]:
        """Human overall vs reviewer_confidence bucket (표본 부족 표시)."""

        reviews = list(
            self._session.scalars(
                select(AIAnalysisReviewEntity)
                .where(
                    AIAnalysisReviewEntity.status.in_(["SUBMITTED", "AMENDED"]),
                    AIAnalysisReviewEntity.overall_score.is_not(None),
                )
                .limit(500)
            )
        )
        if len(reviews) < 10:
            return {
                "status": "INSUFFICIENT_SAMPLE",
                "sample_count": len(reviews),
                "buckets": [],
                "disclaimer": QUALITY_DISCLAIMER,
            }
        buckets: dict[str, list[float]] = {
            "low": [],
            "mid": [],
            "high": [],
        }
        for r in reviews:
            conf = float(r.reviewer_confidence or r.overall_score or 0)
            overall = float(r.overall_score or 0)
            if conf < 2:
                buckets["low"].append(overall)
            elif conf < 4:
                buckets["mid"].append(overall)
            else:
                buckets["high"].append(overall)
        return {
            "status": "OK",
            "sample_count": len(reviews),
            "buckets": {
                k: {
                    "count": len(v),
                    "avg_correctness": round(sum(v) / len(v), 4) if v else None,
                }
                for k, v in buckets.items()
            },
            "disclaimer": QUALITY_DISCLAIMER,
        }
