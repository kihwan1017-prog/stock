"""STEP 12-1A — Strategy Request 승인 게이트 보완 통합 테스트.

STEP12-1 완료 보고 검토에서 발견된 결함(승인 시점 Candidate 재검증 부재,
동시성 방어 부재, History FK CASCADE, Alembic head 하드코딩 테스트)에 대한
회귀 테스트다. 실제 PostgreSQL(로컬 dev DB)을 사용하며, 이 파일이 만든
행은 각 테스트의 finally에서 명시적으로 정리한다.

동시성 테스트(#11, #12)는 실제 스레드 + 실제 세션 2개로 Postgres의
SELECT ... FOR UPDATE 행 잠금이 강제하는 순서를 검증한다 — 소스 문자열
검사나 mock으로 대체하지 않는다.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.candidate_lifecycle.service import AICandidateLifecycleService
from stock_platform.ai.strategy_request.entities import (
    StrategyRequestEntity,
    StrategyRequestHistoryEntity,
)
from stock_platform.ai.strategy_request.service import (
    StrategyRequestError,
    StrategyRequestService,
)
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_1A_TEST"


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
                "DELETE FROM ai.strategy_request_history WHERE strategy_request_id "
                "IN (SELECT strategy_request_id FROM ai.strategy_request "
                "WHERE candidate_id IN (SELECT candidate_id FROM ai.candidate_lifecycle "
                "WHERE created_by = :marker))"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.strategy_request WHERE candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle "
                "WHERE created_by = :marker)"
            ),
            {"marker": _MARKER},
        )
        # supersede() 테스트가 남긴 candidate_supersession은 candidate_lifecycle에
        # RESTRICT FK이므로, lifecycle 행 삭제 전에 먼저 지워야 한다.
        s.execute(
            text(
                "DELETE FROM ai.candidate_supersession WHERE previous_candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle "
                "WHERE created_by = :marker) OR replacement_candidate_id IN "
                "(SELECT candidate_id FROM ai.candidate_lifecycle "
                "WHERE created_by = :marker)"
            ),
            {"marker": _MARKER},
        )
        s.execute(
            text(
                "DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker"
            ),
            {"marker": _MARKER},
        )
        s.commit()
        s.close()


def _create_candidate(session, *, result_id: int, lifecycle_status: str) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, created_by, updated_by)
            VALUES (:cid, :status, 'UNKNOWN', :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "status": lifecycle_status, "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_request(session, *, candidate_id: int) -> dict:
    svc = StrategyRequestService(session)
    return svc.create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note="STEP12-1A 테스트 요청",
        actor=f"user:{_REQUESTER_USER_ID}",
    )


# ---------------------------------------------------------------------------
# 1~4: 승인 시점 재검증 — 비활성 Candidate는 승인 차단
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lifecycle_status",
    ["REVOKED", "EXPIRED", "SUPERSEDED", "STALE"],
)
def test_approve_blocked_for_inactive_candidate(session, lifecycle_status) -> None:
    """요청 생성 후 Candidate가 비활성 상태가 되면 승인이 차단된다."""
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)

    # 요청 생성 이후 Candidate 상태가 바뀐 상황을 재현(승인 게이트 재검증 대상).
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = :status "
            "WHERE candidate_id = :cid"
        ),
        {"status": lifecycle_status, "cid": candidate_id},
    )
    session.commit()

    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError) as exc:
        svc.approve(
            created["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note="승인 시도",
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    assert exc.value.code == "CANDIDATE_NOT_ACTIVE_AT_REVIEW"


def test_approve_blocked_when_candidate_missing(session) -> None:
    """approve()의 'candidate 없음' 방어 분기를 검증한다.

    strategy_request.candidate_id는 ai.candidate_lifecycle.candidate_id에
    대한 ON DELETE RESTRICT FK이므로, 실제 DB에서는 참조 중인 Candidate 행을
    삭제하는 것 자체가 불가능하다(시도하면 ForeignKeyViolation — FK
    무결성이 정상 동작한다는 방증). 즉 이 분기는 정상 운영에서는 도달
    불가능하지만, "Candidate가 없어도 승인 불가 처리한다"는 요구사항대로
    방어 코드는 존재해야 한다. DB로 재현 불가능하므로, candidate 조회
    1회만 모킹해 방어 코드 경로 자체를 검증한다.
    """
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)

    svc = StrategyRequestService(session)
    real_scalar = session.scalar
    call_count = {"n": 0}

    def _fake_scalar(stmt, *args, **kwargs):
        call_count["n"] += 1
        # approve() 내부 호출 순서: 1) strategy_request 조회(_require)
        # 2) candidate_lifecycle 조회. 두 번째 호출만 None으로 만든다.
        if call_count["n"] == 2:
            return None
        return real_scalar(stmt, *args, **kwargs)

    with patch.object(session, "scalar", side_effect=_fake_scalar):
        with pytest.raises(StrategyRequestError) as exc:
            svc.approve(
                created["strategy_request_id"],
                reviewer_user_id=_REVIEWER_USER_ID,
                review_note="승인 시도",
                actor=f"admin:{_REVIEWER_USER_ID}",
            )
    assert exc.value.code == "CANDIDATE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 5~6: ACTIVE 상태 Candidate는 승인 성공 + 승인 시점 스냅샷 기록
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lifecycle_status", ["PROMOTED", "ACTIVE_REVIEW"])
def test_approve_succeeds_for_active_candidate(session, lifecycle_status) -> None:
    candidate_id = _create_candidate(
        session,
        result_id=session.info["result_ids"][0],
        lifecycle_status=lifecycle_status,
    )
    created = _create_request(session, candidate_id=candidate_id)

    svc = StrategyRequestService(session)
    approved = svc.approve(
        created["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="근거 확인 완료",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewer_user_id"] == _REVIEWER_USER_ID
    # 승인 시점 스냅샷(STEP12-1A) — 요청 시점 스냅샷과 별도로 보존.
    assert approved["candidate_status_at_review"] == lifecycle_status


# ---------------------------------------------------------------------------
# 7~9: 승인 실패 시 부분 commit 금지
# ---------------------------------------------------------------------------


def test_approve_failure_leaves_request_pending_review(session) -> None:
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": candidate_id},
    )
    session.commit()

    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError):
        svc.approve(
            created["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note="승인 시도",
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    session.rollback()

    reloaded = svc.get(created["strategy_request_id"])
    assert reloaded["status"] == "PENDING_REVIEW"


def test_approve_failure_leaves_reviewer_and_reviewed_at_unset(session) -> None:
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'EXPIRED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": candidate_id},
    )
    session.commit()

    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError):
        svc.approve(
            created["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note="승인 시도",
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    # 서비스 내부에서 커밋된 적이 없어야 하므로, 세션을 정리(rollback)한 뒤
    # 새로 조회해도 reviewer_user_id/reviewed_at은 세팅되지 않아야 한다.
    session.rollback()

    reloaded = svc.get(created["strategy_request_id"])
    assert reloaded["reviewer_user_id"] is None
    assert reloaded["reviewed_at"] is None
    assert reloaded["candidate_status_at_review"] is None


def test_approve_failure_does_not_create_approved_history(session) -> None:
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'SUPERSEDED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": candidate_id},
    )
    session.commit()

    svc = StrategyRequestService(session)
    with pytest.raises(StrategyRequestError):
        svc.approve(
            created["strategy_request_id"],
            reviewer_user_id=_REVIEWER_USER_ID,
            review_note="승인 시도",
            actor=f"admin:{_REVIEWER_USER_ID}",
        )
    session.rollback()

    history = svc.get_history(created["strategy_request_id"])
    actions = [h["action"] for h in history["items"]]
    assert "APPROVE" not in actions
    assert actions == ["CREATE"]


# ---------------------------------------------------------------------------
# 10: 승인 실패 Audit 기록 (실제 HTTP API 경로)
# ---------------------------------------------------------------------------


def test_approve_failure_records_audit_event(session) -> None:
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)
    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": candidate_id},
    )
    session.commit()

    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategy-requests/{created['strategy_request_id']}/approve",
        json={"review_note": "승인 시도"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CANDIDATE_NOT_ACTIVE_AT_REVIEW"

    event = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.event_type == "STRATEGY_REQUEST_APPROVE_FAILED",
        )
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(1)
    )
    assert event is not None
    assert event.detail.get("strategy_request_id") == created["strategy_request_id"]
    assert event.detail.get("code") == "CANDIDATE_NOT_ACTIVE_AT_REVIEW"


# ---------------------------------------------------------------------------
# 11~12: 동시성 — 승인과 revoke/supersede 경합 (실 스레드 + 실 세션 2개)
# ---------------------------------------------------------------------------


def test_approve_vs_expire_concurrency_blocks_approval(session) -> None:
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)

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
            time.sleep(0.4)  # revoke 트랜잭션이 오래 걸리는 상황을 재현
            AICandidateLifecycleService(s_a).expire(
                candidate_id=candidate_id,
                expected_version=1,
                actor="admin:concurrency-test",
                reason="STEP12-1A concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5), "expire 스레드가 잠금을 획득하지 못함"
        s_b = Session()
        try:
            StrategyRequestService(s_b).approve(
                created["strategy_request_id"],
                reviewer_user_id=_REVIEWER_USER_ID,
                review_note="race approve",
                actor=f"admin:{_REVIEWER_USER_ID}",
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

    strategy_errors = [e for e in errors if isinstance(e, StrategyRequestError)]
    assert len(strategy_errors) == 1
    assert strategy_errors[0].code == "CANDIDATE_NOT_ACTIVE_AT_REVIEW"

    svc = StrategyRequestService(session)
    reloaded = svc.get(created["strategy_request_id"])
    assert reloaded["status"] == "PENDING_REVIEW"
    assert reloaded["reviewer_user_id"] is None


def test_approve_vs_supersede_concurrency_blocks_approval(session) -> None:
    if len(session.info["result_ids"]) < 2:
        pytest.skip("supersede 동시성 테스트에는 서로 다른 result_id 2개가 필요")

    previous_id = _create_candidate(
        session,
        result_id=session.info["result_ids"][0],
        lifecycle_status="PROMOTED",
    )
    replacement_id = _create_candidate(
        session,
        result_id=session.info["result_ids"][1],
        lifecycle_status="PROMOTED",
    )
    created = _create_request(session, candidate_id=previous_id)

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
                reason="STEP12-1A concurrency test",
            )
            s_a.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            s_a.rollback()
        finally:
            s_a.close()

    def _approve_thread() -> None:
        assert lock_acquired.wait(timeout=5), "supersede 스레드가 잠금을 획득하지 못함"
        s_b = Session()
        try:
            StrategyRequestService(s_b).approve(
                created["strategy_request_id"],
                reviewer_user_id=_REVIEWER_USER_ID,
                review_note="race approve",
                actor=f"admin:{_REVIEWER_USER_ID}",
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

    strategy_errors = [e for e in errors if isinstance(e, StrategyRequestError)]
    assert len(strategy_errors) == 1
    assert strategy_errors[0].code == "CANDIDATE_NOT_ACTIVE_AT_REVIEW"

    svc = StrategyRequestService(session)
    reloaded = svc.get(created["strategy_request_id"])
    assert reloaded["status"] == "PENDING_REVIEW"
    assert reloaded["reviewer_user_id"] is None


# ---------------------------------------------------------------------------
# 13: History가 있는 Strategy Request는 Hard Delete 차단(ON DELETE RESTRICT)
# ---------------------------------------------------------------------------


def test_hard_delete_blocked_when_history_exists(session) -> None:
    candidate_id = _create_candidate(
        session, result_id=session.info["result_ids"][0], lifecycle_status="PROMOTED"
    )
    created = _create_request(session, candidate_id=candidate_id)

    history_count = session.scalar(
        select(StrategyRequestHistoryEntity)
        .where(
            StrategyRequestHistoryEntity.strategy_request_id
            == created["strategy_request_id"]
        )
        .limit(1)
    )
    assert history_count is not None  # create()가 CREATE history를 남겼는지 확인

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "DELETE FROM ai.strategy_request WHERE strategy_request_id = :id"
            ),
            {"id": created["strategy_request_id"]},
        )
        session.commit()
    session.rollback()

    # 정상 상태 전이/이력 조회에는 영향이 없어야 한다.
    svc = StrategyRequestService(session)
    still_there = svc.get(created["strategy_request_id"])
    assert still_there["status"] == "PENDING_REVIEW"
    history = svc.get_history(created["strategy_request_id"])
    assert len(history["items"]) == 1


# ---------------------------------------------------------------------------
# 14: 신규 Migration upgrade/downgrade 라운드트립
# ---------------------------------------------------------------------------


def test_new_migration_upgrade_downgrade_roundtrip() -> None:
    from alembic import command
    from tests.migration_helpers import alembic_config

    config = alembic_config()

    def _columns() -> set[str]:
        Session = get_session_factory()
        s = Session()
        try:
            rows = s.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='ai' AND table_name='strategy_request' "
                    "AND column_name IN "
                    "('candidate_status_at_review', 'candidate_fingerprint_at_review')"
                )
            ).fetchall()
            return {r[0] for r in rows}
        finally:
            s.close()

    def _fk_delete_rule() -> str | None:
        Session = get_session_factory()
        s = Session()
        try:
            return s.execute(
                text(
                    "SELECT confdeltype FROM pg_constraint "
                    "WHERE conname = 'fk_ai_strategy_request_hist_request'"
                )
            ).scalar()
        finally:
            s.close()

    assert _columns() == {
        "candidate_status_at_review",
        "candidate_fingerprint_at_review",
    }
    assert _fk_delete_rule() == "r"  # RESTRICT

    try:
        # 상대 경로("-1") 대신 이 Migration의 down_revision을 명시적으로
        # 지정한다 — 이후 STEP(예: STEP12-2-1)이 위에 새 Migration을 쌓으면
        # "-1"은 그 새 Migration을 내리게 되어 이 테스트가 엉뚱한 리비전을
        # 검증하게 된다(STEP12-2-1 도입 시 실제로 발견된 문제).
        command.downgrade(config, "bfc6ab7d28b2")
        assert _columns() == set()
        assert _fk_delete_rule() == "c"  # CASCADE (원복 확인)
    finally:
        command.upgrade(config, "head")

    assert _columns() == {
        "candidate_status_at_review",
        "candidate_fingerprint_at_review",
    }
    assert _fk_delete_rule() == "r"


# ---------------------------------------------------------------------------
# 15: Alembic head 하드코딩 테스트 재발 방지(회귀 가드)
# ---------------------------------------------------------------------------


def test_no_hardcoded_alembic_head_comparisons_remain() -> None:
    """`alembic_current_head() == "<literal>"` 패턴 재발 방지 회귀 가드.

    STEP12-1A에서 13개 파일의 하드코딩된 head 비교를
    assert_revision_is_ancestor_of_head()로 교체했다. 향후 다시 하드코딩된
    비교가 추가되면 이 테스트가 실패해 즉시 드러난다.
    """

    forbidden = re.compile(r"alembic_current_head\(\)\s*==\s*[\"']")
    tests_dir = Path(__file__).resolve().parent
    offenders = []
    for path in tests_dir.glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue
        text_content = path.read_text(encoding="utf-8")
        if forbidden.search(text_content):
            offenders.append(str(path))
    assert offenders == [], f"하드코딩된 alembic head 비교가 남아있음: {offenders}"
