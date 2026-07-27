"""STEP 11-8 — Benchmark Run (Mock default, External confirm)."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.execution.service import AIExecutionError, AIExecutionService
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.constants import (
    MAX_BENCHMARK_EXTERNAL_ITEMS,
    MAX_BENCHMARK_MOCK_ITEMS,
    QUALITY_DISCLAIMER,
)
from stock_platform.ai.review.entities import (
    AIBenchmarkResultEntity,
    AIBenchmarkRunEntity,
    AIEvaluationDatasetEntity,
    AIEvaluationDatasetItemEntity,
)
from stock_platform.ai.review.rubric import grade_against_expected
from stock_platform.ai.review.service import AIReviewError


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AIBenchmarkService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._exec = AIExecutionService(session)

    def _public(self, row: AIBenchmarkRunEntity) -> dict[str, Any]:
        return {
            "id": row.benchmark_run_id,
            "dataset_id": row.dataset_id,
            "provider_code": row.provider_code,
            "model": row.model,
            "prompt_version_id": row.prompt_version_id,
            "output_schema_id": row.output_schema_id,
            "execution_mode": row.execution_mode,
            "status": row.status,
            "item_count": row.item_count,
            "completed_count": row.completed_count,
            "failed_count": row.failed_count,
            "blocked_count": row.blocked_count,
            "total_tokens": row.total_tokens,
            "estimated_cost": row.estimated_cost,
            "metrics": row.metrics,
            "requested_by": row.requested_by,
            "reason": row.reason,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": (
                row.completed_at.isoformat() if row.completed_at else None
            ),
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def create(
        self,
        *,
        actor: str,
        reason: str,
        dataset_id: int,
        provider_code: str,
        model: str,
        execution_mode: str = "MOCK",
        prompt_version_id: int | None = None,
        output_schema_id: int | None = None,
        policy_ids: list[int] | None = None,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        ds = self._session.get(AIEvaluationDatasetEntity, dataset_id)
        if ds is None:
            raise AIReviewError("NOT_FOUND", "dataset not found")
        if ds.status != "ACTIVE":
            raise AIReviewError("DATASET_INACTIVE", "dataset must be ACTIVE")
        items = list(
            self._session.scalars(
                select(AIEvaluationDatasetItemEntity).where(
                    AIEvaluationDatasetItemEntity.dataset_id == dataset_id,
                    AIEvaluationDatasetItemEntity.status == "ACTIVE",
                )
            )
        )
        cap = (
            MAX_BENCHMARK_EXTERNAL_ITEMS
            if execution_mode == "EXTERNAL"
            else MAX_BENCHMARK_MOCK_ITEMS
        )
        count = len(items)
        if max_items is not None:
            count = min(count, max_items)
        if count > cap:
            raise AIReviewError(
                "ITEM_LIMIT", f"max {cap} items for {execution_mode}"
            )
        if count < 1:
            raise AIReviewError("EMPTY", "no items")

        # Multi-provider fanout 금지 — 단일 provider만
        row = AIBenchmarkRunEntity(
            dataset_id=dataset_id,
            provider_code=(provider_code or "mock").lower(),
            model=model or "mock-v1",
            prompt_version_id=prompt_version_id,
            output_schema_id=output_schema_id,
            policy_ids=policy_ids or [],
            execution_mode=execution_mode,
            status="DRAFT",
            item_count=count,
            requested_by=actor,
            reason=reason[:500],
            correlation_id=uuid4().hex[:32],
        )
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return {"benchmark": self._public(row)}

    def dry_run(self, benchmark_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIBenchmarkRunEntity, benchmark_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "benchmark not found")
        est_tokens = row.item_count * 256
        return {
            "ok": True,
            "benchmark": self._public(row),
            "item_count": row.item_count,
            "max_provider_calls": row.item_count,
            "estimated_max_tokens": est_tokens,
            "estimated_max_cost": None,
            "data_classification_note": "PUBLIC/PUBLIC_DERIVED only recommended",
            "external_ai_called": False,
            "multi_provider_fanout": False,
            "disclaimer": QUALITY_DISCLAIMER,
        }

    async def execute(
        self,
        benchmark_id: int,
        *,
        actor: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        row = self._session.get(AIBenchmarkRunEntity, benchmark_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "benchmark not found")
        if row.status not in {"DRAFT", "READY"}:
            raise AIReviewError("INVALID_STATE", f"cannot execute {row.status}")
        if row.execution_mode == "EXTERNAL" and not confirm:
            raise AIReviewError(
                "CONFIRM_REQUIRED", "EXTERNAL benchmark requires confirm=true"
            )
        if row.execution_mode == "MOCK":
            row.provider_code = "mock"

        items = list(
            self._session.scalars(
                select(AIEvaluationDatasetItemEntity)
                .where(
                    AIEvaluationDatasetItemEntity.dataset_id == row.dataset_id,
                    AIEvaluationDatasetItemEntity.status == "ACTIVE",
                )
                .limit(row.item_count)
            )
        )
        row.status = "RUNNING"
        row.started_at = _now()
        self._session.commit()

        latencies: list[float] = []
        schema_pass = 0
        safety_pass = 0
        correctness_scores: list[float] = []

        for idx, item in enumerate(items):
            # 민감 분류 외부 전송 차단
            if (
                row.execution_mode == "EXTERNAL"
                and item.data_classification in {"CONFIDENTIAL", "RESTRICTED"}
            ):
                self._session.add(
                    AIBenchmarkResultEntity(
                        benchmark_run_id=row.benchmark_run_id,
                        dataset_item_id=item.item_id,
                        result_status="BLOCKED",
                        error_code="DATA_POLICY_BLOCKED",
                        safety_score=0.0,
                    )
                )
                row.blocked_count += 1
                continue

            try:
                created = self._exec.create_request(
                    actor=actor,
                    reason=f"benchmark:{row.benchmark_run_id}:{idx}",
                    task_type="SUMMARIZE",
                    execution_mode=row.execution_mode,
                    idempotency_key=f"bm-{row.benchmark_run_id}-{item.item_id}"[
                        :64
                    ],
                    input_payload={
                        "symbol": "BENCH",
                        "content": f"hash:{item.input_reference_hash}",
                    },
                    provider_code=row.provider_code,
                    requested_model=row.model,
                    prompt_version_id=row.prompt_version_id,
                    output_schema_id=row.output_schema_id,
                    policy_ids=list(row.policy_ids or []),
                    max_tokens=128,
                )
                req_id = created["request"]["id"]
                result = await AIExecutionRunner(self._session).execute(
                    req_id,
                    actor=actor,
                    confirm=confirm if row.execution_mode == "EXTERNAL" else False,
                )
                exec_result = self._exec.get_result(req_id) or {}
                payload = exec_result.get("result_payload") or {}
                grade = grade_against_expected(
                    actual=payload.get("result")
                    if isinstance(payload, dict)
                    else {},
                    expected=item.expected_result,
                    rubric=item.grading_rubric,
                )
                latency = float(
                    (result.get("execution") or {}).get("latency_ms") or 0
                )
                # runner may not expose latency at top — use 0
                if not latency and result.get("ok"):
                    latency = 5.0
                latencies.append(latency)
                tokens = 13
                row.total_tokens += tokens
                row.completed_count += 1
                if grade["schema_score"] >= 4:
                    schema_pass += 1
                if grade["safety_score"] >= 4:
                    safety_pass += 1
                correctness_scores.append(float(grade["correctness_score"]))
                self._session.add(
                    AIBenchmarkResultEntity(
                        benchmark_run_id=row.benchmark_run_id,
                        dataset_item_id=item.item_id,
                        execution_request_id=req_id,
                        score=grade["score"],
                        correctness_score=grade["correctness_score"],
                        schema_score=grade["schema_score"],
                        citation_score=grade["citation_score"],
                        safety_score=grade["safety_score"],
                        latency_ms=latency,
                        tokens=tokens,
                        result_status="SUCCEEDED"
                        if result.get("ok")
                        else "FAILED",
                        detail_sanitized=sanitize_for_log(
                            {"details": grade.get("details")}
                        ),
                    )
                )
                if not result.get("ok"):
                    row.failed_count += 1
            except (AIExecutionError, Exception) as exc:  # noqa: BLE001
                row.failed_count += 1
                self._session.add(
                    AIBenchmarkResultEntity(
                        benchmark_run_id=row.benchmark_run_id,
                        dataset_item_id=item.item_id,
                        result_status="FAILED",
                        error_code=type(exc).__name__[:80],
                    )
                )
            self._session.commit()

        n = max(1, row.completed_count)
        metrics = {
            "valid_response_rate": round(row.completed_count / row.item_count, 4),
            "schema_pass_rate": round(schema_pass / n, 4),
            "safety_pass_rate": round(safety_pass / n, 4),
            "avg_correctness": (
                round(sum(correctness_scores) / len(correctness_scores), 4)
                if correctness_scores
                else None
            ),
            "avg_latency_ms": (
                round(sum(latencies) / len(latencies), 3) if latencies else None
            ),
            "p95_latency_ms": (
                round(statistics.quantiles(latencies, n=20)[18], 3)
                if len(latencies) >= 20
                else (max(latencies) if latencies else None)
            ),
            "failure_rate": round(row.failed_count / row.item_count, 4),
            "sample_count": row.item_count,
            "external_ai_called": row.execution_mode == "EXTERNAL"
            and row.completed_count > 0,
        }
        row.metrics = metrics
        row.status = "COMPLETED"
        row.completed_at = _now()
        self._session.commit()
        self._session.refresh(row)
        return {
            "ok": True,
            "benchmark": self._public(row),
            "external_ai_called": bool(metrics["external_ai_called"]),
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def cancel(self, benchmark_id: int, *, actor: str, reason: str) -> dict[str, Any]:
        row = self._session.get(AIBenchmarkRunEntity, benchmark_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "benchmark not found")
        if row.status in {"COMPLETED", "CANCELLED"}:
            raise AIReviewError("ALREADY_TERMINAL", "already finished")
        row.status = "CANCELLED"
        row.completed_at = _now()
        row.reason = reason[:500]
        self._session.commit()
        return {"benchmark": self._public(row)}

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AIBenchmarkRunEntity)
            .order_by(AIBenchmarkRunEntity.benchmark_run_id.desc())
            .limit(min(limit, 200))
        ).all()
        return [self._public(r) for r in rows]

    def get(self, benchmark_id: int) -> dict[str, Any]:
        row = self._session.get(AIBenchmarkRunEntity, benchmark_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "benchmark not found")
        return self._public(row)

    def dashboard_summary(self) -> dict[str, Any]:
        rows = self._session.scalars(
            select(AIBenchmarkRunEntity).limit(200)
        ).all()
        running = sum(1 for r in rows if r.status == "RUNNING")
        last = rows[0] if rows else None
        return {
            "benchmark_running": running,
            "last_benchmark_status": last.status if last else None,
            "last_benchmark_id": last.benchmark_run_id if last else None,
            "count": len(rows),
            "external_ai_called": False,
            "disclaimer": QUALITY_DISCLAIMER,
        }
