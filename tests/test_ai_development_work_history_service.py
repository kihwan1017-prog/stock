"""Tests — AI development work history service."""

from __future__ import annotations

import uuid

from stock_platform.database.session import get_session_factory
from stock_platform.operation.ai_development_work_history_service import (
    DevelopmentWorkHistoryService,
    hash_command,
    mask_secrets_in_command,
    safe_work_history_call,
    upsert_work_from_record,
)


def test_mask_secrets_in_command() -> None:
    raw = "API_KEY=supersecret token=abc123 Bearer eyJhbGciOiJIUzI1NiJ9.x"
    masked = mask_secrets_in_command(raw) or ""
    assert "supersecret" not in masked
    assert "abc123" not in masked


def test_hash_command_stable() -> None:
    a = hash_command("  hello\nworld  ")
    b = hash_command("hello\nworld")
    assert a == b
    assert a and len(a) == 64


def _session():
    return get_session_factory()()


def test_create_work_idempotent() -> None:
    session = _session()
    wid = f"WRK-TEST-{uuid.uuid4().hex[:8]}"
    try:
        svc = DevelopmentWorkHistoryService(session)
        first = svc.create_work(
            work_id=wid,
            project_code="stock-platform",
            work_type="TEST",
            title="test work",
            status="COMPLETED",
            command_text="do something safe",
        )
        second = svc.create_work(
            work_id=wid,
            project_code="stock-platform",
            work_type="TEST",
            title="test work",
            status="COMPLETED",
        )
        assert first["work_id"] == wid
        assert second.get("idempotent") is True
        session.commit()
    finally:
        session.close()


def test_duplicate_detection() -> None:
    session = _session()
    wid = f"WRK-TEST-DUP-{uuid.uuid4().hex[:8]}"
    try:
        svc = DevelopmentWorkHistoryService(session)
        svc.create_work(
            work_id=wid,
            project_code="stock-platform",
            work_type="OBSERVABILITY_RELIABILITY_FIX",
            title="dup",
            status="COMPLETED",
            dedupe_key="stock-platform:UPBIT:PIPELINE_STALL:OBSERVABILITY-TEST",
        )
        session.commit()
        dup = svc.find_duplicate_work(
            project_code="stock-platform",
            work_type="OBSERVABILITY_RELIABILITY_FIX",
            dedupe_key="stock-platform:UPBIT:PIPELINE_STALL:OBSERVABILITY-TEST",
        )
        assert dup["verdict"] == "DUPLICATE_COMPLETED"
    finally:
        session.close()


def test_fail_open_safe_call() -> None:
    session = _session()
    try:
        out = safe_work_history_call(
            session, "get_work", work_id="WRK-NOT-EXISTS-XYZ"
        )
        assert out["ok"] is True
    finally:
        session.close()


def test_bootstrap_record_shape() -> None:
    session = _session()
    wid = f"WRK-TEST-BOOT-{uuid.uuid4().hex[:8]}"
    try:
        record = {
            "work_id": wid,
            "project_code": "stock-platform",
            "work_type": "TEST",
            "title": "bootstrap",
            "status": "COMPLETED",
            "final_verdict": "PASS",
        }
        row = upsert_work_from_record(session, record)
        session.commit()
        assert row["work_id"] == wid
    finally:
        session.close()
