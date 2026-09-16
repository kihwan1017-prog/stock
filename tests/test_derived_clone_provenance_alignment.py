"""Derived clone provenance — resolve_strategy_provenance / explainability 정렬."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.explainability import (
    _EvidenceCollector,
    _build_provenance_evidence,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    resolve_strategy_provenance,
    validate_provenance,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.ownership import StrategyDefinitionService

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "DERIVED_CLONE_PROV_TEST"

_VALID_ENTRY = '[{"indicator":"RSI","operator":"LT","threshold":30}]'
_VALID_EXIT = '[{"indicator":"RSI","operator":"GT","threshold":70}]'
_VALID_STOP_LOSS = '{"type":"PERCENT","value":5}'
_VALID_TAKE_PROFIT = '{"type":"PERCENT","value":10}'
_VALID_POSITION_SIZING = '{"method":"FIXED_PERCENT","value":0.1}'

_CLEANUP_SQL = [
    "DELETE FROM trading.strategy_explainability_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_draft_approval_history WHERE approval_id IN "
    "(SELECT approval_id FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "UPDATE trading.strategy_definition SET approval_id = NULL WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM trading.strategy_definition WHERE candidate_id IN "
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
def result_ids() -> list[int]:
    Session = get_session_factory()
    s = Session()
    try:
        rows = s.execute(
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 1")
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
        for sql in _CLEANUP_SQL:
            s.execute(text(sql), {"marker": _MARKER})
        s.commit()
        s.close()


def _admin_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=_REVIEWER_USER_ID,
        username="admin",
        roles=["admin"],
        is_admin=True,
    )


def _create_candidate(session, *, result_id: int) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, source_fingerprint, created_by, updated_by)
            VALUES (:cid, 'PROMOTED', 'UNKNOWN', :fp, :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "fp": "a1" * 32, "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_approved_native_strategy(session) -> StrategyDefinitionEntity:
    candidate_id = _create_candidate(session, result_id=session.info["result_ids"][0])
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    approved_req = StrategyRequestService(session).approve(
        req["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )
    draft = StrategyDraftService(session).create(
        strategy_request_id=approved_req["strategy_request_id"],
        actor="admin:7",
        title="derived clone prov test",
        timeframe="1D",
        market_type="KR_STOCK",
        entry_rule=_VALID_ENTRY,
        exit_rule=_VALID_EXIT,
        stop_loss_rule=_VALID_STOP_LOSS,
        take_profit_rule=_VALID_TAKE_PROFIT,
        position_sizing_rule=_VALID_POSITION_SIZING,
    )
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    return session.get(StrategyDefinitionEntity, approval["strategy_definition_id"])


def _clone_strategy(session, source: StrategyDefinitionEntity) -> StrategyDefinitionEntity:
    clone = StrategyDefinitionService(session).clone_strategy(
        _admin_user(),
        int(source.strategy_id),
        actor="admin",
        for_user_id=_REQUESTER_USER_ID,
        name=f"{source.name} (clone)",
    )
    session.commit()
    session.refresh(clone)
    return clone


def test_native_strategy_uses_draft_derived_provenance(session) -> None:
    """D — native draft-derived: 기존 validate_provenance 경로 유지."""
    native = _create_approved_native_strategy(session)
    resolved = resolve_strategy_provenance(session, int(native.strategy_id))
    direct = validate_provenance(session, int(native.strategy_id))

    assert resolved["provenance_mode"] == "DRAFT_DERIVED"
    assert resolved["valid"] is True
    assert resolved["valid"] == direct["valid"]
    assert resolved["failures"] == direct["failures"]


def test_valid_derived_clone_provenance_passes(session) -> None:
    """A — 정상 derived clone: source equivalence로 provenance valid."""
    native = _create_approved_native_strategy(session)
    clone = _clone_strategy(session, native)

    assert clone.source_strategy_id == native.strategy_id
    assert clone.source_draft_id is None

    result = resolve_strategy_provenance(session, int(clone.strategy_id))
    assert result["provenance_mode"] == "DERIVED_SOURCE_EQUIVALENCE"
    assert result["valid"] is True
    assert result["chain"]["derived_clone"] is True
    assert result["chain"]["source_strategy_id"] == int(native.strategy_id)
    assert result["chain"]["source_equivalent"] is True

    evidence = _EvidenceCollector()
    payload, outcome = _build_provenance_evidence(
        session,
        int(clone.strategy_id),
        current_executable_hash=None,
        selected_executable_hashes={},
        evidence=evidence,
    )
    assert payload["all_provenance_matches"] is True
    assert payload["chain"]["derived_clone"] is True
    assert outcome.summary_bucket == "POSITIVE"


def test_tampered_derived_clone_blocks_provenance(session) -> None:
    """B — promotion-sensitive field 변조 clone: provenance invalid."""
    native = _create_approved_native_strategy(session)
    clone = _clone_strategy(session, native)

    payload = dict(clone.parameter_payload or {})
    risk = dict(payload.get("risk_parameters") or {})
    risk["max_order_amount"] = 999_999_999
    payload["risk_parameters"] = risk
    clone.parameter_payload = payload
    flag_modified(clone, "parameter_payload")
    session.commit()

    result = resolve_strategy_provenance(session, int(clone.strategy_id))
    assert result["valid"] is False
    assert any("DERIVED_STRATEGY_PARAMETER_DRIFT" in f for f in result["failures"])

    evidence = _EvidenceCollector()
    prov_payload, outcome = _build_provenance_evidence(
        session,
        int(clone.strategy_id),
        current_executable_hash=None,
        selected_executable_hashes={},
        evidence=evidence,
    )
    assert prov_payload["all_provenance_matches"] is False
    assert outcome.summary_bucket == "BLOCKING"


def test_missing_source_strategy_blocks_provenance(session) -> None:
    """C — 존재하지 않는 source: FAIL/BLOCKED."""
    native = _create_approved_native_strategy(session)
    clone = _clone_strategy(session, native)

    clone.source_strategy_id = 9_999_999_999
    session.commit()

    result = resolve_strategy_provenance(session, int(clone.strategy_id))
    assert result["valid"] is False
    assert "SOURCE_STRATEGY_MISSING" in result["failures"]
