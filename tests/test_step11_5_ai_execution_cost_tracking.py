"""STEP 11-5 AI Execution / Cost tracking tests (Mock only, no live AI)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.execution.constants import (
    BLOCKED_TASK_TYPES,
    EXECUTABLE_TASK_TYPES,
    RequestStatus,
)
from stock_platform.ai.execution.cost_service import calculate_cost
from stock_platform.ai.execution.state_machine import (
    InvalidStateTransition,
    assert_request_transition,
)


def test_executable_and_blocked_tasks() -> None:
    assert "CHAT" in EXECUTABLE_TASK_TYPES
    assert "SUMMARIZE" in EXECUTABLE_TASK_TYPES
    assert "NEWS_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "DISCLOSURE_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "CHART_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "MARKET_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "STRATEGY_DRAFT" in BLOCKED_TASK_TYPES
    assert "STOCK_CANDIDATE_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "CRYPTO_CANDIDATE_ANALYSIS" in EXECUTABLE_TASK_TYPES


def test_state_machine_blocks_reverse() -> None:
    assert_request_transition("READY", "RUNNING")
    with pytest.raises(InvalidStateTransition):
        assert_request_transition("SUCCEEDED", "RUNNING")
    with pytest.raises(InvalidStateTransition):
        assert_request_transition("CANCELLED", "RUNNING")


def test_migration_file_exists() -> None:
    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("w3d4e5f6a7b8") for p in versions.glob("*.py"))


def test_head_is_execution() -> None:
    from tests.migration_helpers import alembic_current_head

    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_cost_mock_not_applicable() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    result = calculate_cost(
        session,
        provider_code="mock",
        model="mock-v1",
        input_tokens=10,
        output_tokens=5,
    )
    assert result["cost_calculation_status"] == "NOT_APPLICABLE"
    assert result["estimated_cost"] is None


def test_cost_pricing_not_configured_is_null() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    result = calculate_cost(
        session,
        provider_code="openai",
        model="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=100,
    )
    assert result["estimated_cost"] is None
    assert result["cost_calculation_status"] == "PRICING_NOT_CONFIGURED"


def test_create_blocks_strategy_task() -> None:
    from stock_platform.ai.execution.service import (
        AIExecutionError,
        AIExecutionService,
    )

    session = MagicMock()
    session.scalar.return_value = None
    svc = AIExecutionService(session)
    with pytest.raises(AIExecutionError) as exc:
        svc.create_request(
            actor="admin:1",
            reason="test",
            task_type="STRATEGY_DRAFT",
            execution_mode="MOCK",
            idempotency_key="k1",
            input_payload={"text": "x"},
        )
    assert exc.value.code == "AI_TASK_EXECUTION_NOT_ENABLED"


def test_create_blocks_strategy_task() -> None:
    from stock_platform.ai.execution.service import (
        AIExecutionError,
        AIExecutionService,
    )

    svc = AIExecutionService(MagicMock())
    with pytest.raises(AIExecutionError) as exc:
        svc.create_request(
            actor="admin:1",
            reason="test",
            task_type="STRATEGY_DRAFT",
            execution_mode="MOCK",
            idempotency_key="k2",
        )
    assert exc.value.code == "AI_TASK_EXECUTION_NOT_ENABLED"


def test_idempotent_replay() -> None:
    from stock_platform.ai.execution.entities import AIExecutionRequestEntity
    from stock_platform.ai.execution.service import AIExecutionService

    existing = AIExecutionRequestEntity(
        execution_request_id=9,
        request_key="abc",
        idempotency_key="same",
        task_type="CHAT",
        status="READY",
        execution_mode="MOCK",
        requested_by="admin:1",
        reason="r",
        max_tokens=64,
        temperature=0.2,
        timeout_sec=30,
        fallback_enabled=False,
        retry_max=1,
        currency="USD",
        lock_version=1,
    )
    session = MagicMock()
    session.scalar.return_value = existing
    result = AIExecutionService(session).create_request(
        actor="admin:1",
        reason="again",
        task_type="CHAT",
        execution_mode="MOCK",
        idempotency_key="same",
        input_payload={"text": "hi"},
    )
    assert result["idempotent_replay"] is True
    assert result["request"]["id"] == 9


@pytest.mark.asyncio
async def test_mock_execute_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.ai.execution.entities import AIExecutionRequestEntity
    from stock_platform.ai.execution.runner import AIExecutionRunner
    from stock_platform.ai.providers.manager import AIManager, reset_ai_manager

    reset_ai_manager(AIManager.create_default())

    row = AIExecutionRequestEntity(
        execution_request_id=1,
        request_key="rk",
        idempotency_key="idem-mock-1",
        task_type="CHAT",
        status=RequestStatus.READY.value,
        execution_mode="MOCK",
        provider_code="mock",
        requested_model="mock-v1",
        requested_by="admin:1",
        reason="mock exec",
        max_tokens=32,
        temperature=0.1,
        timeout_sec=10,
        fallback_enabled=False,
        retry_max=0,
        currency="USD",
        lock_version=1,
        input_payload_sanitized={"text": "hello"},
        input_hash="x",
        policy_ids=[],
    )

    session = MagicMock()
    session.get.side_effect = lambda model, ident: (
        row if model is AIExecutionRequestEntity else None
    )
    # refresh no-op
    session.refresh = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.add = MagicMock()
    session.scalar.return_value = None

    # lease / transition / events use session.add
    runner = AIExecutionRunner(session)

    # patch acquire and transitions to mutate row
    def acquire(r, *, owner, seconds=120):
        r.lease_owner = owner
        return True

    monkeypatch.setattr(runner._svc, "acquire_lease", acquire)
    monkeypatch.setattr(runner._svc, "is_cancel_requested", lambda _id: False)

    result = await runner.execute(1, actor="admin:1", confirm=False)
    assert result["ok"] is True
    assert result["mock_called"] is True
    assert result["external_ai_called"] is False
    assert row.status in {
        RequestStatus.SUCCEEDED.value,
        RequestStatus.SUCCEEDED_WITH_WARNINGS.value,
    }


@pytest.mark.asyncio
async def test_external_requires_confirm() -> None:
    from stock_platform.ai.execution.entities import AIExecutionRequestEntity
    from stock_platform.ai.execution.runner import AIExecutionRunner
    from stock_platform.ai.execution.service import AIExecutionError

    row = AIExecutionRequestEntity(
        execution_request_id=2,
        request_key="rk2",
        idempotency_key="idem-ext",
        task_type="CHAT",
        status=RequestStatus.READY.value,
        execution_mode="EXTERNAL",
        provider_code="openai",
        requested_by="admin:1",
        reason="ext",
        max_tokens=32,
        temperature=0.1,
        timeout_sec=10,
        fallback_enabled=False,
        retry_max=0,
        currency="USD",
        lock_version=1,
        input_payload_sanitized={"text": "x"},
    )
    session = MagicMock()
    session.get.return_value = row

    with pytest.raises(AIExecutionError) as exc:
        await AIExecutionRunner(session).execute(2, actor="a", confirm=False)
    assert exc.value.code == "CONFIRM_REQUIRED"


def test_cancel_terminal_blocked() -> None:
    from stock_platform.ai.execution.entities import AIExecutionRequestEntity
    from stock_platform.ai.execution.service import (
        AIExecutionError,
        AIExecutionService,
    )

    row = AIExecutionRequestEntity(
        execution_request_id=3,
        request_key="rk3",
        idempotency_key="idem-c",
        task_type="CHAT",
        status=RequestStatus.SUCCEEDED.value,
        execution_mode="MOCK",
        requested_by="admin:1",
        reason="r",
        max_tokens=16,
        temperature=0.2,
        timeout_sec=10,
        fallback_enabled=False,
        retry_max=0,
        currency="USD",
        lock_version=1,
    )
    session = MagicMock()
    session.get.return_value = row
    with pytest.raises(AIExecutionError) as exc:
        AIExecutionService(session).cancel(3, actor="a", reason="x")
    assert exc.value.code == "ALREADY_TERMINAL"


def test_recovery_abandons_running() -> None:
    from datetime import datetime, timedelta, timezone

    from stock_platform.ai.execution.entities import AIExecutionRequestEntity
    from stock_platform.ai.execution.recovery import recover_stale_executions

    row = AIExecutionRequestEntity(
        execution_request_id=4,
        request_key="rk4",
        idempotency_key="idem-r",
        task_type="CHAT",
        status=RequestStatus.RUNNING.value,
        execution_mode="MOCK",
        requested_by="admin:1",
        reason="r",
        max_tokens=16,
        temperature=0.2,
        timeout_sec=10,
        fallback_enabled=False,
        retry_max=0,
        currency="USD",
        lock_version=1,
        lease_owner="old",
        lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    result = recover_stale_executions(session, actor="STARTUP")
    assert result["abandoned"] == 1
    assert result["auto_external_retry"] == 0
    assert row.status == RequestStatus.ABANDONED.value


def test_api_router_registered() -> None:
    from stock_platform.api import router as router_mod

    assert hasattr(router_mod, "admin_ai_executions_router")
    paths = {
        getattr(r, "path", "")
        for r in router_mod.admin_ai_executions_router.routes
    }
    assert any("executions" in p for p in paths)


def test_dry_run_flag_contract() -> None:
    from stock_platform.ai.execution.runner import AIExecutionRunner
    from stock_platform.ai.execution.entities import AIExecutionRequestEntity

    row = AIExecutionRequestEntity(
        execution_request_id=5,
        request_key="rk5",
        idempotency_key="idem-d",
        task_type="CHAT",
        status=RequestStatus.READY.value,
        execution_mode="MOCK",
        provider_code="mock",
        requested_by="admin:1",
        reason="r",
        max_tokens=16,
        temperature=0.2,
        timeout_sec=10,
        fallback_enabled=False,
        retry_max=0,
        currency="USD",
        lock_version=1,
        input_payload_sanitized={"text": "hi"},
        policy_ids=[],
    )
    session = MagicMock()
    session.get.return_value = row
    session.scalars.return_value = []
    session.scalar.return_value = None
    result = AIExecutionRunner(session).dry_run(5, actor="admin:1")
    assert result["external_ai_called"] is False
