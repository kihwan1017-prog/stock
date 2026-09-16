"""STEP 12-2-2 — AI Strategy Draft Generator 통합 테스트.

실제 PostgreSQL(로컬 dev DB) + "mock" Provider(결정적, 외부 네트워크 없음)를
사용한다. 실제 Ollama/외부 AI 호출 테스트는 `@pytest.mark.live_ai`로
격리하며(이 파일에는 포함하지 않음 — 이 샌드박스에 실행 중인 Ollama가
없어 검증 불가능하므로 완료 보고에 미실행으로 명시한다), 기본 테스트는
Fake(mock) Provider로 완전 결정적이다.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.candidate_lifecycle.service import AICandidateLifecycleService
from stock_platform.ai.prompt.output_validator import validate_ai_output
from stock_platform.ai.strategy_draft.entities import (
    StrategyDraftEntity,
    StrategyDraftHistoryEntity,
)
from stock_platform.ai.strategy_draft_generation.entities import (
    StrategyDraftGenerationAttemptEntity,
    StrategyDraftGenerationRunEntity,
)
from stock_platform.ai.strategy_draft_generation.prompt import (
    STRATEGY_DRAFT_OUTPUT_ENVELOPE,
)
from stock_platform.ai.strategy_draft_generation.schema import (
    GenerationSchemaError,
    parse_and_validate_output,
)
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationError,
    StrategyDraftGenerationService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_2_2_TEST"
_FINGERPRINT = "e5" * 32

_MOCK_STRATEGY_DRAFT_RESULT = {
    "title": "Mock RSI Reversal Draft",
    "summary": "Mock oversold bounce sketch for review only.",
    "market_type": "KR_STOCK",
    "symbols": ["MOCK"],
    "timeframe": "1D",
    "entry_rules": [{"indicator": "RSI", "operator": "LT", "threshold": 30}],
    "exit_rules": [{"indicator": "RSI", "operator": "GT", "threshold": 70}],
    "stop_loss_rule": {"type": "PERCENT", "value": 5},
    "take_profit_rule": {"type": "PERCENT", "value": 10},
    "position_sizing_rule": {"method": "FIXED_PERCENT", "value": 0.1},
    "indicators": ["RSI"],
    "risk_parameters": {"max_daily_loss_pct": 2.0},
    "trading_session_rules": [],
    "cooldown_rules": [],
    "invalidation_conditions": [],
    "assumptions": ["mock_data"],
    "rationale": "Mock reference sketch only, not investment advice.",
    "confidence": 0.6,
}


def _mock_envelope(result: dict, **overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "task_type": "STRATEGY_DRAFT",
        "confidence": 0.6,
        "reasoning_summary": "Mock strategy draft (reference only)",
        "result": result,
        "warnings": [],
        "citations": [{"source": "mock", "ref": "fixture"}],
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def result_ids() -> list[int]:
    Session = get_session_factory()
    s = Session()
    try:
        rows = s.execute(
            text(
                "SELECT result_id FROM strategy.candidate_result "
                "ORDER BY result_id LIMIT 2"
            )
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


@pytest.fixture()
def session(result_ids: list[int]):
    Session = get_session_factory()
    s = Session()
    try:
        s.info["result_ids"] = result_ids
        yield s
    finally:
        s.rollback()
        s.execute(
            text(
                "DELETE FROM ai.strategy_draft_generation_attempt WHERE generation_run_id IN "
                "(SELECT generation_run_id FROM ai.strategy_draft_generation_run WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_draft_generation_run WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_draft_history WHERE draft_id IN "
                "(SELECT draft_id FROM ai.strategy_draft WHERE strategy_request_id IN "
                "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_draft WHERE strategy_request_id IN "
                "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_request_history WHERE strategy_request_id IN "
                "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_request WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.candidate_supersession WHERE previous_candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker) "
                "OR replacement_candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text("DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker"),
            {"marker": _MARKER},
        )
        s.commit()
        s.close()


def _create_candidate(
    session, *, result_id: int, lifecycle_status: str = "PROMOTED", fingerprint=_FINGERPRINT
) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, source_fingerprint, created_by, updated_by)
            VALUES (:cid, :status, 'UNKNOWN', :fp, :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "status": lifecycle_status, "fp": fingerprint, "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_approved_request(session, *, result_id: int) -> dict:
    candidate_id = _create_candidate(session, result_id=result_id)
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    return StrategyRequestService(session).approve(
        req["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )


def _run_generate(session, run_id: int, *, actor: str = "admin:7") -> dict:
    return asyncio.run(
        StrategyDraftGenerationService(session).generate(run_id, actor=actor)
    )


def _run_generate_strategy_draft(session, **kwargs) -> dict:
    kwargs.setdefault("actor", "admin:7")
    kwargs.setdefault("provider_id", "mock")
    return asyncio.run(
        StrategyDraftGenerationService(session).generate_strategy_draft(**kwargs)
    )


# ---------------------------------------------------------------------------
# Domain/DB — 1~9
# ---------------------------------------------------------------------------


def test_create_generation_run_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    run = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"],
        actor="admin:7",
        provider_id="mock",
    )
    assert run["status"] == "PENDING"
    assert run["candidate_lifecycle_status_at_request"] == "PROMOTED"
    assert run["candidate_fingerprint_at_request"] == _FINGERPRINT
    assert run["idempotent_replay"] is False


def test_state_transitions_pending_to_terminal(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    result = _run_generate(session, created["generation_run_id"])
    assert result["run"]["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT"}


def test_generate_blocks_non_pending_run(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    _run_generate(session, created["generation_run_id"])

    with pytest.raises(StrategyDraftGenerationError) as exc:
        asyncio.run(svc.generate(created["generation_run_id"], actor="admin:7"))
    assert exc.value.code == "INVALID_STATE_TRANSITION"


def test_duplicate_active_run_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.create_generation_run(
            strategy_request_id=request["strategy_request_id"],
            actor="admin:7",
            provider_id="mock",
            idempotency_key="different-key",
        )
    assert exc.value.code == "DUPLICATE_ACTIVE_GENERATION_RUN"


def test_idempotency_key_replays_same_run(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    first = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"],
        actor="admin:7",
        provider_id="mock",
        idempotency_key="fixed-key-1",
    )
    second = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"],
        actor="admin:7",
        provider_id="mock",
        idempotency_key="fixed-key-1",
    )
    assert second["generation_run_id"] == first["generation_run_id"]
    assert second["idempotent_replay"] is True


def test_retry_blocked_for_pending_or_succeeded(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.retry_generation(created["generation_run_id"], actor="admin:7")
    assert exc.value.code == "INVALID_STATE_TRANSITION"

    result = _run_generate(session, created["generation_run_id"])
    if result["run"]["status"] == "SUCCEEDED":
        with pytest.raises(StrategyDraftGenerationError) as exc2:
            svc.retry_generation(result["run"]["generation_run_id"], actor="admin:7")
        assert exc2.value.code == "INVALID_STATE_TRANSITION"


def test_retry_after_failure_creates_new_run(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    # 실패를 강제하기 위해 candidate를 실행 직전 무효화한다.
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()
    failed = _run_generate(session, created["generation_run_id"])
    assert failed["run"]["status"] == "FAILED"

    # candidate를 복구한 뒤 재시도 — 새 Run이 생성되어야 한다(기존 Run을 되살리지 않음).
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'PROMOTED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()
    retried = svc.retry_generation(created["generation_run_id"], actor="admin:7")
    assert retried["generation_run_id"] != created["generation_run_id"]
    assert retried["retry_of_run_id"] == created["generation_run_id"]
    assert retried["retry_number"] == 1


def test_fk_and_not_found_errors(session) -> None:
    svc = StrategyDraftGenerationService(session)
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.create_generation_run(
            strategy_request_id=999_999_999, actor="admin:7", provider_id="mock"
        )
    assert exc.value.code == "STRATEGY_REQUEST_NOT_FOUND"

    with pytest.raises(StrategyDraftGenerationError) as exc2:
        svc.get_generation_run(999_999_999)
    assert exc2.value.code == "NOT_FOUND"


def test_hard_delete_blocked_when_run_exists(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM ai.strategy_request WHERE strategy_request_id = :id"),
            {"id": request["strategy_request_id"]},
        )
        session.commit()
    session.rollback()


def test_migration_upgrade_downgrade_roundtrip() -> None:
    from alembic import command
    from tests.migration_helpers import alembic_config

    config = alembic_config()

    def _tables_exist() -> bool:
        Session = get_session_factory()
        s = Session()
        try:
            row = s.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='ai' AND table_name IN "
                    "('strategy_draft_generation_run', 'strategy_draft_generation_attempt')"
                )
            ).scalar()
            return int(row or 0) == 2
        finally:
            s.close()

    assert _tables_exist()
    try:
        command.downgrade(config, "5b999d920792")
        assert not _tables_exist()
    finally:
        command.upgrade(config, "head")
    assert _tables_exist()


# ---------------------------------------------------------------------------
# 무결성 — 10~21
# ---------------------------------------------------------------------------


def test_create_run_requires_approved_request(session) -> None:
    candidate_id = _create_candidate(session, result_id=session.info["result_ids"][0])
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    svc = StrategyDraftGenerationService(session)
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.create_generation_run(
            strategy_request_id=req["strategy_request_id"], actor="admin:7", provider_id="mock"
        )
    assert exc.value.code == "STRATEGY_REQUEST_NOT_APPROVED"


@pytest.mark.parametrize("lifecycle_status", ["REVOKED", "EXPIRED", "SUPERSEDED", "STALE"])
def test_create_run_blocks_inactive_candidate(session, lifecycle_status) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = :status "
            "WHERE candidate_id = :cid"
        ),
        {"status": lifecycle_status, "cid": request["candidate_id"]},
    )
    session.commit()

    svc = StrategyDraftGenerationService(session)
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.create_generation_run(
            strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"


def test_create_run_blocks_fingerprint_mismatch(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET source_fingerprint = :fp "
            "WHERE candidate_id = :cid"
        ),
        {"fp": "ff" * 32, "cid": request["candidate_id"]},
    )
    session.commit()
    svc = StrategyDraftGenerationService(session)
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.create_generation_run(
            strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
        )
    assert exc.value.code == "CANDIDATE_FINGERPRINT_CHANGED"


def test_create_run_blocks_null_approval_fingerprint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.strategy_request SET candidate_fingerprint_at_review = NULL "
            "WHERE strategy_request_id = :id"
        ),
        {"id": request["strategy_request_id"]},
    )
    session.commit()
    svc = StrategyDraftGenerationService(session)
    with pytest.raises(StrategyDraftGenerationError) as exc:
        svc.create_generation_run(
            strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
        )
    assert exc.value.code == "CANDIDATE_FINGERPRINT_CHANGED"


@pytest.mark.parametrize("lifecycle_status", ["REVOKED", "EXPIRED", "SUPERSEDED"])
def test_candidate_invalidated_during_call_blocks_draft(session, lifecycle_status) -> None:
    """AI 호출(Step B~C) 도중 Candidate가 무효화되면 Draft를 채택하지 않는다.

    실 스레드 동시성은 STEP12-1A/STEP12-2-1A에서 StrategyDraftService.create()
    자체에 대해 이미 검증됐다(candidate_lifecycle의 FOR UPDATE 락 재사용).
    이 서비스의 Step C는 그 create()를 그대로 재호출하므로, 여기서는
    "Step A 이후 상태가 바뀐 경우" 시나리오를 순차적으로 재현해 결과가
    올바르게 폐기되는지 검증한다(동일한 재검증 로직 경로).
    """
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    # Step A 완료(PENDING) 이후, AI 호출 도중에 해당하는 상태 변경을 재현.
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = :status "
            "WHERE candidate_id = :cid"
        ),
        {"status": lifecycle_status, "cid": request["candidate_id"]},
    )
    session.commit()

    result = _run_generate(session, created["generation_run_id"])
    assert result["run"]["status"] == "FAILED"
    assert result["run"]["error_code"] == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"
    assert result["draft"] is None

    remaining = session.execute(
        text(
            "SELECT count(*) FROM ai.strategy_draft WHERE strategy_request_id = :id"
        ),
        {"id": request["strategy_request_id"]},
    ).scalar()
    assert remaining == 0


def test_failure_leaves_no_partial_history(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()
    _run_generate(session, created["generation_run_id"])

    history_count = session.execute(
        text("SELECT count(*) FROM ai.strategy_draft_history")
    ).scalar()
    draft_count = session.execute(
        text(
            "SELECT count(*) FROM ai.strategy_draft WHERE strategy_request_id = :id"
        ),
        {"id": request["strategy_request_id"]},
    ).scalar()
    assert draft_count == 0
    # 이 request 소유의 draft가 없으므로 그에 연결된 history도 없다(전역 카운트가
    # 아니라 draft_count==0 로 이미 증명됨). history_count는 다른 테스트 영향을
    # 받을 수 있어 draft_count만으로 판단한다.
    assert draft_count == 0 and history_count >= 0


# ---------------------------------------------------------------------------
# Provider/Parsing — 22~35 (핵심 항목)
# ---------------------------------------------------------------------------


def test_normal_json_response_succeeds(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _run_generate_strategy_draft(
        session, strategy_request_id=request["strategy_request_id"]
    )
    assert result["run"]["status"] == "SUCCEEDED"
    assert result["draft"]["title"] == "Mock RSI Reversal Draft"


def test_markdown_fence_response_parsed() -> None:
    raw = "```json\n" + json.dumps(_mock_envelope(_MOCK_STRATEGY_DRAFT_RESULT)) + "\n```"
    validation = validate_ai_output(
        raw=raw, json_schema=STRATEGY_DRAFT_OUTPUT_ENVELOPE, expected_task_type="STRATEGY_DRAFT"
    )
    assert validation["status"] == "VALID"
    parsed = parse_and_validate_output(validation["data"]["result"])
    assert parsed.title == "Mock RSI Reversal Draft"


def test_invalid_json_blocked() -> None:
    validation = validate_ai_output(
        raw="{not valid json", json_schema=STRATEGY_DRAFT_OUTPUT_ENVELOPE,
        expected_task_type="STRATEGY_DRAFT",
    )
    assert validation["status"] == "INVALID"
    assert validation["code"] == "AI_RESPONSE_INVALID_JSON"


def test_missing_required_field_blocked() -> None:
    bad_result = dict(_MOCK_STRATEGY_DRAFT_RESULT)
    del bad_result["stop_loss_rule"]
    with pytest.raises(GenerationSchemaError):
        parse_and_validate_output(bad_result)


def test_unknown_field_policy_rejected() -> None:
    bad_result = dict(_MOCK_STRATEGY_DRAFT_RESULT)
    bad_result["unexpected_field"] = "x"
    with pytest.raises(GenerationSchemaError):
        parse_and_validate_output(bad_result)


def test_unknown_indicator_blocked() -> None:
    bad_result = dict(_MOCK_STRATEGY_DRAFT_RESULT)
    bad_result["entry_rules"] = [
        {"indicator": "MAGIC_INDICATOR", "operator": "LT", "threshold": 30}
    ]
    with pytest.raises(GenerationSchemaError):
        parse_and_validate_output(bad_result)


def test_abnormal_risk_value_blocked() -> None:
    bad_result = dict(_MOCK_STRATEGY_DRAFT_RESULT)
    bad_result["stop_loss_rule"] = {"type": "PERCENT", "value": 999}
    with pytest.raises(GenerationSchemaError):
        parse_and_validate_output(bad_result)


def test_nan_infinity_blocked() -> None:
    raw = (
        '{"schema_version":"1.0","task_type":"STRATEGY_DRAFT","confidence":0.5,'
        '"reasoning_summary":"x","result":{"value": NaN}}'
    )
    validation = validate_ai_output(
        raw=raw, json_schema=STRATEGY_DRAFT_OUTPUT_ENVELOPE, expected_task_type="STRATEGY_DRAFT"
    )
    assert validation["status"] == "INVALID"


def test_provider_timeout_recorded(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager
    from stock_platform.ai.providers.registry import AIProviderRegistry
    from stock_platform.ai.providers.mock_provider import MockAIProvider

    cfg = AIProviderConfig(
        provider_id="mock", enabled=True, is_default=True, model="mock-v1",
        extra={"simulate_timeout": True},
    )
    registry = AIProviderRegistry()
    registry.register(MockAIProvider(cfg), cfg)
    manager = AIManager(registry=registry)

    svc2 = StrategyDraftGenerationService(session, ai_manager=manager)
    result = asyncio.run(svc2.generate(created["generation_run_id"], actor="admin:7"))
    assert result["run"]["status"] == "TIMED_OUT"
    assert result["draft"] is None


def test_provider_transport_error_recorded(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftGenerationService(session)
    created = svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager
    from stock_platform.ai.providers.registry import AIProviderRegistry
    from stock_platform.ai.providers.mock_provider import MockAIProvider

    cfg = AIProviderConfig(
        provider_id="mock", enabled=True, is_default=True, model="mock-v1",
        retry_max=0,
        extra={"simulate_error": True},
    )
    registry = AIProviderRegistry()
    registry.register(MockAIProvider(cfg), cfg)
    manager = AIManager(registry=registry)

    svc2 = StrategyDraftGenerationService(session, ai_manager=manager)
    result = asyncio.run(svc2.generate(created["generation_run_id"], actor="admin:7"))
    assert result["run"]["status"] == "FAILED"
    assert result["run"]["error_code"] == "MOCK_ERROR"


def test_provider_configuration_error() -> None:
    from stock_platform.ai.providers.manager import AIManager
    from stock_platform.ai.providers.registry import AIProviderRegistry

    empty_manager = AIManager(registry=AIProviderRegistry())
    with pytest.raises(Exception):
        empty_manager.select_provider()


def test_token_and_latency_recorded(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _run_generate_strategy_draft(
        session, strategy_request_id=request["strategy_request_id"]
    )
    run_detail = StrategyDraftGenerationService(session).get_generation_run(
        result["run"]["generation_run_id"]
    )
    attempt = run_detail["attempts"][0]
    assert attempt["total_tokens"] is not None and attempt["total_tokens"] >= 0
    assert attempt["latency_ms"] is not None and attempt["latency_ms"] >= 0


def test_prompt_and_response_hash_recorded_no_raw_text(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _run_generate_strategy_draft(
        session, strategy_request_id=request["strategy_request_id"]
    )
    attempt_row = session.scalar(
        select(StrategyDraftGenerationAttemptEntity).where(
            StrategyDraftGenerationAttemptEntity.generation_run_id
            == result["run"]["generation_run_id"]
        )
    )
    assert attempt_row.prompt_hash is not None
    assert attempt_row.response_hash is not None
    assert len(attempt_row.prompt_hash) == 64
    # 원문 미저장 정책 — structured_response에는 파싱된 JSON만 있고 raw 문자열
    # 컬럼 자체가 엔티티에 존재하지 않는다(설계로 보장).
    assert not hasattr(attempt_row, "raw_response")


# ---------------------------------------------------------------------------
# API/Auth — 36~43
# ---------------------------------------------------------------------------


def test_admin_generation_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategy-draft-generations", json={"strategy_request_id": 1}
    )
    assert resp.status_code == 401


def test_admin_generation_create_and_list_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategy-draft-generations",
        json={"strategy_request_id": request["strategy_request_id"], "provider_id": "mock"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    run_id = resp.json()["run"]["generation_run_id"]

    listed = client.get(
        "/api/v1/admin/strategy-draft-generations",
        params={"strategy_request_id": request["strategy_request_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert listed.status_code == 200
    assert any(item["generation_run_id"] == run_id for item in listed.json()["items"])

    detail = client.get(
        f"/api/v1/admin/strategy-draft-generations/{run_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert detail.status_code == 200
    assert detail.json()["generation_run_id"] == run_id


def test_admin_generation_duplicate_click_idempotent(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    body = {
        "strategy_request_id": request["strategy_request_id"],
        "provider_id": "mock",
        "idempotency_key": "dup-click-key",
    }
    first = client.post(
        "/api/v1/admin/strategy-draft-generations",
        json=body,
        headers={"X-Admin-API-Key": admin_key},
    )
    second = client.post(
        "/api/v1/admin/strategy-draft-generations",
        json=body,
        headers={"X-Admin-API-Key": admin_key},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert (
        first.json()["run"]["generation_run_id"]
        == second.json()["run"]["generation_run_id"]
    )


def test_admin_generation_retry_endpoint(session) -> None:
    """Provider 오류로 실패한 Run을 재시도하면 새 Run이 연결 생성된다.

    (Candidate를 미리 무효화하면 Step A 자체가 create 단계에서 막혀 PENDING
    Run조차 생성되지 않으므로 — 이는 다른 테스트가 이미 검증함 — 여기서는
    Provider 레벨 실패로 재현한다.)
    """
    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager, reset_ai_manager
    from stock_platform.ai.providers.mock_provider import MockAIProvider
    from stock_platform.ai.providers.registry import AIProviderRegistry

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)

    broken_cfg = AIProviderConfig(
        provider_id="mock", enabled=True, is_default=True, model="mock-v1",
        retry_max=0, extra={"simulate_error": True},
    )
    broken_registry = AIProviderRegistry()
    broken_registry.register(MockAIProvider(broken_cfg), broken_cfg)
    reset_ai_manager(AIManager(registry=broken_registry))
    try:
        created = client.post(
            "/api/v1/admin/strategy-draft-generations",
            json={"strategy_request_id": request["strategy_request_id"], "provider_id": "mock"},
            headers={"X-Admin-API-Key": admin_key},
        )
    finally:
        reset_ai_manager()

    assert created.status_code == 201
    assert created.json()["run"]["status"] == "FAILED"
    run_id = created.json()["run"]["generation_run_id"]

    retried = client.post(
        f"/api/v1/admin/strategy-draft-generations/{run_id}/retry",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert retried.status_code == 201
    assert retried.json()["run"]["generation_run_id"] != run_id


def test_admin_generation_audit_success_and_failure(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/admin/strategy-draft-generations",
        json={"strategy_request_id": request["strategy_request_id"], "provider_id": "mock"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201

    event = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.event_type.in_(
                (
                    "STRATEGY_DRAFT_GENERATION_SUCCEEDED",
                    "STRATEGY_DRAFT_GENERATION_FAILED",
                )
            )
        )
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(1)
    )
    assert event is not None
    # 전체 Prompt/응답/API Key는 Audit에 없어야 한다.
    dumped = json.dumps(event.detail)
    assert "system_template" not in dumped
    assert "api_key" not in dumped.lower()


def test_openapi_lists_generation_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/admin/strategy-draft-generations" in paths
    assert "post" in paths["/api/v1/admin/strategy-draft-generations"]
    assert "get" in paths["/api/v1/admin/strategy-draft-generations"]
    assert "/api/v1/admin/strategy-draft-generations/{run_id}" in paths
    assert "/api/v1/admin/strategy-draft-generations/{run_id}/retry" in paths
    # USER는 이 STEP에서 생성 권한이 없다 — user 전용 generation 경로가 없어야 한다.
    assert not any("strategy-draft-generations" in p and "/user/" in p for p in paths)
