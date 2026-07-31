"""STEP 12-1 — AI Candidate -> Strategy Request 승인 게이트 통합 테스트.

실제 PostgreSQL(로컬 dev DB)을 사용한다. 이 파일이 만든 행은 각 테스트의
finally에서 명시적으로 정리한다. strategy.candidate_result는 기존 행을
읽기 전용으로 재사용하고, ai.candidate_lifecycle 테스트 행만 신규 생성한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from stock_platform.ai.strategy_request.service import (
    StrategyRequestError,
    StrategyRequestService,
)
from stock_platform.api.main import app
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7


@pytest.fixture()
def session():
    Session = get_session_factory()
    s = Session()
    try:
        result_id = s.execute(
            text("SELECT result_id FROM strategy.candidate_result LIMIT 1")
        ).scalar()
        if result_id is None:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        s.info["result_id"] = int(result_id)
        yield s
    finally:
        s.rollback()
        s.execute(
            text(
                "DELETE FROM ai.strategy_request_history WHERE strategy_request_id "
                "IN (SELECT strategy_request_id FROM ai.strategy_request "
                "WHERE candidate_id IN (SELECT candidate_id FROM ai.candidate_lifecycle "
                "WHERE created_by = 'STEP12_1_TEST'))"
            )
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_request WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle "
                "WHERE created_by = 'STEP12_1_TEST')"
            )
        )
        s.execute(
            text(
                "DELETE FROM ai.candidate_lifecycle WHERE created_by = 'STEP12_1_TEST'"
            )
        )
        s.commit()
        s.close()


def _create_candidate(session, *, lifecycle_status: str) -> int:
    result_id = session.info["result_id"]
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, created_by, updated_by)
            VALUES (:cid, :status, 'UNKNOWN', 'STEP12_1_TEST', 'STEP12_1_TEST')
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "status": lifecycle_status},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


# candidate_id는 candidate_lifecycle.candidate_id = strategy.candidate_result.result_id
# 이므로, 서로 다른 lifecycle_status를 테스트하려면 서로 다른 result_id가 필요하다.
# 로컬 dev DB에는 result_id 1, 2 두 개만 있으므로, 실제로는 하나의 result_id를
# 재사용해 이전 테스트의 candidate_lifecycle 행을 정리한 뒤 다음 테스트를 진행한다.
# (각 테스트가 독립적으로 자신의 후보를 만들고 fixture teardown에서 정리한다.)


def test_create_success_with_active_candidate(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)

    result = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note="테스트 요청",
        actor=f"user:{_REQUESTER_USER_ID}",
    )

    assert result["status"] == "PENDING_REVIEW"
    assert result["candidate_id"] == candidate_id
    assert result["user_id"] == _REQUESTER_USER_ID
    assert result["candidate_lifecycle_status_snapshot"] == "PROMOTED"

    history = svc.get_history(result["strategy_request_id"])
    assert len(history["items"]) == 1
    assert history["items"][0]["action"] == "CREATE"
    assert history["items"][0]["new_status"] == "PENDING_REVIEW"


def test_create_blocks_duplicate_active_request(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )

    with pytest.raises(StrategyRequestError) as exc:
        svc.create(
            candidate_id=candidate_id,
            user_id=_REQUESTER_USER_ID,
            request_note=None,
            actor=f"user:{_REQUESTER_USER_ID}",
        )
    assert exc.value.code == "DUPLICATE_ACTIVE_REQUEST"


def test_create_blocks_revoked_candidate(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="REVOKED")
    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError) as exc:
        svc.create(
            candidate_id=candidate_id,
            user_id=_REQUESTER_USER_ID,
            request_note=None,
            actor=f"user:{_REQUESTER_USER_ID}",
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE"


def test_create_blocks_expired_candidate(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="EXPIRED")
    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError) as exc:
        svc.create(
            candidate_id=candidate_id,
            user_id=_REQUESTER_USER_ID,
            request_note=None,
            actor=f"user:{_REQUESTER_USER_ID}",
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE"


def test_create_blocks_superseded_candidate(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="SUPERSEDED")
    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError) as exc:
        svc.create(
            candidate_id=candidate_id,
            user_id=_REQUESTER_USER_ID,
            request_note=None,
            actor=f"user:{_REQUESTER_USER_ID}",
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE"


def test_create_blocks_nonexistent_candidate(session) -> None:
    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError) as exc:
        svc.create(
            candidate_id=999_999_999,
            user_id=_REQUESTER_USER_ID,
            request_note=None,
            actor=f"user:{_REQUESTER_USER_ID}",
        )
    assert exc.value.code == "CANDIDATE_NOT_FOUND"


def test_reconnect_after_terminal_state_allowed(session) -> None:
    """이전 요청이 종결 상태(CANCELLED)가 되면 동일 candidate로 재요청 가능."""
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    first = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    svc.cancel(
        first["strategy_request_id"],
        user_id=_REQUESTER_USER_ID,
        reason="취소",
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    second = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note="재요청",
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    assert second["strategy_request_id"] != first["strategy_request_id"]
    assert second["status"] == "PENDING_REVIEW"


def test_db_partial_unique_index_blocks_concurrent_duplicate(session) -> None:
    """서비스 사전검사를 우회한 raw INSERT도 부분 유니크 인덱스가 최종 차단."""
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    session.execute(
        text(
            """
            INSERT INTO ai.strategy_request
            (candidate_id, user_id, status, candidate_lifecycle_status_snapshot)
            VALUES (:cid, :uid, 'PENDING_REVIEW', 'PROMOTED')
            """
        ),
        {"cid": candidate_id, "uid": _REQUESTER_USER_ID},
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO ai.strategy_request
                (candidate_id, user_id, status, candidate_lifecycle_status_snapshot)
                VALUES (:cid, :uid, 'PENDING_REVIEW', 'PROMOTED')
                """
            ),
            {"cid": candidate_id, "uid": _REQUESTER_USER_ID},
        )
        session.commit()
    session.rollback()


