"""STEP 12-5 — Strategy Definition Backtest Readiness & Reproducibility.

새 Entity/Table 없이 STEP12-2-1/12-2-2/12-3 엔티티만 재사용해 Provenance
Chain(Candidate->Draft->Approval->Definition)과 Backtest Readiness를
검증한다. 이 파일은 신규/관련 회귀만 다룬다.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    check_readiness,
    validate_provenance,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_5_TEST"
_FINGERPRINT = "f5" * 32

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
                "SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 1"
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
    "DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker",
]


@pytest.fixture()
def session(result_ids: list[int]):
    Session = get_session_factory()
    s = Session()
    try:
        s.info["result_ids"] = result_ids
        yield s
    finally:
        s.rollback()
        for sql in _CLEANUP_SQL:
            s.execute(text(sql), {"marker": _MARKER})
        s.commit()
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


# ---------------------------------------------------------------------------
# Provenance Chain
# ---------------------------------------------------------------------------


def test_provenance_valid_for_manual_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    result = validate_provenance(session, approval["strategy_definition_id"])
    assert result["valid"] is True
    assert result["failures"] == []
    assert result["chain"]["source_draft_id"] == draft["draft_id"]
    assert result["chain"]["approval_id"] == approval["approval_id"]


def test_provenance_valid_for_ai_draft_includes_generation_chain(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    gen_result = _generate_ai_draft(session, request["strategy_request_id"])
    draft_id = gen_result["draft"]["draft_id"]
    approval = StrategyDraftApprovalService(session).approve(
        draft_id, actor="admin:7", reason="AI 초안 승인"
    )
    result = validate_provenance(session, approval["strategy_definition_id"])
    assert result["valid"] is True
    assert result["chain"]["generation_run_id"] == gen_result["run"]["generation_run_id"]
    assert result["chain"]["generation_attempt_id"] is not None


def test_provenance_survives_candidate_revocation_after_approval(session) -> None:
    """승인 이후 Candidate가 철회되어도 이미 확정된 Snapshot의 Provenance
    Chain 자체(내부 교차 참조 일치)는 계속 유효해야 한다 — Readiness는
    "현재 Candidate 상태"가 아니라 "승인 시점에 고정된 기록의 내부 일관성"
    을 검증하는 것이 STEP12-3의 불변 정책과 일관된 설계다."""
    from stock_platform.ai.candidate_lifecycle.service import (
        AICandidateLifecycleService,
    )

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    AICandidateLifecycleService(session).expire(
        candidate_id=request["candidate_id"], expected_version=1,
        actor="admin:test", reason="테스트 만료",
    )
    result = validate_provenance(session, approval["strategy_definition_id"])
    assert result["valid"] is True


def test_provenance_not_found(session) -> None:
    with pytest.raises(ReadinessError) as exc_info:
        validate_provenance(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


def test_provenance_detects_definition_approval_mismatch(session) -> None:
    """서비스를 우회한 직접 UPDATE로 교차 참조가 깨진 상황을 재현한다."""
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    session.execute(
        text(
            "UPDATE ai.strategy_draft_approval SET strategy_definition_id = NULL "
            "WHERE approval_id = :aid"
        ),
        {"aid": approval["approval_id"]},
    )
    session.commit()
    result = validate_provenance(session, approval["strategy_definition_id"])
    assert result["valid"] is False
    assert any("APPROVAL_DEFINITION_MISMATCH" in f for f in result["failures"])


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_readiness_true_for_freshly_approved_manual_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    result = check_readiness(session, approval["strategy_definition_id"])
    assert result["ready"] is True
    assert result["checks"]["is_active"] is True
    assert result["checks"]["hash_valid"] is True
    assert result["checks"]["payload_complete"] is True
    assert result["checks"]["provenance_valid"] is True
    assert result["failure_reasons"] == []


def test_readiness_false_when_revoked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")
    result = check_readiness(session, approval["strategy_definition_id"])
    assert result["ready"] is False
    assert result["checks"]["is_active"] is False


def test_readiness_false_when_hash_tampered(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    session.execute(
        text(
            "UPDATE trading.strategy_definition SET name = 'TAMPERED' "
            "WHERE strategy_id = :sid"
        ),
        {"sid": approval["strategy_definition_id"]},
    )
    session.commit()
    result = check_readiness(session, approval["strategy_definition_id"])
    assert result["ready"] is False
    assert result["checks"]["hash_valid"] is False


def test_readiness_false_when_payload_incomplete(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    payload = dict(definition.parameter_payload or {})
    payload.pop("stop_loss_rule", None)
    definition.parameter_payload = payload
    # definition_hash는 의도적으로 갱신하지 않는다 — 필드 누락은 hash 무결성과는
    # 별개 축의 실패(payload_complete)이며, 이 테스트는 그 축만 검증한다.
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(definition, "parameter_payload")
    session.commit()
    result = check_readiness(session, approval["strategy_definition_id"])
    assert result["ready"] is False
    assert result["checks"]["payload_complete"] is False
    assert any("stop_loss_rule" in r for r in result["failure_reasons"])


def test_readiness_not_found(session) -> None:
    with pytest.raises(ReadinessError) as exc_info:
        check_readiness(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Definition Version 증가 정책 검증(STEP12-4 인계 §2)
# ---------------------------------------------------------------------------


def test_definition_version_policy_still_correct_across_multiple_supersessions(
    session,
) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftApprovalService(session)
    versions = []
    for i in range(3):
        draft = _create_manual_draft(
            session, request["strategy_request_id"], title=f"v{i}"
        )
        approval = svc.approve(draft["draft_id"], actor="admin:7", reason=f"승인 {i}")
        definition = session.get(
            StrategyDefinitionEntity, approval["strategy_definition_id"]
        )
        versions.append(definition.definition_version)
    assert versions == [1, 2, 3]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_readiness_api_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/readiness",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


def test_provenance_api_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/provenance",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_readiness_provenance_api_require_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/admin/strategies/1/readiness").status_code == 401
    assert client.get("/api/v1/admin/strategies/1/provenance").status_code == 401


def test_readiness_audit_recorded(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/readiness",
        headers={"X-Admin-API-Key": admin_key},
    )
    client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/provenance",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(
            AuditEvent.event_type.in_(
                ["READINESS_CHECK", "READINESS_FAILED", "PROVENANCE_VALIDATED"]
            )
        )
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(5)
    ).all()
    event_types = {e[0] for e in events}
    assert "READINESS_CHECK" in event_types
    assert "PROVENANCE_VALIDATED" in event_types
