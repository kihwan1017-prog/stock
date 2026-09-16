"""STEP 12-2-1 — Strategy Draft Domain 통합 테스트.

실제 PostgreSQL(로컬 dev DB)을 사용한다. 이 파일이 만든 행은 각 테스트의
finally에서 명시적으로 정리한다. AI 호출/Prompt 생성/LLM 실행은 다루지
않는다(도메인 자체가 저장/버전관리 기반 구조만 구현).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from stock_platform.ai.strategy_draft.entities import (
    StrategyDraftEntity,
    StrategyDraftHistoryEntity,
)
from stock_platform.ai.strategy_draft.service import (
    StrategyDraftError,
    StrategyDraftService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_OTHER_USER_ID = 999_999
_MARKER = "STEP12_2_1_TEST"


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
            text("DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker"),
            {"marker": _MARKER},
        )
        s.commit()
        s.close()


_FINGERPRINT = "a1" * 32  # 64자 — STEP12-2-1A 재검증(current == approval)을 통과시키기 위한 고정값


def _create_approved_request(
    session, *, result_id: int, fingerprint: str | None = _FINGERPRINT
) -> dict:
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
        "title": "테스트 전략 초안",
        "timeframe": "1D",
        "market_type": "KR_STOCK",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Draft 생성 / Version 생성
# ---------------------------------------------------------------------------


def test_create_first_draft_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)

    draft = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    assert draft["version"] == 1
    assert draft["revision"] == 1
    assert draft["label"] == "v1"
    assert draft["status"] == "DRAFT"
    assert draft["candidate_fingerprint"] == request["candidate_fingerprint_at_review"]

    history = svc.get_history(draft["draft_id"])
    assert [h["action"] for h in history["items"]] == ["CREATE"]


def test_create_blocks_non_approved_request(session) -> None:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, created_by, updated_by)
            VALUES (:cid, 'PROMOTED', 'UNKNOWN', :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": session.info["result_ids"][0], "marker": _MARKER},
    ).scalar_one()
    session.commit()
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )

    svc = StrategyDraftService(session)
    with pytest.raises(StrategyDraftError) as exc:
        svc.create(strategy_request_id=req["strategy_request_id"], **_draft_kwargs())
    assert exc.value.code == "STRATEGY_REQUEST_NOT_APPROVED"


def test_create_blocks_nonexistent_request(session) -> None:
    svc = StrategyDraftService(session)
    with pytest.raises(StrategyDraftError) as exc:
        svc.create(strategy_request_id=999_999_999, **_draft_kwargs())
    assert exc.value.code == "STRATEGY_REQUEST_NOT_FOUND"


def test_create_new_version_supersedes_previous(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)

    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    v2 = svc.create(
        strategy_request_id=request["strategy_request_id"],
        **_draft_kwargs(title="v2 title"),
    )

    assert v2["version"] == 2
    assert v2["revision"] == 1
    assert v2["label"] == "v2"

    v1_reloaded = svc.get(v1["draft_id"])
    assert v1_reloaded["status"] == "SUPERSEDED"

    v1_history = svc.get_history(v1["draft_id"])
    assert [h["action"] for h in v1_history["items"]] == ["SUPERSEDED", "CREATE"]

    v2_history = svc.get_history(v2["draft_id"])
    assert v2_history["items"][0]["action"] == "CREATE_VERSION"
    assert v2_history["items"][0]["previous_version"] == 1
    assert v2_history["items"][0]["new_version"] == 2


# ---------------------------------------------------------------------------
# Revision 생성
# ---------------------------------------------------------------------------


def test_create_revision_regenerates_previous(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    v1r2 = svc.create_revision(
        v1["draft_id"], actor="admin:7", reason="revise", summary="v1r2 summary"
    )
    assert v1r2["version"] == 1
    assert v1r2["revision"] == 2
    assert v1r2["label"] == "v1-r2"
    assert v1r2["title"] == v1["title"]  # 미변경 필드는 상속
    assert v1r2["summary"] == "v1r2 summary"  # override 반영

    v1_reloaded = svc.get(v1["draft_id"])
    assert v1_reloaded["status"] == "REGENERATED"

    v1r3 = svc.create_revision(v1r2["draft_id"], actor="admin:7", reason="revise again")
    assert v1r3["revision"] == 3
    assert v1r3["label"] == "v1-r3"


def test_create_revision_blocks_non_draft_source(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    svc.create_revision(v1["draft_id"], actor="admin:7")  # v1 -> REGENERATED

    with pytest.raises(StrategyDraftError) as exc:
        svc.create_revision(v1["draft_id"], actor="admin:7")
    assert exc.value.code == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# 수정 (Update)
# ---------------------------------------------------------------------------


def test_update_edits_draft_only(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    updated = svc.update(
        v1["draft_id"], actor="admin:7", reason="typo fix", title="수정된 제목"
    )
    assert updated["title"] == "수정된 제목"
    assert updated["version"] == 1
    assert updated["revision"] == 1  # 수정은 revision을 올리지 않는다

    history = svc.get_history(v1["draft_id"])
    assert [h["action"] for h in history["items"]] == ["UPDATE", "CREATE"]


def test_update_blocks_non_draft_status(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    svc.archive(v1["draft_id"], actor="admin:7")

    with pytest.raises(StrategyDraftError) as exc:
        svc.update(v1["draft_id"], actor="admin:7", title="변경 시도")
    assert exc.value.code == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def test_archive_transitions_and_blocks_double_archive(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    archived = svc.archive(v1["draft_id"], actor="admin:7", reason="종료")
    assert archived["status"] == "ARCHIVED"

    with pytest.raises(StrategyDraftError) as exc:
        svc.archive(v1["draft_id"], actor="admin:7")
    assert exc.value.code == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# History / Version 조회
# ---------------------------------------------------------------------------


def test_version_query_returns_all_revisions_in_order(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    v1r2 = svc.create_revision(v1["draft_id"], actor="admin:7")
    svc.create_revision(v1r2["draft_id"], actor="admin:7")

    version_result = svc.get_version(request["strategy_request_id"], 1)
    labels = [item["label"] for item in version_result["items"]]
    assert labels == ["v1", "v1-r2", "v1-r3"]


def test_version_query_not_found(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    with pytest.raises(StrategyDraftError) as exc:
        svc.get_version(request["strategy_request_id"], 99)
    assert exc.value.code == "NOT_FOUND"


def test_not_found_errors(session) -> None:
    svc = StrategyDraftService(session)
    with pytest.raises(StrategyDraftError) as exc:
        svc.get(999_999_999)
    assert exc.value.code == "NOT_FOUND"

    with pytest.raises(StrategyDraftError) as exc:
        svc.get_history(999_999_999)
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# IDOR / 소유권
# ---------------------------------------------------------------------------


def test_get_owned_ownership_and_idor(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    with pytest.raises(StrategyDraftError) as exc:
        svc.get_owned(v1["draft_id"], user_id=_OTHER_USER_ID)
    assert exc.value.code == "OWNERSHIP_DENIED"

    ok = svc.get_owned(v1["draft_id"], user_id=_REQUESTER_USER_ID)
    assert ok["draft_id"] == v1["draft_id"]


def test_list_user_filter_idor(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    own = svc.list(user_id=_REQUESTER_USER_ID)
    assert any(item["draft_id"] == v1["draft_id"] for item in own["items"])

    other = svc.list(user_id=_OTHER_USER_ID)
    assert all(item["draft_id"] != v1["draft_id"] for item in other["items"])


# ---------------------------------------------------------------------------
# DB 무결성 (부분 유니크 인덱스 / FK RESTRICT)
# ---------------------------------------------------------------------------


def test_db_partial_unique_index_blocks_concurrent_active_draft(session) -> None:
    """서비스 사전검사를 우회한 raw INSERT도 부분 유니크 인덱스가 최종 차단."""
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    session.execute(
        text(
            """
            INSERT INTO ai.strategy_draft
            (strategy_request_id, version, revision, status, title, timeframe, market_type, created_by)
            VALUES (:rid, 1, 1, 'DRAFT', 't1', '1D', 'KR_STOCK', 'admin:7')
            """
        ),
        {"rid": request["strategy_request_id"]},
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO ai.strategy_draft
                (strategy_request_id, version, revision, status, title, timeframe, market_type, created_by)
                VALUES (:rid, 2, 1, 'DRAFT', 't2', '1D', 'KR_STOCK', 'admin:7')
                """
            ),
            {"rid": request["strategy_request_id"]},
        )
        session.commit()
    session.rollback()