def test_cancel_requires_ownership(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    with pytest.raises(StrategyRequestError) as exc:
        svc.cancel(
            created["strategy_request_id"],
            user_id=999_999,
            reason=None,
            actor="user:999999",
        )
    assert exc.value.code == "OWNERSHIP_DENIED"


def test_get_owned_requires_ownership(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    with pytest.raises(StrategyRequestError) as exc:
        svc.get_owned(created["strategy_request_id"], user_id=999_999)
    assert exc.value.code == "OWNERSHIP_DENIED"

    ok = svc.get_owned(
        created["strategy_request_id"], user_id=_REQUESTER_USER_ID
    )
    assert ok["strategy_request_id"] == created["strategy_request_id"]


def test_approve_transitions_and_records_reviewer(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="ACTIVE_REVIEW")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    approved = svc.approve(
        created["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="근거 확인 완료",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewer_user_id"] == _REVIEWER_USER_ID
    assert approved["reviewed_at"] is not None
    assert approved["version"] == 2

    history = svc.get_history(created["strategy_request_id"])
    actions = [h["action"] for h in history["items"]]
    assert "APPROVE" in actions


def test_reject_requires_review_note(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    with pytest.raises(StrategyRequestError) as exc:
        svc.reject(
            created["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note=None,
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    assert exc.value.code == "REVIEW_NOTE_REQUIRED"

    rejected = svc.reject(
        created["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="근거 부족",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["review_note"] == "근거 부족"


def test_terminal_state_transition_blocked(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    svc.cancel(
        created["strategy_request_id"],
        user_id=_REQUESTER_USER_ID,
        reason=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    with pytest.raises(StrategyRequestError) as exc:
        svc.approve(
            created["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note="승인 시도",
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    assert exc.value.code == "INVALID_STATE_TRANSITION"


def test_list_filters_by_user(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    own = svc.list(user_id=_REQUESTER_USER_ID)
    assert any(
        i["strategy_request_id"] == created["strategy_request_id"]
        for i in own["items"]
    )
    other = svc.list(user_id=999_999)
    assert all(
        i["strategy_request_id"] != created["strategy_request_id"]
        for i in other["items"]
    )


def test_not_found_raises_clear_error(session) -> None:
    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError) as exc:
        svc.get(999_999_999)
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# API 레벨 — 인증/권한 (TestClient, 실DB 세션 대신 앱 라우팅/의존성 확인)
# ---------------------------------------------------------------------------


def test_user_strategy_requests_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/user/strategy-requests")
    assert resp.status_code == 401


def test_admin_strategy_requests_require_admin() -> None:
    # admin_strategy_requests 라우터는 admin_ai_candidate_lifecycle 등과
    # 동일하게 require_admin(자체 JWT/X-Admin-API-Key 파싱, get_current_user에
    # 의존하지 않음)으로 게이팅된다. 자격증명 없이 호출하면 401(미인증)이며,
    # 이는 라우터가 실제로 게이팅되어 있음을 증명한다.
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/admin/strategy-requests")
    assert resp.status_code == 401


def test_openapi_lists_strategy_request_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/user/strategy-requests" in paths
    assert "post" in paths["/api/v1/user/strategy-requests"]
    assert "get" in paths["/api/v1/user/strategy-requests"]
    assert (
        "/api/v1/user/strategy-requests/{strategy_request_id}/cancel" in paths
    )
    assert "/api/v1/admin/strategy-requests" in paths
    assert (
        "/api/v1/admin/strategy-requests/{strategy_request_id}/approve" in paths
    )
    assert (
        "/api/v1/admin/strategy-requests/{strategy_request_id}/reject" in paths
    )
    assert (
        "/api/v1/admin/strategy-requests/{strategy_request_id}/history" in paths
    )


# ---------------------------------------------------------------------------
# STEP12-2-2 선행 정리 — user_strategy_requests GET의 trading:write RBAC
# 오적용을 trading:read로 수정한 회귀 테스트.
# ---------------------------------------------------------------------------


def _read_only_user(user_id: int) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}",
        roles=["user"],
        permissions=["trading:read"],  # trading:write 없음
    )


def test_user_strategy_requests_list_succeeds_with_read_permission_only(
    session,
) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )

    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(
        _REQUESTER_USER_ID
    )
    try:
        resp = client.get("/api/v1/user/strategy-requests")
        assert resp.status_code == 200
        assert any(
            item["strategy_request_id"] == created["strategy_request_id"]
            for item in resp.json()["items"]
        )
    finally:
        app.dependency_overrides.clear()


def test_user_strategy_requests_detail_succeeds_with_read_permission_only(
    session,
) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )

    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(
        _REQUESTER_USER_ID
    )
    try:
        resp = client.get(
            f"/api/v1/user/strategy-requests/{created['strategy_request_id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["strategy_request_id"] == created["strategy_request_id"]
    finally:
        app.dependency_overrides.clear()


def test_user_strategy_requests_detail_blocks_other_users(session) -> None:
    candidate_id = _create_candidate(session, lifecycle_status="PROMOTED")
    svc = StrategyRequestService(session)
    created = svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )

    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(999_999)
    try:
        resp = client.get(
            f"/api/v1/user/strategy-requests/{created['strategy_request_id']}"
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
