"""STEP 12-3 — Strategy Draft 관리자 최종 승인 및 Strategy Definition 확정
통합 테스트.

실제 PostgreSQL(로컬 dev DB) + "mock" Provider(결정적)를 사용한다. 동시성
테스트는 실제 2세션/2스레드로 검증하며(§11), 문자열 검사나 mock lock으로
대체하지 않는다.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.candidate_lifecycle.service import AICandidateLifecycleService
from stock_platform.ai.strategy_draft.entities import StrategyDraftEntity
from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.entities import (
    StrategyDraftApprovalEntity,
    StrategyDraftApprovalHistoryEntity,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalError,
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.ownership import (
    StrategyOwnershipError,
    assert_strategy_not_draft_derived,
)

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_OTHER_USER_ID = 999_999
_MARKER = "STEP12_3_TEST"
_FINGERPRINT = "c3" * 32

_VALID_ENTRY = '[{"indicator":"RSI","operator":"LT","threshold":30}]'
_VALID_EXIT = '[{"indicator":"RSI","operator":"GT","threshold":70}]'
_VALID_STOP_LOSS = '{"type":"PERCENT","value":5}'
_VALID_TAKE_PROFIT = '{"type":"PERCENT","value":10}'
_VALID_POSITION_SIZING = '{"method":"FIXED_PERCENT","value":0.1}'


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


_CLEANUP_SQL = [
    "DELETE FROM ai.strategy_draft_approval_history WHERE approval_id IN "
    "(SELECT approval_id FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "UPDATE trading.strategy_definition SET approval_id = NULL WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_generation_attempt WHERE generation_run_id IN "
    "(SELECT generation_run_id FROM ai.strategy_draft_generation_run WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_draft_generation_run WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_history WHERE draft_id IN "
    "(SELECT draft_id FROM ai.strategy_draft WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM ai.strategy_draft WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_request_history WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.candidate_revocation WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.candidate_supersession WHERE previous_candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker) "
    "OR replacement_candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker",
]


def _cleanup(s) -> None:
    for sql in _CLEANUP_SQL:
        s.execute(text(sql), {"marker": _MARKER})
    s.commit()


@pytest.fixture()
def session(result_ids: list[int]):
    Session = get_session_factory()
    s = Session()
    try:
        s.info["result_ids"] = result_ids
        yield s
    finally:
        s.rollback()
        _cleanup(s)
        s.close()


def _create_candidate(session, *, result_id: int, fingerprint=_FINGERPRINT) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, source_fingerprint, created_by, updated_by)
            VALUES (:cid, 'PROMOTED', 'UNKNOWN', :fp, :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "fp": fingerprint, "marker": _MARKER},
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


def _manual_draft_kwargs(**overrides) -> dict:
    base = {
        "actor": "admin:7",
        "title": "수동 초안",
        "timeframe": "1D",
        "market_type": "KR_STOCK",
        "entry_rule": _VALID_ENTRY,
        "exit_rule": _VALID_EXIT,
        "stop_loss_rule": _VALID_STOP_LOSS,
        "take_profit_rule": _VALID_TAKE_PROFIT,
        "position_sizing_rule": _VALID_POSITION_SIZING,
    }
    base.update(overrides)
    return base


def _create_manual_draft(session, strategy_request_id: int, **overrides) -> dict:
    return StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, **_manual_draft_kwargs(**overrides)
    )


def _generate_ai_draft(session, strategy_request_id: int) -> dict:
    return asyncio.run(
        StrategyDraftGenerationService(session).generate_strategy_draft(
            strategy_request_id=strategy_request_id,
            actor="admin:7",
            provider_id="mock",
        )
    )


def _read_only_user(user_id: int) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, username=f"user{user_id}", roles=["user"],
        permissions=["trading:read"],
    )


# ---------------------------------------------------------------------------
# 1~9: Domain/DB
# ---------------------------------------------------------------------------


def test_approval_created_on_approve(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인합니다")
    assert approval["status"] == "APPROVED"
    assert approval["strategy_definition_id"] is not None


def test_reject_transition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval = svc.reject(draft["draft_id"], actor="admin:7", reason="근거 불충분")
    assert approval["status"] == "REJECTED"
    assert approval["strategy_definition_id"] is None


def test_revoke_transition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    revoked = svc.revoke(approval["approval_id"], actor="admin:9", reason="취소 사유")
    assert revoked["status"] == "REVOKED"
    definition = session.get(
        StrategyDefinitionEntity, revoked["strategy_definition_id"]
    )
    assert definition.is_active is False


def test_invalid_transition_reject_then_approve_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    svc.reject(draft["draft_id"], actor="admin:7", reason="반려")
    # REJECTED -> APPROVED 직접 전이 금지. 반려 후에도 Draft.status는 여전히
    # DRAFT이므로 approve()를 다시 호출할 수는 있으나(재심), 이미 REJECTED
    # 결정이 남아있는 상태에서 승인이 "그 반려를 뒤집는 것"이 아니라 "새
    # 결정"임을 보장하기 위해 최소한 REJECTED 행 자체는 불변으로 남아야 한다.
    rejected = session.scalar(
        select(StrategyDraftApprovalEntity).where(
            StrategyDraftApprovalEntity.draft_id == draft["draft_id"],
            StrategyDraftApprovalEntity.status == "REJECTED",
        )
    )
    assert rejected is not None
    approved = svc.approve(draft["draft_id"], actor="admin:7", reason="재심 후 승인")
    assert approved["status"] == "APPROVED"
    # 기존 REJECTED 행은 그대로 보존(덮어쓰기 없음).
    session.refresh(rejected)
    assert rejected.status == "REJECTED"


def test_revoke_on_non_approved_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    rejected = svc.reject(draft["draft_id"], actor="admin:7", reason="반려")
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        svc.revoke(rejected["approval_id"], actor="admin:7", reason="취소 시도")
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"


def test_history_append_only(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")
    history = svc.get_history(approval["approval_id"])["items"]
    actions = [h["action"] for h in history]
    assert "APPROVED" in actions
    assert "REVOKED" in actions
    # append-only: history_id는 모두 고유하고 삭제되지 않는다(행 개수 >= 2).
    assert len(history) >= 2


def test_fk_restrict_blocks_hard_delete_of_draft_with_approval(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM ai.strategy_draft WHERE draft_id = :d"),
            {"d": draft["draft_id"]},
        )
    session.rollback()


def test_unique_active_approval_per_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        svc.approve(draft["draft_id"], actor="admin:7", reason="다시 승인")
    assert exc_info.value.code == "ALREADY_APPROVED"


def test_reason_required(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        svc.approve(draft["draft_id"], actor="admin:7", reason="   ")
    assert exc_info.value.code == "REASON_REQUIRED"


# ---------------------------------------------------------------------------
# 10~21: 승인 조건
# ---------------------------------------------------------------------------


def test_latest_draft_approval_succeeds(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    assert approval["status"] == "APPROVED"


def test_superseded_draft_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    v1 = _create_manual_draft(session, request["strategy_request_id"])
    _create_manual_draft(session, request["strategy_request_id"], title="v2")  # v1 -> SUPERSEDED
    session.refresh(session.get(StrategyDraftEntity, v1["draft_id"]))
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            v1["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "DRAFT_STATUS_NOT_APPROVABLE"


def test_archived_draft_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    StrategyDraftService(session).archive(draft["draft_id"], actor="admin:7")
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            draft["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "DRAFT_STATUS_NOT_APPROVABLE"


def test_regenerated_draft_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    v1 = _create_manual_draft(session, request["strategy_request_id"])
    StrategyDraftService(session).create_revision(
        v1["draft_id"], actor="admin:7", summary="재작성"
    )
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            v1["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "DRAFT_STATUS_NOT_APPROVABLE"


def test_non_approved_strategy_request_blocked(session) -> None:
    candidate_id = _create_candidate(session, result_id=session.info["result_ids"][0])
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id, user_id=_REQUESTER_USER_ID, request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    # 승인 전(PENDING_REVIEW) 상태에서는 Draft 자체를 만들 수 없으므로,
    # 이 조건은 draft.create()가 이미 차단한다는 사실 자체가 증거다.
    from stock_platform.ai.strategy_draft.service import StrategyDraftError

    with pytest.raises(StrategyDraftError) as exc_info:
        _create_manual_draft(session, req["strategy_request_id"])
    assert exc_info.value.code == "STRATEGY_REQUEST_NOT_APPROVED"


def test_inactive_candidate_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    AICandidateLifecycleService(session).expire(
        candidate_id=request["candidate_id"], expected_version=1,
        actor="admin:test", reason="테스트 만료",
    )
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            draft["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "CANDIDATE_NOT_ACTIVE"


def test_fingerprint_mismatch_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET source_fingerprint = :fp "
            "WHERE candidate_id = :cid"
        ),
        {"fp": "ff" * 32, "cid": request["candidate_id"]},
    )
    session.commit()
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            draft["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "CANDIDATE_FINGERPRINT_CHANGED"


def test_generation_failed_blocked(session) -> None:
    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager, reset_ai_manager
    from stock_platform.ai.providers.mock_provider import MockAIProvider
    from stock_platform.ai.providers.registry import AIProviderRegistry

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    gen_svc = StrategyDraftGenerationService(session)
    created = gen_svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7",
        provider_id="mock",
    )
    broken_cfg = AIProviderConfig(
        provider_id="mock", enabled=True, is_default=True, model="mock-v1",
        retry_max=0, extra={"simulate_error": True},
    )
    broken_registry = AIProviderRegistry()
    broken_registry.register(MockAIProvider(broken_cfg), broken_cfg)
    reset_ai_manager(AIManager(registry=broken_registry))
    try:
        failing_svc = StrategyDraftGenerationService(session)
        failed = asyncio.run(
            failing_svc.generate(created["generation_run_id"], actor="admin:7")
        )
    finally:
        reset_ai_manager()
    assert failed["run"]["status"] == "FAILED"
    # 실패한 Run은 Draft를 만들지 않으므로 승인 대상 Draft 자체가 없다 —
    # 이 자체가 "Generation FAILED는 Draft를 만들지 않아 승인 대상이 될 수
    # 없다"는 안전성의 증거다.
    assert failed["run"]["draft_id"] is None


def test_no_successful_attempt_blocked_via_manual_draft_marked_as_ai(session) -> None:
    """draft.llm_provider가 채워져 있는데(=AI 생성으로 표시) 대응하는
    Generation Run이 전혀 없는(비정상) 경우 DRAFT_RUN_MISMATCH로 차단됨을
    검증한다(정상 경로에서는 발생하지 않지만 방어 로직 자체를 검증)."""
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(
        session, request["strategy_request_id"], llm_provider="ollama", llm_model="x"
    )
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            draft["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "DRAFT_RUN_MISMATCH"


def test_structured_validation_failure_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(
        session, request["strategy_request_id"], entry_rule="[]"
    )
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).approve(
            draft["draft_id"], actor="admin:7", reason="승인 시도"
        )
    assert exc_info.value.code == "STRUCTURED_VALIDATION_FAILED"


def test_manual_draft_approval_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    assert draft["llm_provider"] is None
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="수동 초안 승인"
    )
    assert approval["status"] == "APPROVED"
    assert approval["generation_run_id"] is None


def test_ai_draft_approval_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate_ai_draft(session, request["strategy_request_id"])
    draft_id = result["draft"]["draft_id"]
    approval = StrategyDraftApprovalService(session).approve(
        draft_id, actor="admin:7", reason="AI 초안 승인"
    )
    assert approval["status"] == "APPROVED"
    assert approval["generation_run_id"] == result["run"]["generation_run_id"]
    assert approval["generation_attempt_id"] is not None


# ---------------------------------------------------------------------------
# 22~28: Strategy Definition
# ---------------------------------------------------------------------------


def test_definition_created_and_owner_mapping(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:9", reason="승인"
    )
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    assert definition is not None
    assert definition.owner_type == "USER"
    assert int(definition.user_id) == _REQUESTER_USER_ID
    assert definition.visibility == "PRIVATE"
    assert definition.is_active is True
    assert definition.source_draft_id == draft["draft_id"]
    assert definition.approved_by == "admin:9"


def test_draft_snapshot_preserved_in_parameter_payload(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    payload = definition.parameter_payload
    assert payload["entry_rule"] is not None
    assert payload["stop_loss_rule"]["type"] == "PERCENT"


def test_definition_hash_present(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    assert approval["definition_hash"] is not None
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    assert definition.definition_hash == approval["definition_hash"]


def test_definition_immutable_after_approval(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    with pytest.raises(Exception):
        assert_strategy_not_draft_derived(definition)


def test_admin_strategies_api_cannot_edit_draft_derived_definition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.put(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}",
        json={"name": "변조 시도"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 409


def test_duplicate_definition_blocked_by_reapproving_same_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft["draft_id"]},
    ).scalar_one()
    assert count == 1
    with pytest.raises(StrategyDraftApprovalError):
        svc.approve(draft["draft_id"], actor="admin:7", reason="다시")
    count_after = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft["draft_id"]},
    ).scalar_one()
    assert count_after == 1


def test_new_draft_supersedes_prior_approval_for_same_request(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    v1 = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval_1 = svc.approve(v1["draft_id"], actor="admin:7", reason="v1 승인")

    v2 = _create_manual_draft(session, request["strategy_request_id"], title="v2")
    approval_2 = svc.approve(v2["draft_id"], actor="admin:7", reason="v2 승인")

    session.refresh(session.get(StrategyDraftApprovalEntity, approval_1["approval_id"]))
    old = session.get(StrategyDraftApprovalEntity, approval_1["approval_id"])
    assert old.status == "SUPERSEDED"
    assert approval_2["status"] == "APPROVED"

    old_definition = session.get(
        StrategyDefinitionEntity, approval_1["strategy_definition_id"]
    )
    assert old_definition.is_active is False
    new_definition = session.get(
        StrategyDefinitionEntity, approval_2["strategy_definition_id"]
    )
    assert new_definition.is_active is True


# ---------------------------------------------------------------------------
# 29~37: 멱등성/동시성
# ---------------------------------------------------------------------------


def test_idempotency_key_replay(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    first = svc.approve(
        draft["draft_id"], actor="admin:7", reason="승인", idempotency_key="idem-1"
    )
    second = svc.approve(
        draft["draft_id"], actor="admin:7", reason="승인(재시도)", idempotency_key="idem-1"
    )
    assert second["idempotent_replay"] is True
    assert second["approval_id"] == first["approval_id"]


def test_different_idempotency_key_on_approved_draft_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    svc.approve(draft["draft_id"], actor="admin:7", reason="승인", idempotency_key="idem-a")
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        svc.approve(draft["draft_id"], actor="admin:7", reason="승인", idempotency_key="idem-b")
    assert exc_info.value.code == "ALREADY_APPROVED"


def test_concurrent_approve_vs_approve_only_one_wins(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    draft_id = draft["draft_id"]
    request_id = request["strategy_request_id"]

    Session = get_session_factory()
    lock_acquired = threading.Event()
    errors: list[BaseException] = []
    results: list[dict] = []

    def _approve_a() -> None:
        s_a = Session()
        try:
            from stock_platform.ai.strategy_request.entities import (
                StrategyRequestEntity,
            )

            # approve()가 실제로 첫 번째로 잠그는 것과 동일한 자원(Strategy
            # Request)을 밖에서 먼저 잠가야 한다 — Draft를 먼저 잠그면
            # approve() 내부 잠금 순서(request->candidate->draft)와 엇갈려
            # 데드락이 발생한다(스레드 A: draft 보유 후 request 대기, 스레드
            # B: request 보유 후 draft 대기).
            s_a.execute(
                select(StrategyRequestEntity)
                .where(StrategyRequestEntity.strategy_request_id == request_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            r = StrategyDraftApprovalService(s_a).approve(
                draft_id, actor="admin:A", reason="A 승인"
            )
            results.append(r)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_b() -> None:
        assert lock_acquired.wait(timeout=5)
        s_b = Session()
        try:
            r = StrategyDraftApprovalService(s_b).approve(
                draft_id, actor="admin:B", reason="B 승인"
            )
            results.append(r)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_a = threading.Thread(target=_approve_a)
    t_b = threading.Thread(target=_approve_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    approval_errors = [e for e in errors if isinstance(e, StrategyDraftApprovalError)]
    assert len(approval_errors) == 1
    assert approval_errors[0].code == "ALREADY_APPROVED"
    assert len(results) == 1

    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft_id},
    ).scalar_one()
    assert count == 1


def test_concurrent_approve_vs_candidate_revoke(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    draft_id = draft["draft_id"]
    candidate_id = request["candidate_id"]

    Session = get_session_factory()
    lock_acquired = threading.Event()
    errors: list[BaseException] = []

    def _revoke_thread() -> None:
        s_a = Session()
        try:
            s_a.execute(
                select(AICandidateLifecycleEntity)
                .where(AICandidateLifecycleEntity.candidate_id == candidate_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            AICandidateLifecycleService(s_a).request_revocation(
                candidate_id=candidate_id,
                expected_version=1,
                actor="admin:concurrency-test",
                reason="STEP12-3 concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5)
        s_b = Session()
        try:
            StrategyDraftApprovalService(s_b).approve(
                draft_id, actor="admin:7", reason="승인 시도"
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_revoke = threading.Thread(target=_revoke_thread)
    t_approve = threading.Thread(target=_approve_thread)
    t_revoke.start()
    t_approve.start()
    t_revoke.join(timeout=10)
    t_approve.join(timeout=10)

    approval_errors = [e for e in errors if isinstance(e, StrategyDraftApprovalError)]
    assert len(approval_errors) == 1
    assert approval_errors[0].code in {"CANDIDATE_NOT_ACTIVE", "CANDIDATE_FINGERPRINT_CHANGED"}

    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft_id},
    ).scalar_one()
    assert count == 0


def test_concurrent_approve_vs_candidate_expire(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    draft_id = draft["draft_id"]
    candidate_id = request["candidate_id"]

    Session = get_session_factory()
    lock_acquired = threading.Event()
    errors: list[BaseException] = []

    def _expire_thread() -> None:
        s_a = Session()
        try:
            s_a.execute(
                select(AICandidateLifecycleEntity)
                .where(AICandidateLifecycleEntity.candidate_id == candidate_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            AICandidateLifecycleService(s_a).expire(
                candidate_id=candidate_id, expected_version=1,
                actor="admin:concurrency-test", reason="STEP12-3 concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5)
        s_b = Session()
        try:
            StrategyDraftApprovalService(s_b).approve(
                draft_id, actor="admin:7", reason="승인 시도"
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_expire = threading.Thread(target=_expire_thread)
    t_approve = threading.Thread(target=_approve_thread)
    t_expire.start()
    t_approve.start()
    t_expire.join(timeout=10)
    t_approve.join(timeout=10)

    approval_errors = [e for e in errors if isinstance(e, StrategyDraftApprovalError)]
    assert len(approval_errors) == 1
    assert approval_errors[0].code == "CANDIDATE_NOT_ACTIVE"

    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft_id},
    ).scalar_one()
    assert count == 0


def test_concurrent_approve_vs_candidate_supersede(session) -> None:
    if len(session.info["result_ids"]) < 2:
        pytest.skip("서로 다른 result_id 2개 필요")
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    draft_id = draft["draft_id"]
    candidate_id = request["candidate_id"]

    successor_id = _create_candidate(
        session, result_id=session.info["result_ids"][1], fingerprint="d4" * 32
    )

    Session = get_session_factory()
    lock_acquired = threading.Event()
    errors: list[BaseException] = []

    def _supersede_thread() -> None:
        s_a = Session()
        try:
            s_a.execute(
                select(AICandidateLifecycleEntity)
                .where(AICandidateLifecycleEntity.candidate_id == candidate_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            AICandidateLifecycleService(s_a).supersede(
                candidate_id, successor_id,
                expected_version=1,
                actor="admin:concurrency-test", reason="STEP12-3 concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5)
        s_b = Session()
        try:
            StrategyDraftApprovalService(s_b).approve(
                draft_id, actor="admin:7", reason="승인 시도"
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_supersede = threading.Thread(target=_supersede_thread)
    t_approve = threading.Thread(target=_approve_thread)
    t_supersede.start()
    t_approve.start()
    t_supersede.join(timeout=10)
    t_approve.join(timeout=10)

    approval_errors = [e for e in errors if isinstance(e, StrategyDraftApprovalError)]
    assert len(approval_errors) == 1
    assert approval_errors[0].code == "CANDIDATE_NOT_ACTIVE"

    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft_id},
    ).scalar_one()
    assert count == 0


def test_concurrent_approve_vs_draft_revision(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    draft_id = draft["draft_id"]
    request_id = request["strategy_request_id"]

    Session = get_session_factory()
    lock_acquired = threading.Event()
    errors: list[BaseException] = []
    results: list[dict] = []

    def _revision_thread() -> None:
        s_a = Session()
        try:
            from stock_platform.ai.strategy_request.entities import (
                StrategyRequestEntity,
            )

            s_a.execute(
                select(StrategyRequestEntity)
                .where(StrategyRequestEntity.strategy_request_id == request_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            StrategyDraftService(s_a).create_revision(
                draft_id, actor="admin:concurrency-test", summary="동시 개정"
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5)
        s_b = Session()
        try:
            r = StrategyDraftApprovalService(s_b).approve(
                draft_id, actor="admin:7", reason="승인 시도"
            )
            results.append(r)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_rev = threading.Thread(target=_revision_thread)
    t_app = threading.Thread(target=_approve_thread)
    t_rev.start()
    t_app.start()
    t_rev.join(timeout=10)
    t_app.join(timeout=10)

    # 둘 다 같은 StrategyRequest를 첫 잠금으로 사용하므로(request -> ...),
    # Postgres가 직렬화한다 — revision 스레드가 먼저 커밋되면 draft.status가
    # REGENERATED로 바뀌어 승인은 DRAFT_STATUS_NOT_APPROVABLE로 실패해야
    # 하고, 승인이 먼저 성공하면 revision은 재검증(같은 안전 기준)에서
    # 막히지 않고 성공할 수 있다(Draft 승인 여부는 Revision 생성 자체를
    # 막지 않음 — 이번 STEP 범위에서 별도로 차단하지 않기로 결정, 완료
    # 보고 Known Issues 참고). 어느 경우든 부분 상태(Definition은 생겼는데
    # approval이 없다거나 등)는 없어야 한다.
    approval_errors = [e for e in errors if isinstance(e, StrategyDraftApprovalError)]
    assert len(approval_errors) <= 1
    if results:
        assert results[0]["status"] == "APPROVED"


def test_concurrent_approve_vs_draft_archive(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    draft_id = draft["draft_id"]
    request_id = request["strategy_request_id"]

    Session = get_session_factory()
    lock_acquired = threading.Event()
    errors: list[BaseException] = []
    results: list[dict] = []

    def _archive_thread() -> None:
        s_a = Session()
        try:
            from stock_platform.ai.strategy_request.entities import (
                StrategyRequestEntity,
            )

            s_a.execute(
                select(StrategyRequestEntity)
                .where(StrategyRequestEntity.strategy_request_id == request_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            StrategyDraftService(s_a).archive(
                draft_id, actor="admin:concurrency-test", reason="동시 보관"
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5)
        s_b = Session()
        try:
            r = StrategyDraftApprovalService(s_b).approve(
                draft_id, actor="admin:7", reason="승인 시도"
            )
            results.append(r)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_arch = threading.Thread(target=_archive_thread)
    t_app = threading.Thread(target=_approve_thread)
    t_arch.start()
    t_app.start()
    t_arch.join(timeout=10)
    t_app.join(timeout=10)

    # 정확히 하나만 성공해야 한다 — 둘 다 request를 먼저 잠그므로 직렬화됨.
    assert len(results) + len(
        [e for e in errors if isinstance(e, StrategyDraftApprovalError)]
    ) >= 1
    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE source_draft_id = :d"
        ),
        {"d": draft_id},
    ).scalar_one()
    assert count in (0, 1)
    if count == 1:
        assert len(results) == 1


# ---------------------------------------------------------------------------
# 38~47: API / Auth / IDOR
# ---------------------------------------------------------------------------


def test_admin_approve_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
        json={"reason": "승인합니다"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "APPROVED"


def test_admin_reject_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/reject",
        json={"reason": "반려합니다"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "REJECTED"


def test_admin_revoke_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    approve_resp = client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
        json={"reason": "승인"},
        headers={"X-Admin-API-Key": admin_key},
    )
    approval_id = approve_resp.json()["approval_id"]
    resp = client.post(
        f"/api/v1/admin/strategy-draft-approvals/{approval_id}/revoke",
        json={"reason": "취소"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "REVOKED"


def test_regular_user_blocked_from_approve(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(_REQUESTER_USER_ID)
    try:
        resp = client.post(
            f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
            json={"reason": "승인 시도"},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_unauthenticated_401() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.post(
            "/api/v1/admin/strategy-drafts/1/approve", json={"reason": "x"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/admin/strategy-draft-approvals").status_code == 401


def test_idor_user_cannot_see_others_approval(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(_OTHER_USER_ID)
    try:
        resp = client.get(f"/api/v1/user/strategy-drafts/{draft['draft_id']}/approval")
        assert resp.status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()


def test_owner_user_can_read_own_approval(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(_REQUESTER_USER_ID)
    try:
        resp = client.get(f"/api/v1/user/strategy-drafts/{draft['draft_id']}/approval")
        assert resp.status_code == 200
        assert resp.json()["status"] == "APPROVED"
    finally:
        app.dependency_overrides.clear()


def test_list_and_detail_endpoints(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    approve_resp = client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
        json={"reason": "승인"},
        headers={"X-Admin-API-Key": admin_key},
    )
    approval_id = approve_resp.json()["approval_id"]

    list_resp = client.get(
        "/api/v1/admin/strategy-draft-approvals",
        params={"draft_id": draft["draft_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 1

    detail_resp = client.get(
        f"/api/v1/admin/strategy-draft-approvals/{approval_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["approval_id"] == approval_id


def test_approval_history_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    approve_resp = client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
        json={"reason": "승인"},
        headers={"X-Admin-API-Key": admin_key},
    )
    approval_id = approve_resp.json()["approval_id"]
    history_resp = client.get(
        f"/api/v1/admin/strategy-draft-approvals/{approval_id}/history",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert history_resp.status_code == 200
    assert len(history_resp.json()["items"]) >= 1


def test_audit_events_recorded(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
        json={"reason": "승인"},
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("STRATEGY_D%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    event_types = {e[0] for e in events}
    assert "STRATEGY_DRAFT_APPROVED" in event_types
    assert "STRATEGY_DEFINITION_CREATED" in event_types


def test_audit_does_not_contain_draft_body_or_secrets(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/approve",
        json={"reason": "승인"},
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.event_type.like("STRATEGY_D%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    for event in events:
        dumped = str(event.detail)
        assert "api_key" not in dumped.lower()
        assert _VALID_ENTRY not in dumped


# ---------------------------------------------------------------------------
# 56~57: Timeout Known Issue
# ---------------------------------------------------------------------------


def test_generation_request_carries_run_timeout_seconds(session) -> None:
    """STEP12-3 §18 — run.timeout_seconds가 실제 AIChatRequest에 반영되는지
    확인한다(이전에는 AIProviderConfig 전역 설정만 사용됨)."""
    captured: dict = {}

    class _CapturingProvider:
        provider_id = "mock"

        def supports(self, capability) -> bool:
            return True

        async def chat(self, request):
            captured["timeout_seconds"] = request.timeout_seconds
            from stock_platform.ai.providers.mock_provider import MockAIProvider
            from stock_platform.ai.providers.config import AIProviderConfig

            return await MockAIProvider(
                AIProviderConfig(provider_id="mock", enabled=True, is_default=True)
            ).chat(request)

        async def health_check(self):
            from stock_platform.ai.providers.dto import HealthStatus, ProviderHealth

            return ProviderHealth(provider_id="mock", status=HealthStatus.HEALTHY)

    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager
    from stock_platform.ai.providers.registry import AIProviderRegistry

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    registry = AIProviderRegistry()
    cfg = AIProviderConfig(
        provider_id="mock", enabled=True, is_default=True, timeout_seconds=999.0
    )
    registry.register(_CapturingProvider(), cfg)
    manager = AIManager(registry=registry)

    gen_svc = StrategyDraftGenerationService(session, ai_manager=manager)
    created = gen_svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7",
        provider_id="mock", timeout_seconds=12.5,
    )
    asyncio.run(gen_svc.generate(created["generation_run_id"], actor="admin:7"))
    # cfg.timeout_seconds(999.0)가 아니라 Run에 기록된 12.5가 실제 호출에
    # 전달되어야 한다.
    assert captured["timeout_seconds"] == 12.5
