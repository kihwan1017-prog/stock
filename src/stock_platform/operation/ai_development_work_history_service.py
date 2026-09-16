"""Development work history — FAIL-OPEN (REAL trading 중단 금지)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from stock_platform.operation.ai_development_work_history_entities import (
    AiDevelopmentWorkHistory,
)

logger = structlog.get_logger(__name__)

DuplicateVerdict = Literal[
    "DUPLICATE_COMPLETED",
    "RELATED_COMPLETED",
    "RELATED_DEFERRED",
    "NEW_WORK",
]

_SECRET_PATTERNS = [
    re.compile(
        r"(?i)(api[_-]?key|secret|token|password|credential|authorization)\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-+/=]{8,}"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mask_secrets_in_command(text: str | None) -> str | None:
    if not text:
        return text
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(0).split("=")[0] + "=***" if "=" in m.group(0) else "***", out)
    return out


def normalize_command(text: str | None) -> str:
    if not text:
        return ""
    masked = mask_secrets_in_command(text) or ""
    return "\n".join(line.rstrip() for line in masked.strip().splitlines())


def hash_command(text: str | None) -> str | None:
    norm = normalize_command(text)
    if not norm:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _row_to_dict(row: AiDevelopmentWorkHistory) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "work_id": row.work_id,
        "parent_work_id": row.parent_work_id,
        "project_code": row.project_code,
        "work_type": row.work_type,
        "title": row.title,
        "objective": row.objective,
        "request_source": row.request_source,
        "executor": row.executor,
        "status": row.status,
        "command_text": row.command_text,
        "scope_json": row.scope_json,
        "safety_constraints_json": row.safety_constraints_json,
        "root_cause": row.root_cause,
        "final_verdict": row.final_verdict,
        "result_summary": row.result_summary,
        "base_commit": row.base_commit,
        "result_commit": row.result_commit,
        "changed_files_json": row.changed_files_json,
        "tests_json": row.tests_json,
        "deployment_json": row.deployment_json,
        "safety_result_json": row.safety_result_json,
        "evidence_json": row.evidence_json,
        "remaining_issues_json": row.remaining_issues_json,
        "next_action": row.next_action,
        "command_hash": row.command_hash,
        "dedupe_key": row.dedupe_key,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class DevelopmentWorkHistoryService:
    """개발 작업 이력 — trading path와 분리, 저장 실패는 fail-open."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_work(self, work_id: str) -> dict[str, Any] | None:
        row = self._session.scalar(
            select(AiDevelopmentWorkHistory).where(
                AiDevelopmentWorkHistory.work_id == str(work_id)
            )
        )
        return _row_to_dict(row) if row else None

    def create_work(
        self,
        *,
        work_id: str,
        project_code: str,
        work_type: str,
        title: str,
        status: str = "REQUESTED",
        parent_work_id: str | None = None,
        objective: str | None = None,
        request_source: str | None = None,
        executor: str | None = None,
        command_text: str | None = None,
        scope_json: dict[str, Any] | None = None,
        safety_constraints_json: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        base_commit: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        existing = self.get_work(work_id)
        if existing:
            return {**existing, "idempotent": True, "action": "ALREADY_EXISTS"}

        masked_cmd = mask_secrets_in_command(command_text)
        now = _now()
        row = AiDevelopmentWorkHistory(
            work_id=str(work_id),
            parent_work_id=parent_work_id,
            project_code=str(project_code),
            work_type=str(work_type),
            title=str(title),
            objective=objective,
            request_source=request_source,
            executor=executor,
            status=str(status),
            command_text=masked_cmd,
            scope_json=scope_json,
            safety_constraints_json=safety_constraints_json,
            dedupe_key=dedupe_key,
            base_commit=base_commit,
            command_hash=hash_command(command_text),
            created_at=now,
            updated_at=now,
            started_at=now if status == "RUNNING" else None,
        )
        for key in (
            "root_cause",
            "final_verdict",
            "result_summary",
            "result_commit",
            "changed_files_json",
            "tests_json",
            "deployment_json",
            "safety_result_json",
            "evidence_json",
            "remaining_issues_json",
            "next_action",
        ):
            if key in extra:
                setattr(row, key, extra[key])
        self._session.add(row)
        self._session.flush()
        return _row_to_dict(row)

    def start_work(self, work_id: str) -> dict[str, Any] | None:
        row = self._session.scalar(
            select(AiDevelopmentWorkHistory).where(
                AiDevelopmentWorkHistory.work_id == str(work_id)
            )
        )
        if row is None:
            return None
        row.status = "RUNNING"
        row.started_at = row.started_at or _now()
        row.updated_at = _now()
        self._session.flush()
        return _row_to_dict(row)

    def complete_work(self, work_id: str, **fields: Any) -> dict[str, Any] | None:
        return self._finalize(work_id, status="COMPLETED", **fields)

    def fail_work(self, work_id: str, **fields: Any) -> dict[str, Any] | None:
        return self._finalize(work_id, status="FAILED", **fields)

    def defer_work(self, work_id: str, **fields: Any) -> dict[str, Any] | None:
        return self._finalize(work_id, status="DEFERRED", **fields)

    def _finalize(
        self, work_id: str, *, status: str, **fields: Any
    ) -> dict[str, Any] | None:
        row = self._session.scalar(
            select(AiDevelopmentWorkHistory).where(
                AiDevelopmentWorkHistory.work_id == str(work_id)
            )
        )
        if row is None:
            return None
        row.status = status
        row.completed_at = _now()
        row.updated_at = _now()
        if "command_text" in fields:
            fields["command_text"] = mask_secrets_in_command(fields["command_text"])
            fields["command_hash"] = hash_command(fields.get("command_text"))
        for key, val in fields.items():
            if hasattr(row, key):
                setattr(row, key, val)
        self._session.flush()
        return _row_to_dict(row)

    def list_recent_work(
        self,
        *,
        project_code: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        q = select(AiDevelopmentWorkHistory).order_by(
            desc(AiDevelopmentWorkHistory.created_at)
        )
        if project_code:
            q = q.where(AiDevelopmentWorkHistory.project_code == project_code)
        rows = self._session.scalars(q.limit(max(1, min(limit, 200)))).all()
        return [_row_to_dict(r) for r in rows]

    def find_related_work(
        self,
        *,
        project_code: str | None = None,
        work_type: str | None = None,
        dedupe_key: str | None = None,
        keywords: str | None = None,
        result_commit: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = select(AiDevelopmentWorkHistory)
        if project_code:
            q = q.where(AiDevelopmentWorkHistory.project_code == project_code)
        if work_type:
            q = q.where(AiDevelopmentWorkHistory.work_type == work_type)
        if dedupe_key:
            q = q.where(AiDevelopmentWorkHistory.dedupe_key == dedupe_key)
        if result_commit:
            q = q.where(AiDevelopmentWorkHistory.result_commit == result_commit)
        if keywords:
            like = f"%{keywords}%"
            q = q.where(
                or_(
                    AiDevelopmentWorkHistory.title.ilike(like),
                    AiDevelopmentWorkHistory.objective.ilike(like),
                    AiDevelopmentWorkHistory.command_text.ilike(like),
                )
            )
        rows = self._session.scalars(
            q.order_by(desc(AiDevelopmentWorkHistory.created_at)).limit(limit)
        ).all()
        return [_row_to_dict(r) for r in rows]

    def find_duplicate_work(
        self,
        *,
        project_code: str,
        work_type: str,
        dedupe_key: str | None = None,
        command_text: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        cmd_hash = hash_command(command_text)
        related = self.find_related_work(
            project_code=project_code,
            work_type=work_type,
            dedupe_key=dedupe_key,
            limit=10,
        )
        if not related and cmd_hash:
            related = self._session.scalars(
                select(AiDevelopmentWorkHistory)
                .where(
                    AiDevelopmentWorkHistory.project_code == project_code,
                    AiDevelopmentWorkHistory.command_hash == cmd_hash,
                )
                .order_by(desc(AiDevelopmentWorkHistory.created_at))
                .limit(5)
            ).all()
            related = [_row_to_dict(r) for r in related]

        completed = [r for r in related if r.get("status") == "COMPLETED"]
        deferred = [r for r in related if r.get("status") == "DEFERRED"]

        if completed and dedupe_key:
            return {
                "verdict": "DUPLICATE_COMPLETED",
                "existing_work_id": completed[0]["work_id"],
                "existing": completed[0],
            }
        if completed:
            return {
                "verdict": "RELATED_COMPLETED",
                "existing_work_id": completed[0]["work_id"],
                "existing": completed[0],
            }
        if deferred:
            return {
                "verdict": "RELATED_DEFERRED",
                "existing_work_id": deferred[0]["work_id"],
                "existing": deferred[0],
            }
        return {"verdict": "NEW_WORK", "existing_work_id": None, "existing": None}


def upsert_work_from_record(session: Session, record: dict[str, Any]) -> dict[str, Any]:
    """JSON agent_work_record → DB (idempotent by work_id)."""

    svc = DevelopmentWorkHistoryService(session)
    work_id = str(record["work_id"])
    existing = svc.get_work(work_id)
    payload = {
        "parent_work_id": record.get("parent_work_id"),
        "project_code": record.get("project_code", "stock-platform"),
        "work_type": record["work_type"],
        "title": record["title"],
        "objective": record.get("objective"),
        "request_source": record.get("request_source"),
        "executor": record.get("executor"),
        "command_text": record.get("command_text"),
        "scope_json": record.get("scope_json"),
        "safety_constraints_json": record.get("safety_constraints_json"),
        "root_cause": record.get("root_cause"),
        "final_verdict": record.get("final_verdict"),
        "result_summary": record.get("result_summary"),
        "base_commit": record.get("base_commit"),
        "result_commit": record.get("result_commit"),
        "changed_files_json": record.get("changed_files_json"),
        "tests_json": record.get("tests_json"),
        "deployment_json": record.get("deployment_json"),
        "safety_result_json": record.get("safety_result_json"),
        "evidence_json": record.get("evidence_json"),
        "remaining_issues_json": record.get("remaining_issues_json"),
        "next_action": record.get("next_action"),
        "dedupe_key": record.get("dedupe_key"),
    }
    if existing:
        return svc.complete_work(work_id, **payload) or existing

    status = str(record.get("status") or "COMPLETED")
    created = svc.create_work(
        work_id=work_id,
        status=status,
        **payload,
    )
    if status in {"COMPLETED", "FAILED", "DEFERRED"}:
        fn = {
            "COMPLETED": svc.complete_work,
            "FAILED": svc.fail_work,
            "DEFERRED": svc.defer_work,
        }[status]
        return fn(work_id, **{k: v for k, v in payload.items() if v is not None}) or created
    return created


def safe_work_history_call(session: Session, fn_name: str, **kwargs: Any) -> dict[str, Any]:
    """Trading path에서 호출 시 fail-open."""

    try:
        svc = DevelopmentWorkHistoryService(session)
        fn = getattr(svc, fn_name)
        result = fn(**kwargs)
        session.commit()
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("development_work_history_fail_open", fn=fn_name, error=str(exc)[:200])
        return {"ok": False, "fail_open": True, "error": str(exc)[:200]}
