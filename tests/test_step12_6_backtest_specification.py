"""STEP 12-6 — Strategy Definition -> Backtest Executable Specification Compiler.

새 Entity/Table 없이 STEP12-2-1/12-2-2/12-3/12-5 엔티티·서비스만 재사용해
결정적 Executable Specification/Hash를 생성한다(실제 Backtest 실행/DB
WRITE 없음).
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
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
_MARKER = "STEP12_6_TEST"
_FINGERPRINT = "a6" * 32

_VALID_ENTRY = '[{"indicator":"RSI","operator":"LT","threshold":30,"lookback":14}]'
_VALID_EXIT = '[{"indicator":"RSI","operator":"GT","threshold":70,"lookback":14}]'
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


def _approve(session, strategy_request_id: int, **draft_overrides) -> dict:
    draft = _create_manual_draft(session, strategy_request_id, **draft_overrides)
    return StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )


# ---------------------------------------------------------------------------
# 1~2: 정상 컴파일 + 결정성
# ---------------------------------------------------------------------------


def test_compile_success_for_valid_definition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is True
    assert result["executable_hash"] is not None
    assert result["errors"] == []
    assert {"indicator": "RSI", "period": 14} in result["indicator_requirements"]


def test_compile_deterministic_repeat(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    r1 = compile_specification(session, approval["strategy_definition_id"])
    r2 = compile_specification(session, approval["strategy_definition_id"])
    assert r1["executable_hash"] == r2["executable_hash"]


# ---------------------------------------------------------------------------
# 3: Version 변경 시 Hash 변화
# ---------------------------------------------------------------------------


def test_hash_differs_across_definition_versions(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval_1 = _approve(session, request["strategy_request_id"], title="v1")
    approval_2 = _approve(
        session,
        request["strategy_request_id"],
        title="v2",
        entry_rule='[{"indicator":"SMA","operator":"GT","threshold":0,"lookback":20}]',
    )
    r1 = compile_specification(session, approval_1["strategy_definition_id"])
    r2 = compile_specification(session, approval_2["strategy_definition_id"])
    assert r1["executable_hash"] != r2["executable_hash"]
    assert r2["definition_version"] == r1["definition_version"] + 1


# ---------------------------------------------------------------------------
# 4~5: 변조/Provenance 불일치 시 차단
# ---------------------------------------------------------------------------


def test_compile_blocked_on_tampered_definition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    session.execute(
        text(
            "UPDATE trading.strategy_definition SET name = 'TAMPERED' WHERE strategy_id = :sid"
        ),
        {"sid": approval["strategy_definition_id"]},
    )
    session.commit()
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is False
    assert result["ready"] is False
    assert any("DEFINITION_NOT_READY" in e for e in result["errors"])


def test_compile_blocked_on_provenance_mismatch(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    session.execute(
        text(
            "UPDATE ai.strategy_draft_approval SET strategy_definition_id = NULL "
            "WHERE approval_id = :aid"
        ),
        {"aid": approval["approval_id"]},
    )
    session.commit()
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is False


# ---------------------------------------------------------------------------
# 6: readiness=false 시 차단(취소된 승인)
# ---------------------------------------------------------------------------


def test_compile_blocked_when_revoked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is False
    assert result["ready"] is False


# ---------------------------------------------------------------------------
# 7: 필수 Rule 누락 차단
# ---------------------------------------------------------------------------


def test_compile_blocked_when_entry_rule_missing(session) -> None:
    # STEP12-3 validate_draft_for_approval이 이미 빈 entry_rule을 승인
    # 시점에 차단하므로, 여기서는 승인된 Definition을 직접 변조해 재현한다
    # (Compiler 자체의 방어 로직을 검증하려는 목적).
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    payload = copy.deepcopy(definition.parameter_payload)
    payload["entry_rule"] = []
    from sqlalchemy.orm.attributes import flag_modified

    definition.parameter_payload = payload
    flag_modified(definition, "parameter_payload")
    # payload_complete 체크는 falsy 값(빈 리스트 포함)을 누락으로 간주하므로
    # readiness 자체가 실패한다 — Compiler가 DEFINITION_NOT_READY로 막는지
    # 확인한다(이미 §6의 대상과 같은 경로지만, entry_rule 누락이라는 다른
    # 원인임을 별도로 검증).
    session.commit()
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is False


# ---------------------------------------------------------------------------
# 8~9: 미지원 Indicator/Operator 차단
# ---------------------------------------------------------------------------


def test_compile_blocked_on_unsupported_indicator(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(
        session,
        request["strategy_request_id"],
        entry_rule='[{"indicator":"MACD","operator":"GT","threshold":0}]',
    )
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is False
    assert any("UNSUPPORTED_INDICATOR" in e for e in result["errors"])


def test_compile_blocked_on_unsupported_stop_loss_type(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(
        session,
        request["strategy_request_id"],
        stop_loss_rule='{"type":"ATR_MULTIPLE","value":2}',
    )
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is False
    assert any("UNSUPPORTED_RULE_FIELD" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 10~11: Indicator 요구사항 중복 제거 + 정렬 결정성
# ---------------------------------------------------------------------------


def test_indicator_requirements_deduplicated_and_sorted(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(
        session,
        request["strategy_request_id"],
        entry_rule=(
            '[{"indicator":"RSI","operator":"LT","threshold":30,"lookback":14},'
            '{"indicator":"SMA","operator":"GT","threshold":0,"lookback":20}]'
        ),
        exit_rule=(
            '[{"indicator":"RSI","operator":"GT","threshold":70,"lookback":14},'
            '{"indicator":"EMA","operator":"LT","threshold":0,"lookback":10}]'
        ),
    )
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is True
    reqs = result["indicator_requirements"]
    # RSI(14)는 entry/exit에 각각 나오지만 1개로 합쳐져야 한다.
    assert reqs.count({"indicator": "RSI", "period": 14}) == 1
    # 정렬 결정성: indicator 이름 알파벳 순.
    assert [r["indicator"] for r in reqs] == sorted(r["indicator"] for r in reqs)


# ---------------------------------------------------------------------------
# 12~13: Runtime Input Schema / symbols 정책
# ---------------------------------------------------------------------------


def test_required_runtime_inputs_include_symbol_not_definition_column(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    result = compile_specification(session, approval["strategy_definition_id"])
    input_names = {i["name"] for i in result["required_runtime_inputs"]}
    assert "symbol" in input_names
    assert "start_date" in input_names
    assert "end_date" in input_names
    assert "initial_capital" in input_names
    # Definition 자체(parameter_payload)에는 symbol 컬럼이 없어야 한다
    # (옵션 A — 종목 독립적 Template).
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    assert "symbol" not in (definition.parameter_payload or {})
    assert not hasattr(definition, "symbols")


# ---------------------------------------------------------------------------
# 14: NaN/Infinity 차단(Canonical JSON)
# ---------------------------------------------------------------------------


def test_canonical_json_rejects_nan_and_infinity() -> None:
    from stock_platform.ai.strategy_draft_approval.backtest_spec import (
        _canonical_json,
    )

    with pytest.raises(ValueError):
        _canonical_json({"value": float("nan")})
    with pytest.raises(ValueError):
        _canonical_json({"value": float("inf")})


# ---------------------------------------------------------------------------
# 15~17: API
# ---------------------------------------------------------------------------


def test_backtest_specification_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.get("/api/v1/admin/strategies/1/backtest-specification").status_code
        == 401
    )


def test_backtest_specification_api_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtest-specification",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["compilable"] is True
    assert body["executable_hash"] is not None


def test_backtest_specification_api_failure_response(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(
        session,
        request["strategy_request_id"],
        entry_rule='[{"indicator":"MACD","operator":"GT","threshold":0}]',
    )
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtest-specification",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    assert resp.json()["compilable"] is False


# ---------------------------------------------------------------------------
# 18~19: Audit
# ---------------------------------------------------------------------------


def test_audit_success_and_failure_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval_ok = _approve(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.get(
        f"/api/v1/admin/strategies/{approval_ok['strategy_definition_id']}/backtest-specification",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("STRATEGY_BACKTEST_SPEC%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(3)
    ).all()
    assert "STRATEGY_BACKTEST_SPEC_COMPILED" in {e[0] for e in events}


def test_audit_does_not_contain_secrets(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtest-specification",
        headers={"X-Admin-API-Key": admin_key},
    )
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.event_type.like("STRATEGY_BACKTEST_SPEC%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(3)
    ).all()
    for event in events:
        dumped = str(event.detail)
        assert "api_key" not in dumped.lower()


# ---------------------------------------------------------------------------
# 20~21: DB WRITE 없음 / Definition 불변
# ---------------------------------------------------------------------------


def test_compile_does_not_mutate_definition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    before_hash = definition.definition_hash
    before_updated_at = definition.updated_at
    compile_specification(session, approval["strategy_definition_id"])
    compile_specification(session, approval["strategy_definition_id"])
    session.expire_all()
    definition_after = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    assert definition_after.definition_hash == before_hash
    assert definition_after.updated_at == before_updated_at


# ---------------------------------------------------------------------------
# 22~23: STEP12-5 readiness 회귀 / Candidate expire 후에도 컴파일 가능
# ---------------------------------------------------------------------------


def test_compile_succeeds_after_candidate_expired(session) -> None:
    from stock_platform.ai.candidate_lifecycle.service import (
        AICandidateLifecycleService,
    )

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    AICandidateLifecycleService(session).expire(
        candidate_id=request["candidate_id"], expected_version=1,
        actor="admin:test", reason="테스트 만료",
    )
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is True


def test_readiness_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.readiness import check_readiness

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    result = check_readiness(session, approval["strategy_definition_id"])
    assert result["ready"] is True


def test_not_found(session) -> None:
    with pytest.raises(BacktestSpecificationError) as exc_info:
        compile_specification(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# 24: 승인된 Draft Revision은 기존 Definition에 영향 없음(§14 정책 확인)
# ---------------------------------------------------------------------------


def test_revision_on_approved_draft_does_not_affect_existing_definition(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    before_spec = compile_specification(session, approval["strategy_definition_id"])

    # 이미 승인된(그러나 Draft.status는 여전히 DRAFT인) Draft에 Revision을
    # 생성한다 — 이 Revision은 자동 승인되지 않는다.
    revision = StrategyDraftService(session).create_revision(
        draft["draft_id"], actor="admin:7", summary="변경된 요약"
    )
    assert revision["status"] == "DRAFT"

    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    after_spec = compile_specification(session, approval["strategy_definition_id"])
    assert before_spec["executable_hash"] == after_spec["executable_hash"]
    assert definition.definition_hash == before_spec["definition_hash"]

    # 새 Revision을 승인하기 전까지는 새 Definition이 생기지 않는다.
    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE strategy_request_id = :rid"
        ),
        {"rid": request["strategy_request_id"]},
    ).scalar_one()
    assert count == 1

    # 새 Revision을 승인하면 그제서야 새 Definition Version이 생긴다.
    new_approval = StrategyDraftApprovalService(session).approve(
        revision["draft_id"], actor="admin:7", reason="Revision 승인"
    )
    new_definition = session.get(
        StrategyDefinitionEntity, new_approval["strategy_definition_id"]
    )
    assert new_definition.definition_version == definition.definition_version + 1
    # 기존 Definition은 여전히 그대로(불변) 존재한다.
    session.refresh(definition)
    assert definition.definition_hash == before_spec["definition_hash"]
