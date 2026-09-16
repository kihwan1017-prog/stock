"""STEP 11-5 — AI Execution Service (create / dry-run / execute / cancel / query)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.execution.constants import (
    BLOCKED_TASK_TYPES,
    DEFAULT_LEASE_SECONDS,
    EXECUTABLE_TASK_TYPES,
    MAX_INPUT_CHARS,
    MAX_RETRY_ATTEMPTS,
    MAX_TOTAL_PROVIDER_CALLS,
    TERMINAL_REQUEST,
    ExecutionMode,
    RequestStatus,
)
from stock_platform.ai.execution.entities import (
    AIExecutionEventEntity,
    AIExecutionRequestEntity,
    AIExecutionResultEntity,
    AIExecutionRunEntity,
)
from stock_platform.ai.execution.state_machine import (
    InvalidStateTransition,
    assert_request_transition,
)
from stock_platform.ai.prompt.injection import inspect_text_security
from stock_platform.ai.providers.security import sanitize_for_log


class AIExecutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AIExecutionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _event(
        self,
        request_id: int,
        *,
        event_type: str,
        actor: str,
        previous: str | None = None,
        new: str | None = None,
        run_id: int | None = None,
        detail: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._session.add(
            AIExecutionEventEntity(
                execution_request_id=request_id,
                execution_run_id=run_id,
                event_type=event_type,
                previous_status=previous,
                new_status=new,
                detail_sanitized=sanitize_for_log(detail or {}),
                correlation_id=correlation_id,
                created_by=actor,
            )
        )

    def _transition(
        self,
        row: AIExecutionRequestEntity,
        target: str,
        *,
        actor: str,
        event_type: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        prev = row.status
        try:
            assert_request_transition(prev, target)
        except InvalidStateTransition as exc:
            raise AIExecutionError(
                "INVALID_STATE_TRANSITION", str(exc)
            ) from exc
        row.status = target
        row.lock_version = int(row.lock_version) + 1
        row.updated_at = _now()
        self._event(
            row.execution_request_id,
            event_type=event_type,
            actor=actor,
            previous=prev,
            new=target,
            detail=detail,
            correlation_id=row.correlation_id,
        )

    def _public_request(self, row: AIExecutionRequestEntity) -> dict[str, Any]:
        return {
            "id": row.execution_request_id,
            "request_key": row.request_key,
            "idempotency_key": row.idempotency_key,
            "task_type": row.task_type,
            "status": row.status,
            "execution_mode": row.execution_mode,
            "provider_code": row.provider_code,
            "requested_model": row.requested_model,
            "prompt_template_id": row.prompt_template_id,
            "prompt_version_id": row.prompt_version_id,
            "output_schema_id": row.output_schema_id,
            "max_tokens": row.max_tokens,
            "timeout_sec": row.timeout_sec,
            "fallback_enabled": row.fallback_enabled,
            "retry_max": row.retry_max,
            "budget_limit": row.budget_limit,
            "estimated_max_cost": row.estimated_max_cost,
            "currency": row.currency,
            "requested_by": row.requested_by,
            "reason": row.reason,
            "correlation_id": row.correlation_id,
            "input_hash": row.input_hash,
            "rendered_prompt_hash": row.rendered_prompt_hash,
            "lock_version": row.lock_version,
            "sanitized_error": row.sanitized_error,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": (
                row.completed_at.isoformat() if row.completed_at else None
            ),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            # 원문 Prompt/Response 미포함
        }

    def create_request(
        self,
        *,
        actor: str,
        reason: str,
        task_type: str,
        execution_mode: str,
        idempotency_key: str,
        input_payload: dict[str, Any] | None = None,
        provider_code: str | None = None,
        requested_model: str | None = None,
        prompt_template_id: int | None = None,
        prompt_version_id: int | None = None,
        output_schema_id: int | None = None,
        policy_ids: list[int] | None = None,
        max_tokens: int = 256,
        temperature: float = 0.2,
        timeout_sec: float = 30.0,
        fallback_enabled: bool = False,
        retry_max: int = 1,
        budget_limit: float | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIExecutionError("REASON_REQUIRED", "reason required")
        if not idempotency_key.strip():
            raise AIExecutionError("IDEMPOTENCY_REQUIRED", "idempotency_key required")
        if task_type in BLOCKED_TASK_TYPES:
            raise AIExecutionError(
                "AI_TASK_EXECUTION_NOT_ENABLED",
                f"Task {task_type} execution is not enabled",
            )
        if task_type not in EXECUTABLE_TASK_TYPES:
            raise AIExecutionError("INVALID_TASK_TYPE", "Unsupported task type")
        if execution_mode not in {m.value for m in ExecutionMode}:
            raise AIExecutionError("INVALID_MODE", "bad execution_mode")
        if max_tokens < 1 or max_tokens > 4096:
            raise AIExecutionError("INVALID_MAX_TOKENS", "max_tokens out of range")
        if retry_max < 0 or retry_max > MAX_RETRY_ATTEMPTS:
            raise AIExecutionError("INVALID_RETRY", "retry_max too high")

        existing = self._session.scalar(
            select(AIExecutionRequestEntity).where(
                AIExecutionRequestEntity.requested_by == actor,
                AIExecutionRequestEntity.idempotency_key == idempotency_key.strip(),
            )
        )
        if existing is not None:
            return {
                "request": self._public_request(existing),
                "idempotent_replay": True,
            }

        payload = input_payload or {}
        dumped = json.dumps(payload, ensure_ascii=False, default=str)
        if len(dumped) > MAX_INPUT_CHARS:
            raise AIExecutionError("INPUT_TOO_LARGE", "input exceeds limit")
        sec = inspect_text_security(dumped)
        if sec["secrets_detected"] or sec["blocked"]:
            raise AIExecutionError(
                "INPUT_POLICY_BLOCKED",
                "Input failed security inspection",
            )

        # 모드별 provider 기본값
        mode = ExecutionMode(execution_mode)
        if mode == ExecutionMode.MOCK and not provider_code:
            provider_code = "mock"
        if mode == ExecutionMode.EXTERNAL and not provider_code:
            raise AIExecutionError(
                "PROVIDER_REQUIRED", "EXTERNAL mode requires provider_code"
            )
        if mode == ExecutionMode.EXTERNAL and provider_code == "mock":
            raise AIExecutionError(
                "INVALID_PROVIDER", "EXTERNAL mode cannot use mock"
            )

        request_key = uuid.uuid4().hex
        row = AIExecutionRequestEntity(
            request_key=request_key,
            idempotency_key=idempotency_key.strip()[:64],
            task_type=task_type,
            status=RequestStatus.READY.value,
            execution_mode=mode.value,
            provider_code=provider_code,
            requested_model=requested_model,
            prompt_template_id=prompt_template_id,
            prompt_version_id=prompt_version_id,
            output_schema_id=output_schema_id,
            policy_ids=policy_ids or [],
            input_meta={
                "keys": sorted(list(payload.keys()))[:50],
                "size": len(dumped),
                "pii": sec.get("pii_detected") or [],
            },
            input_hash=_hash_payload(payload),
            input_payload_sanitized=sanitize_for_log(payload),
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_sec=float(timeout_sec),
            fallback_enabled=bool(fallback_enabled),
            retry_max=int(retry_max),
            budget_limit=budget_limit,
            requested_by=actor,
            reason=reason[:500],
            correlation_id=correlation_id or str(uuid.uuid4()),
        )
        self._session.add(row)
        self._session.flush()
        self._event(
            row.execution_request_id,
            event_type="AI_EXECUTION_CREATED",
            actor=actor,
            previous=None,
            new=row.status,
            detail={
                "task_type": task_type,
                "mode": mode.value,
                "provider": provider_code,
            },
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {
            "request": self._public_request(row),
            "idempotent_replay": False,
            "auto_executed": False,
        }

    def get_request(self, request_id: int) -> dict[str, Any]:
        row = self._session.get(AIExecutionRequestEntity, request_id)
        if row is None:
            raise AIExecutionError("NOT_FOUND", "Execution not found")
        return self._public_request(row)

    def list_requests(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIExecutionRequestEntity)
                .order_by(AIExecutionRequestEntity.execution_request_id.desc())
                .limit(max(1, min(limit, 200)))
            )
        )
        return [self._public_request(r) for r in rows]

    def list_runs(self, request_id: int) -> list[dict[str, Any]]:
        self.get_request(request_id)
        rows = list(
            self._session.scalars(
                select(AIExecutionRunEntity)
                .where(
                    AIExecutionRunEntity.execution_request_id == request_id
                )
                .order_by(AIExecutionRunEntity.attempt_no.asc())
            )
        )
        return [
            {
                "id": r.execution_run_id,
                "attempt_no": r.attempt_no,
                "provider_code": r.provider_code,
                "model": r.model,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost": r.estimated_cost,
                "cost_calculation_status": r.cost_calculation_status,
                "currency": r.currency,
                "error_code": r.error_code,
                "sanitized_error": r.sanitized_error,
                "retry_reason": r.retry_reason,
                "fallback_reason": r.fallback_reason,
                "finish_reason": r.finish_reason,
            }
            for r in rows
        ]

    def get_result(self, request_id: int) -> dict[str, Any] | None:
        row = self._session.scalar(
            select(AIExecutionResultEntity).where(
                AIExecutionResultEntity.execution_request_id == request_id
            )
        )
        if row is None:
            return None
        return {
            "validation_status": row.validation_status,
            "schema_version": row.schema_version,
            "result_payload": row.result_payload,
            "result_hash": row.result_hash,
            "confidence": row.confidence,
            "reasoning_summary": row.reasoning_summary,
            "warnings": row.warnings or [],
            "citations": row.citations or [],
            "policy_findings": row.policy_findings or [],
            "raw_response_retained": False,
        }

    def list_events(self, request_id: int) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIExecutionEventEntity)
                .where(
                    AIExecutionEventEntity.execution_request_id == request_id
                )
                .order_by(AIExecutionEventEntity.execution_event_id.asc())
            )
        )
        return [
            {
                "id": e.execution_event_id,
                "event_type": e.event_type,
                "previous_status": e.previous_status,
                "new_status": e.new_status,
                "detail": e.detail_sanitized,
                "created_by": e.created_by,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]

    def dashboard_stats(self) -> dict[str, Any]:
        today = _now().replace(hour=0, minute=0, second=0, microsecond=0)

        def count_status(status: str) -> int:
            return int(
                self._session.scalar(
                    select(func.count())
                    .select_from(AIExecutionRequestEntity)
                    .where(AIExecutionRequestEntity.status == status)
                )
                or 0
            )

        today_count = int(
            self._session.scalar(
                select(func.count())
                .select_from(AIExecutionRequestEntity)
                .where(AIExecutionRequestEntity.created_at >= today)
            )
            or 0
        )
        token_sum = self._session.scalar(
            select(func.coalesce(func.sum(AIExecutionRunEntity.total_tokens), 0)).where(
                AIExecutionRunEntity.created_at >= today
            )
        )
        cost_sum = self._session.scalar(
            select(
                func.coalesce(func.sum(AIExecutionRunEntity.estimated_cost), 0)
            ).where(AIExecutionRunEntity.created_at >= today)
        )
        return {
            "today_requests": today_count,
            "running": count_status(RequestStatus.RUNNING.value),
            "queued": count_status(RequestStatus.QUEUED.value),
            "succeeded": count_status(RequestStatus.SUCCEEDED.value)
            + count_status(RequestStatus.SUCCEEDED_WITH_WARNINGS.value),
            "failed": count_status(RequestStatus.FAILED.value),
            "blocked": count_status(RequestStatus.BLOCKED.value),
            "timed_out": count_status(RequestStatus.TIMED_OUT.value),
            "cancelled": count_status(RequestStatus.CANCELLED.value),
            "abandoned": count_status(RequestStatus.ABANDONED.value),
            "today_tokens": int(token_sum or 0),
            "today_estimated_cost": float(cost_sum or 0) if cost_sum else None,
            "external_calls_on_read": 0,
        }

    def cancel(
        self,
        request_id: int,
        *,
        actor: str,
        reason: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIExecutionError("REASON_REQUIRED", "reason required")
        row = self._session.get(AIExecutionRequestEntity, request_id)
        if row is None:
            raise AIExecutionError("NOT_FOUND", "Execution not found")
        if expected_version is not None and row.lock_version != expected_version:
            raise AIExecutionError("VERSION_CONFLICT", "Optimistic lock conflict")
        if row.status in TERMINAL_REQUEST:
            raise AIExecutionError(
                "ALREADY_TERMINAL", "Cannot cancel terminal request"
            )

        self._event(
            request_id,
            event_type="AI_EXECUTION_CANCEL_REQUESTED",
            actor=actor,
            previous=row.status,
            new=row.status,
            detail={"reason": reason},
            correlation_id=row.correlation_id,
        )

        if row.status in {
            RequestStatus.DRAFT.value,
            RequestStatus.READY.value,
            RequestStatus.QUEUED.value,
        }:
            self._transition(
                row,
                RequestStatus.CANCELLED.value,
                actor=actor,
                event_type="AI_EXECUTION_CANCELLED",
                detail={"immediate": True, "cost_refund": False},
            )
            row.cancelled_at = _now()
            row.completed_at = _now()
        elif row.status == RequestStatus.RUNNING.value:
            self._transition(
                row,
                RequestStatus.CANCEL_REQUESTED.value,
                actor=actor,
                event_type="AI_EXECUTION_CANCEL_REQUESTED",
                detail={"cost_may_incur": True},
            )
        else:
            raise AIExecutionError("CANCEL_NOT_ALLOWED", "Cannot cancel in this state")

        self._session.commit()
        return {
            "request": self._public_request(row),
            "cost_refund_guaranteed": False,
        }

    def acquire_lease(
        self,
        row: AIExecutionRequestEntity,
        *,
        owner: str,
        seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        now = _now()
        if row.lease_owner and row.lease_expires_at and row.lease_expires_at > now:
            if row.lease_owner != owner:
                return False
        row.lease_owner = owner
        row.lease_expires_at = now + timedelta(seconds=seconds)
        return True

    def is_cancel_requested(self, request_id: int) -> bool:
        row = self._session.get(AIExecutionRequestEntity, request_id)
        return bool(
            row
            and row.status
            in {
                RequestStatus.CANCEL_REQUESTED.value,
                RequestStatus.CANCELLED.value,
            }
        )

    def costs_summary(self) -> dict[str, Any]:
        today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        by_provider = self._session.execute(
            select(
                AIExecutionRunEntity.provider_code,
                func.count(),
                func.coalesce(func.sum(AIExecutionRunEntity.total_tokens), 0),
                func.coalesce(func.sum(AIExecutionRunEntity.estimated_cost), 0),
            )
            .where(AIExecutionRunEntity.created_at >= today)
            .group_by(AIExecutionRunEntity.provider_code)
        ).all()
        return {
            "today": [
                {
                    "provider_code": r[0],
                    "runs": int(r[1]),
                    "tokens": int(r[2] or 0),
                    "estimated_cost": float(r[3]) if r[3] else None,
                }
                for r in by_provider
            ],
            "external_calls_on_read": 0,
            "note": "Costs are estimates from operator pricing; not live billing.",
        }
