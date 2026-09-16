"""STEP 12-4 — Strategy Definition 승인 후 Backtest 준비(Strategy Snapshot).

새 Snapshot 테이블은 만들지 않는다 — trading.strategy_definition 자체가
승인 후 불변이므로(STEP12-3) 이미 Snapshot이다. 이 테스트는 조회/해시
무결성/이력(Approval History 재사용)/Export/Version 증가 정책만 다룬다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalError,
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
_MARKER = "STEP12_4_TEST"
_FINGERPRINT = "e4" * 32

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
                "ORDER BY result_id LIMIT 1"
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


# ---------------------------------------------------------------------------
# Version 정책
# ---------------------------------------------------------------------------


def test_definition_version_starts_at_one(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="최초 승인"
    )
    definition = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    assert definition.definition_version == 1


def test_definition_version_increments_on_supersede(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftApprovalService(session)

    v1 = _create_manual_draft(session, request["strategy_request_id"])
    approval_1 = svc.approve(v1["draft_id"], actor="admin:7", reason="v1 승인")
    def_1 = session.get(StrategyDefinitionEntity, approval_1["strategy_definition_id"])
    assert def_1.definition_version == 1

    v2 = _create_manual_draft(session, request["strategy_request_id"], title="v2")
    approval_2 = svc.approve(v2["draft_id"], actor="admin:7", reason="v2 승인")
    def_2 = session.get(StrategyDefinitionEntity, approval_2["strategy_definition_id"])
    assert def_2.definition_version == 2

    v3 = _create_manual_draft(session, request["strategy_request_id"], title="v3")
    approval_3 = svc.approve(v3["draft_id"], actor="admin:7", reason="v3 승인")
    def_3 = session.get(StrategyDefinitionEntity, approval_3["strategy_definition_id"])
    assert def_3.definition_version == 3


# ---------------------------------------------------------------------------
# Snapshot 조회/Validation/Provenance
# ---------------------------------------------------------------------------


def test_get_snapshot_returns_valid_hash(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    snapshot = StrategyDraftApprovalService(session).get_snapshot(
        approval["strategy_definition_id"]
    )
    assert snapshot["hash_valid"] is True
    assert snapshot["definition_hash"] == approval["definition_hash"]
    assert snapshot["source_draft_id"] == draft["draft_id"]
    assert snapshot["parameter_payload"]["entry_rule"] is not None


def test_get_snapshot_detects_tampering(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    # 서비스를 우회한 직접 UPDATE로 불변 원칙을 깨는 상황을 시뮬레이션.
    session.execute(
        text(
            "UPDATE trading.strategy_definition SET name = 'TAMPERED' "
            "WHERE strategy_id = :sid"
        ),
        {"sid": approval["strategy_definition_id"]},
    )
    session.commit()
    snapshot = StrategyDraftApprovalService(session).get_snapshot(
        approval["strategy_definition_id"]
    )
    assert snapshot["hash_valid"] is False


def test_export_snapshot_blocks_on_hash_mismatch(session) -> None:
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
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).export_snapshot(
            approval["strategy_definition_id"]
        )
    assert exc_info.value.code == "SNAPSHOT_HASH_MISMATCH"


def test_export_snapshot_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    bundle = StrategyDraftApprovalService(session).export_snapshot(
        approval["strategy_definition_id"]
    )
    assert bundle["definition_hash"] == approval["definition_hash"]
    assert bundle["provenance"]["source_draft_id"] == draft["draft_id"]
    assert bundle["provenance"]["approval_id"] == approval["approval_id"]


def test_snapshot_history_reuses_approval_history(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftApprovalService(session)
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")

    history = svc.get_snapshot_history(approval["strategy_definition_id"])["items"]
    actions = [h["action"] for h in history]
    assert "APPROVED" in actions
    assert "REVOKED" in actions


def test_snapshot_not_found(session) -> None:
    with pytest.raises(StrategyDraftApprovalError) as exc_info:
        StrategyDraftApprovalService(session).get_snapshot(999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_snapshot_api_endpoints(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    definition_id = approval["strategy_definition_id"]
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)

    snap_resp = client.get(
        f"/api/v1/admin/strategies/{definition_id}/snapshot",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert snap_resp.status_code == 200
    assert snap_resp.json()["hash_valid"] is True

    history_resp = client.get(
        f"/api/v1/admin/strategies/{definition_id}/snapshot/history",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert history_resp.status_code == 200
    assert len(history_resp.json()["items"]) >= 1

    export_resp = client.get(
        f"/api/v1/admin/strategies/{definition_id}/snapshot/export",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert export_resp.status_code == 200
    assert export_resp.json()["definition_hash"] == approval["definition_hash"]


def test_snapshot_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/admin/strategies/1/snapshot").status_code == 401
    assert client.get("/api/v1/admin/strategies/1/snapshot/history").status_code == 401
    assert client.get("/api/v1/admin/strategies/1/snapshot/export").status_code == 401


def test_snapshot_audit_recorded(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = _create_manual_draft(session, request["strategy_request_id"])
    approval = StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )
    definition_id = approval["strategy_definition_id"]
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.get(
        f"/api/v1/admin/strategies/{definition_id}/snapshot",
        headers={"X-Admin-API-Key": admin_key},
    )
    client.get(
        f"/api/v1/admin/strategies/{definition_id}/snapshot/export",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("STRATEGY_SNAPSHOT%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(5)
    ).all()
    event_types = {e[0] for e in events}
    assert "STRATEGY_SNAPSHOT_VIEWED" in event_types
    assert "STRATEGY_SNAPSHOT_EXPORTED" in event_types


# ---------------------------------------------------------------------------
# 승인 후 변경 차단 회귀(STEP12-3 정책 유지 확인)
# ---------------------------------------------------------------------------


def test_definition_still_immutable_after_approval(session) -> None:
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