def test_fk_restrict_blocks_hard_delete_of_request_with_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "DELETE FROM ai.strategy_request WHERE strategy_request_id = :id"
            ),
            {"id": request["strategy_request_id"]},
        )
        session.commit()
    session.rollback()


def test_history_fk_restrict_blocks_hard_delete_of_draft(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    v1 = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs()
    )
    history_row = session.scalar(
        select(StrategyDraftHistoryEntity).where(
            StrategyDraftHistoryEntity.draft_id == v1["draft_id"]
        )
    )
    assert history_row is not None

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM ai.strategy_draft WHERE draft_id = :id"),
            {"id": v1["draft_id"]},
        )
        session.commit()
    session.rollback()

    still_there = session.get(StrategyDraftEntity, v1["draft_id"])
    assert still_there is not None


# ---------------------------------------------------------------------------
# API 레벨 — 인증/권한, RBAC
# ---------------------------------------------------------------------------


def test_user_strategy_drafts_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/user/strategy-drafts")
    assert resp.status_code == 401


def test_admin_strategy_drafts_require_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/admin/strategy-drafts")
    assert resp.status_code == 401


def test_openapi_lists_strategy_draft_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/admin/strategy-drafts" in paths
    assert "post" in paths["/api/v1/admin/strategy-drafts"]
    assert "get" in paths["/api/v1/admin/strategy-drafts"]
    assert "patch" in paths["/api/v1/admin/strategy-drafts/{draft_id}"]
    assert "/api/v1/admin/strategy-drafts/{draft_id}/archive" in paths
    assert "/api/v1/admin/strategy-drafts/{draft_id}/history" in paths
    assert "/api/v1/user/strategy-drafts" in paths
    assert "get" in paths["/api/v1/user/strategy-drafts"]
    # USER 쪽은 조회만 허용 — 생성/수정/Archive 경로 없음
    assert "post" not in paths["/api/v1/user/strategy-drafts"]


# ---------------------------------------------------------------------------
# Migration upgrade/downgrade 라운드트립
# ---------------------------------------------------------------------------


def test_new_migration_upgrade_downgrade_roundtrip() -> None:
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
                    "('strategy_draft', 'strategy_draft_history')"
                )
            ).scalar()
            return int(row or 0) == 2
        finally:
            s.close()

    assert _tables_exist()

    try:
        # 상대 경로("-1") 대신 이 Migration의 down_revision을 명시적으로
        # 지정한다 — 향후 이 위에 새 Migration이 쌓이면 "-1"은 그 새
        # Migration을 내리게 되어 이 테스트가 엉뚱한 리비전을 검증하게 된다
        # (STEP12-1A의 동일한 round-trip 테스트에서 실제로 발견된 문제).
        command.downgrade(config, "27d47b2bb048")
        assert not _tables_exist()
    finally:
        command.upgrade(config, "head")

    assert _tables_exist()
