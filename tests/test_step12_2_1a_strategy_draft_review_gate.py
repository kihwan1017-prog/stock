"""STEP 12-2-1A — Strategy Draft 생성 전 무결성·권한·Audit 보완 통합 테스트.

STEP12-2-1 완료 보고 검토에서 발견된 결함(Draft 생성 시 Candidate 재검증
부재, USER 조회 API의 trading:write 오적용, History 조회 Audit 누락)에
대한 회귀 테스트다. 실제 PostgreSQL(로컬 dev DB)을 사용하며, 동시성
테스트(#13~15)는 실제 스레드 + 실제 세션 2개로 검증한다.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.candidate_lifecycle.service import AICandidateLifecycleService
from stock_platform.ai.strategy_draft.entities import StrategyDraftEntity
from stock_platform.ai.strategy_draft.service import (
    StrategyDraftError,
    StrategyDraftService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_OTHER_USER_ID = 999_999
_MARKER = "STEP12_2_1A_TEST"
_FINGERPRINT = "b2" * 32


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
            text(
                "DELETE FROM ai.candidate_revocation WHERE candidate_id IN "
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


def _create_approved_request(session, *, result_id: int, fingerprint=_FINGERPRINT) -> dict:
    candidate_id = _create_candidate(session, result_id=result_id, fingerprint=fingerprint)
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    approved = StrategyRequestService(session).approve(
        req["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )
    return approved


def _draft_kwargs(**overrides) -> dict:
    base = {
        "actor": "admin:7",
        "title": "재검증 테스트 초안",
        "timeframe": "1D",
        "market_type": "KR_STOCK",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1~4: Strategy Request 상태 검증
# ---------------------------------------------------------------------------


def test_create_succeeds_for_approved_request(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    assert draft["status"] == "DRAFT"
    assert draft["candidate_fingerprint"] == _FINGERPRINT


@pytest.mark.parametrize(
    "transition",
    ["pending_review", "rejected", "cancelled"],
)
def test_create_blocked_for_non_approved_request(session, transition) -> None:
    candidate_id = _create_candidate(session, result_id=session.info["result_ids"][0])
    req_svc = StrategyRequestService(session)
    req = req_svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    if transition == "rejected":
        req_svc.reject(
            req["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note="사유",
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    elif transition == "cancelled":
        req_svc.cancel(
            req["strategy_request_id"],
            user_id=_REQUESTER_USER_ID,
            reason=None,
            actor=f"user:{_REQUESTER_USER_ID}",
        )
    # pending_review: 아무 전이도 하지 않음(기본 상태)

    with pytest.raises(StrategyDraftError) as exc:
        StrategyDraftService(session).create(
            strategy_request_id=req["strategy_request_id"], **_draft_kwargs()
        )
    assert exc.value.code == "STRATEGY_REQUEST_NOT_APPROVED"


# ---------------------------------------------------------------------------
# 5~9: Candidate 재검증 / Fingerprint 검증
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lifecycle_status",
    ["REVOKED", "EXPIRED", "SUPERSEDED", "STALE"],
)
def test_create_blocked_for_inactive_candidate(session, lifecycle_status) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = :status "
            "WHERE candidate_id = :cid"
        ),
        {"status": lifecycle_status, "cid": request["candidate_id"]},
    )
    session.commit()

    with pytest.raises(StrategyDraftError) as exc:
        StrategyDraftService(session).create(
            strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"


def test_create_blocked_when_fingerprint_changed(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET source_fingerprint = :fp "
            "WHERE candidate_id = :cid"
        ),
        {"fp": "c3" * 32, "cid": request["candidate_id"]},
    )
    session.commit()

    with pytest.raises(StrategyDraftError) as exc:
        StrategyDraftService(session).create(
            strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
        )
    assert exc.value.code == "CANDIDATE_FINGERPRINT_CHANGED"


def test_create_blocked_when_approval_fingerprint_missing(session) -> None:
    """STEP12-1A 이전 승인 데이터(레거시)처럼 candidate_fingerprint_at_review가
    NULL인 경우 안전을 위해 생성을 차단한다(묵시적 통과 금지)."""
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.strategy_request SET candidate_fingerprint_at_review = NULL "
            "WHERE strategy_request_id = :id"
        ),
        {"id": request["strategy_request_id"]},
    )
    session.commit()

    with pytest.raises(StrategyDraftError) as exc:
        StrategyDraftService(session).create(
            strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
        )
    assert exc.value.code == "CANDIDATE_FINGERPRINT_CHANGED"


# ---------------------------------------------------------------------------
# 10~12: 검증 실패 시 부분 commit 금지
# ---------------------------------------------------------------------------


def test_validation_failure_creates_no_draft_or_history(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()

    with pytest.raises(StrategyDraftError):
        StrategyDraftService(session).create(
            strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
        )
    session.rollback()

    remaining = StrategyDraftService(session).list(
        strategy_request_id=request["strategy_request_id"]
    )
    assert remaining["items"] == []


def test_validation_failure_leaves_existing_active_draft_unchanged(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    v1 = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    assert v1["status"] == "DRAFT"

    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()

    with pytest.raises(StrategyDraftError) as exc:
        StrategyDraftService(session).create(
            strategy_request_id=request["strategy_request_id"],
            **_draft_kwargs(title="v2 시도"),
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"
    session.rollback()

    v1_reloaded = StrategyDraftService(session).get(v1["draft_id"])
    assert v1_reloaded["status"] == "DRAFT"  # SUPERSEDED로 바뀌지 않아야 함

    history = StrategyDraftService(session).get_history(v1["draft_id"])
    assert [h["action"] for h in history["items"]] == ["CREATE"]


# ---------------------------------------------------------------------------
# 13~15: 동시성 — Draft 생성과 revoke/expire/supersede 경합
# ---------------------------------------------------------------------------


def test_create_vs_expire_concurrency_blocks_creation(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
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
                candidate_id=candidate_id,
                expected_version=1,
                actor="admin:concurrency-test",
                reason="STEP12-2-1A concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _create_thread() -> None:
        assert lock_acquired.wait(timeout=5), "expire 스레드가 잠금을 획득하지 못함"
        s_b = Session()
        try:
            StrategyDraftService(s_b).create(
                strategy_request_id=request["strategy_request_id"],
                **_draft_kwargs(),
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_expire = threading.Thread(target=_expire_thread)
    t_create = threading.Thread(target=_create_thread)
    t_expire.start()
    t_create.start()
    t_expire.join(timeout=10)
    t_create.join(timeout=10)

    draft_errors = [e for e in errors if isinstance(e, StrategyDraftError)]
    assert len(draft_errors) == 1
    assert draft_errors[0].code == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"

    remaining = StrategyDraftService(session).list(
        strategy_request_id=request["strategy_request_id"]
    )
    assert remaining["items"] == []


def test_create_vs_revoke_concurrency_blocks_creation(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
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
            svc = AICandidateLifecycleService(s_a)
            requested = svc.request_revocation(
                candidate_id=candidate_id,
                expected_version=1,
                actor="admin:concurrency-test",
                reason="STEP12-2-1A concurrency test",
            )
            svc.approve_revocation(
                candidate_id=candidate_id,
                revocation_key=requested["revocation"]["revocation_key"],
                expected_version=requested["lifecycle"]["lifecycle_version"],
                actor="admin:concurrency-test",
                reason="STEP12-2-1A concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _create_thread() -> None:
        assert lock_acquired.wait(timeout=5), "revoke 스레드가 잠금을 획득하지 못함"
        s_b = Session()
        try:
            StrategyDraftService(s_b).create(
                strategy_request_id=request["strategy_request_id"],
                **_draft_kwargs(),
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_revoke = threading.Thread(target=_revoke_thread)
    t_create = threading.Thread(target=_create_thread)
    t_revoke.start()
    t_create.start()
    t_revoke.join(timeout=10)
    t_create.join(timeout=10)

    draft_errors = [e for e in errors if isinstance(e, StrategyDraftError)]
    assert len(draft_errors) == 1
    assert draft_errors[0].code == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"


def test_create_vs_supersede_concurrency_blocks_creation(session) -> None:
    if len(session.info["result_ids"]) < 2:
        pytest.skip("supersede 동시성 테스트에는 서로 다른 result_id 2개가 필요")

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    previous_id = request["candidate_id"]
    replacement_id = _create_candidate(
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
                .where(AICandidateLifecycleEntity.candidate_id == previous_id)
                .with_for_update()
            )
            lock_acquired.set()
            time.sleep(0.4)
            AICandidateLifecycleService(s_a).supersede(
                previous_candidate_id=previous_id,
                replacement_candidate_id=replacement_id,
                expected_version=1,
                actor="admin:concurrency-test",
                reason="STEP12-2-1A concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _create_thread() -> None:
        assert lock_acquired.wait(timeout=5), "supersede 스레드가 잠금을 획득하지 못함"
        s_b = Session()
        try:
            StrategyDraftService(s_b).create(
                strategy_request_id=request["strategy_request_id"],
                **_draft_kwargs(),
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s_b.close()

    t_supersede = threading.Thread(target=_supersede_thread)
    t_create = threading.Thread(target=_create_thread)
    t_supersede.start()
    t_create.start()
    t_supersede.join(timeout=10)
    t_create.join(timeout=10)

    draft_errors = [e for e in errors if isinstance(e, StrategyDraftError)]
    assert len(draft_errors) == 1
    assert draft_errors[0].code == "CANDIDATE_NOT_ACTIVE_AT_DRAFT"


# ---------------------------------------------------------------------------
# 16~19: USER 읽기 권한(trading:read) — API 레벨
# ---------------------------------------------------------------------------


def _read_only_user(user_id: int) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}",
        roles=["user"],
        permissions=["trading:read"],  # trading:write 없음 — 읽기 권한만
    )


def test_user_list_succeeds_with_read_permission_only(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(
        _REQUESTER_USER_ID
    )
    try:
        resp = client.get("/api/v1/user/strategy-drafts")
        assert resp.status_code == 200
        assert any(
            item["strategy_request_id"] == request["strategy_request_id"]
            for item in resp.json()["items"]
        )
    finally:
        app.dependency_overrides.clear()


def test_user_detail_succeeds_with_read_permission_only(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(
        _REQUESTER_USER_ID
    )
    try:
        resp = client.get(f"/api/v1/user/strategy-drafts/{draft['draft_id']}")
        assert resp.status_code == 200
        assert resp.json()["draft_id"] == draft["draft_id"]
    finally:
        app.dependency_overrides.clear()


def test_user_detail_blocks_other_users_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(_OTHER_USER_ID)
    try:
        resp = client.get(f"/api/v1/user/strategy-drafts/{draft['draft_id']}")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_user_endpoints_reject_missing_read_permission() -> None:
    """trading:read조차 없는(예: 다른 도메인 권한만 있는) 사용자는 403."""
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=_REQUESTER_USER_ID,
        username="norights",
        roles=["user"],
        permissions=["settings:read"],
    )
    try:
        resp = client.get("/api/v1/user/strategy-drafts")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_user_strategy_drafts_require_auth_401() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/user/strategy-drafts")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 20: History 조회 Audit
# ---------------------------------------------------------------------------


def test_admin_history_view_records_audit(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategy-drafts/{draft['draft_id']}/history",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200

    event = session.scalar(
        select(AuditEvent)
        .where(AuditEvent.event_type == "STRATEGY_DRAFT_HISTORY_VIEWED")
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(1)
    )
    assert event is not None
    assert event.detail.get("draft_id") == draft["draft_id"]
    # History 본문/Draft 내용은 기록하지 않고 건수만 남겨야 한다.
    assert "items" not in event.detail
    assert "result_count" in event.detail
