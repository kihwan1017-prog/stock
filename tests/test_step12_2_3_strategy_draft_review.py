"""STEP 12-2-3 — AI Strategy Draft 검토·비교·재생성 관리 통합 테스트.

실제 PostgreSQL(로컬 dev DB) + "mock" Provider(결정적)를 사용한다.
실 Ollama 검증은 `test_step12_2_3_ollama_live_smoke`(live_ai marker)에서
별도로 다룬다 — 이 샌드박스에 실제 실행 중인 Ollama(qwen3.5:4b)가 있어
연동 자체는 검증했으나, 소형 모델의 출력 형식 불안정성으로 Draft 생성
성공까지는 이르지 못했다(완료 보고 §16 참고). 그 테스트는 "연결·파싱·
검증·기록이 정상 동작하는지"를 확인하는 것을 목표로 하며, 모델이 완벽한
JSON을 내지 못해도 실패를 우아하게 기록하면 통과로 본다.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from stock_platform.ai.strategy_draft.comparison import compare_drafts
from stock_platform.ai.strategy_draft.entities import StrategyDraftEntity
from stock_platform.ai.strategy_draft.service import (
    StrategyDraftError,
    StrategyDraftService,
)
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationError,
    StrategyDraftGenerationService,
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
_MARKER = "STEP12_2_3_TEST"
_FINGERPRINT = "f6" * 32


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
            text("DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker"),
            {"marker": _MARKER},
        )
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


def _generate(session, strategy_request_id: int) -> dict:
    return asyncio.run(
        StrategyDraftGenerationService(session).generate_strategy_draft(
            strategy_request_id=strategy_request_id,
            actor="admin:7",
            provider_id="mock",
        )
    )


def _draft_kwargs(**overrides) -> dict:
    base = {
        "actor": "admin:7",
        "title": "수동 초안",
        "timeframe": "1D",
        "market_type": "KR_STOCK",
    }
    base.update(overrides)
    return base


def _read_only_user(user_id: int) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id, username=f"user{user_id}", roles=["user"],
        permissions=["trading:read"],
    )


# ---------------------------------------------------------------------------
# 1: STARTED Audit
# ---------------------------------------------------------------------------


def test_started_audit_recorded_between_requested_and_result(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    floor = _audit_floor(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategy-draft-generations",
        json={"strategy_request_id": request["strategy_request_id"], "provider_id": "mock"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    run_id = resp.json()["run"]["generation_run_id"]

    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("STRATEGY_DRAFT_GENERATION%"))
        .order_by(AuditEvent.audit_event_id.asc())
    ).all()
    # 이번 호출로 REQUESTED -> STARTED -> 결과(SUCCEEDED/FAILED) 3개가
    # 이 순서로 남았는지 최근 3개 이벤트로 확인한다.
    recent = [e[0] for e in events[-3:]]
    assert recent[0] == "STRATEGY_DRAFT_GENERATION_REQUESTED"
    assert recent[1] == "STRATEGY_DRAFT_GENERATION_STARTED"
    assert recent[2].startswith("STRATEGY_DRAFT_GENERATION_") and (
        recent[2].endswith("SUCCEEDED")
        or recent[2].endswith("FAILED")
        or recent[2].endswith("INVALIDATED")
    )
    # STEP12-2-3A: API 경로에서는 STARTED가 정확히 1건만 기록되어야 한다
    # (start_generation() 내부 기록 + API 레이어 기록이 이중으로 남지 않음).
    assert _started_audit_count(session, run_id, since=floor) == 1


def _audit_floor(session) -> int:
    """이 시점 이전의 Audit은 무시하기 위한 기준점.

    이 테스트가 쓰는 공유 dev DB는 이번 STEP 조사 과정에서 스키마를
    재생성한 이력이 있어 시퀀스가 되감긴 적이 있다 — 그 결과 옛날에 삭제된
    Run과 같은 generation_run_id를 새 Run이 재사용하면서, Audit
    이벤트(불변 기록이라 정리 대상이 아님)만 과거 것이 남아 있는 경우가
    실측으로 확인됐다. run_id 필터만으로는 이런 오래된 고아 Audit과
    혼동될 수 있어, audit_event_id 하한을 함께 걸어 이번 테스트 동작 이후
    생성된 것만 센다."""
    return session.execute(select(func.coalesce(func.max(AuditEvent.audit_event_id), 0))).scalar_one()


def _started_audit_count(session, run_id: int, *, since: int = 0) -> int:
    return session.execute(
        select(func.count()).where(
            AuditEvent.event_type == "STRATEGY_DRAFT_GENERATION_STARTED",
            AuditEvent.run_id == str(run_id),
            AuditEvent.audit_event_id > since,
        )
    ).scalar_one()


def test_started_audit_recorded_on_direct_service_call_path(session) -> None:
    """STEP12-2-3A §5 — API를 거치지 않고 서비스를 직접 호출해도(테스트
    헬퍼 `_generate()`가 쓰는 `generate_strategy_draft()` 경로) STARTED가
    정확히 1건 기록되어야 한다. 과거(STEP12-2-3)에는 STARTED Audit이
    API 레이어에만 있어 이 경로에서는 전혀 기록되지 않는 결함이 있었다."""
    floor = _audit_floor(session)
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    run_id = result["run"]["generation_run_id"]

    assert _started_audit_count(session, run_id, since=floor) == 1


def test_started_audit_not_duplicated_on_redundant_start(session) -> None:
    """STEP12-2-3A §5 — 이미 RUNNING인 Run에 start_generation()을 다시
    호출하면 INVALID_STATE_TRANSITION으로 거부되고, STARTED Audit이
    추가로 남지 않아야 한다(정확히 1건 유지)."""
    floor = _audit_floor(session)
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    created = StrategyDraftGenerationService(session).create_generation_run(
        strategy_request_id=request["strategy_request_id"],
        actor="admin:7",
        provider_id="mock",
    )
    run_id = created["generation_run_id"]
    svc = StrategyDraftGenerationService(session)
    svc.start_generation(run_id, actor="admin:7")
    assert _started_audit_count(session, run_id, since=floor) == 1

    with pytest.raises(StrategyDraftGenerationError) as exc_info:
        svc.start_generation(run_id, actor="admin:7")
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    assert _started_audit_count(session, run_id, since=floor) == 1


def test_no_started_audit_on_failed_transition(session) -> None:
    """STEP12-2-3A §5 — 이미 종결(SUCCEEDED/FAILED 등)된 Run에
    start_generation()을 호출해 실패하면 STARTED Audit이 전혀 남지
    않아야 한다(실패한 전이는 감사 기록을 생성하지 않는다)."""
    floor = _audit_floor(session)
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    run_id = result["run"]["generation_run_id"]
    # _generate()가 이미 이 Run을 종결 상태로 만들었다(정상 시작 1건 포함).
    assert _started_audit_count(session, run_id, since=floor) == 1

    svc = StrategyDraftGenerationService(session)
    with pytest.raises(StrategyDraftGenerationError) as exc_info:
        svc.start_generation(run_id, actor="admin:7")
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    # 실패한 전이 시도 이후에도 STARTED는 여전히 최초 1건뿐이다.
    assert _started_audit_count(session, run_id, since=floor) == 1


# ---------------------------------------------------------------------------
# 2~3: Run 상세 / Attempt 목록
# ---------------------------------------------------------------------------


def test_generation_run_detail_fields(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    run_id = result["run"]["generation_run_id"]

    detail = StrategyDraftGenerationService(session).get_generation_run(run_id)
    for field in (
        "generation_run_id", "strategy_request_id", "candidate_id", "status",
        "provider", "model", "retry_number", "started_at", "completed_at",
        "candidate_lifecycle_status_at_request", "candidate_fingerprint_at_request",
        "draft_id", "error_code",
    ):
        assert field in detail
    assert "system_template" not in str(detail)
    assert "api_key" not in str(detail).lower()


def test_list_attempts_endpoint(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    run_id = result["run"]["generation_run_id"]

    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategy-draft-generations/{run_id}/attempts",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert items[0]["attempt_no"] == 1


# ---------------------------------------------------------------------------
# 4: Timeline
# ---------------------------------------------------------------------------


def test_draft_timeline_merges_and_sorts(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    _generate(session, request["strategy_request_id"])

    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategy-requests/{request['strategy_request_id']}/draft-timeline",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 3  # CREATE(draft history) + REQUESTED/STARTED/결과(Run)
    timestamps = [it["occurred_at"] for it in items]
    assert timestamps == sorted(timestamps)
    types = {it["type"] for it in items}
    assert "GENERATION_REQUESTED" in types
    assert "GENERATION_STARTED" in types


def test_draft_timeline_requires_existing_request() -> None:
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        "/api/v1/admin/strategy-requests/999999999/draft-timeline",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5~8: 비교(Version/Revision/added-removed-changed-unchanged/IDOR)
# ---------------------------------------------------------------------------


def test_compare_version_vs_version(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(strategy_request_id=request["strategy_request_id"], **_draft_kwargs(title="v1"))
    v2 = svc.create(
        strategy_request_id=request["strategy_request_id"], **_draft_kwargs(title="v2 다른 제목")
    )

    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategy-drafts/{v1['draft_id']}/comparison",
        params={"compare_draft_id": v2["draft_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"]["title"]["status"] == "changed"
    assert body["summary"]["changed"] >= 1


def test_compare_revision_vs_revision(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    v1 = svc.create(strategy_request_id=request["strategy_request_id"], **_draft_kwargs())
    v1r2 = svc.create_revision(v1["draft_id"], actor="admin:7", summary="변경된 요약")

    result = compare_drafts(svc.get(v1["draft_id"]), svc.get(v1r2["draft_id"]))
    assert result["fields"]["summary"]["status"] in {"changed", "added"}
    assert result["fields"]["title"]["status"] == "unchanged"


def test_compare_reorders_arrays_as_unchanged() -> None:
    a = {"draft_id": 1, "entry_rule": '[{"a":1},{"b":2}]'}
    b = {"draft_id": 2, "entry_rule": '[{"b":2},{"a":1}]'}
    result = compare_drafts(a, b)
    assert result["fields"]["entry_rule"]["status"] == "unchanged"


def test_compare_added_removed_changed_unchanged_summary() -> None:
    a = {"draft_id": 1, "title": "same", "summary": "old", "timeframe": None}
    b = {"draft_id": 2, "title": "same", "summary": "new", "timeframe": "1D"}
    result = compare_drafts(a, b)
    assert result["fields"]["title"]["status"] == "unchanged"
    assert result["fields"]["summary"]["status"] == "changed"
    assert result["fields"]["timeframe"]["status"] == "added"
    assert result["summary"]["unchanged"] >= 1
    assert result["summary"]["changed"] >= 1
    assert result["summary"]["added"] >= 1


def test_compare_blocks_cross_request_drafts(session) -> None:
    if len(session.info["result_ids"]) < 2:
        pytest.skip("서로 다른 result_id 2개 필요")
    request_a = _create_approved_request(session, result_id=session.info["result_ids"][0])
    request_b = _create_approved_request(session, result_id=session.info["result_ids"][1])
    svc = StrategyDraftService(session)
    draft_a = svc.create(strategy_request_id=request_a["strategy_request_id"], **_draft_kwargs())
    draft_b = svc.create(strategy_request_id=request_b["strategy_request_id"], **_draft_kwargs())

    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategy-drafts/{draft_a['draft_id']}/comparison",
        params={"compare_draft_id": draft_b["draft_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CROSS_REQUEST_COMPARISON_BLOCKED"


# ---------------------------------------------------------------------------
# 8.5: Draft <-> Run <-> Attempt 정확한 연결(STEP12-2-3A §6)
# ---------------------------------------------------------------------------


def test_get_latest_attempt_for_draft_uses_the_run_that_produced_it(session) -> None:
    """같은 Strategy Request에 대해 성공한 Run을 두 번(버전 2개) 만들어도,
    각 Draft의 Attempt 조회는 "그 Draft를 만든 Run"으로만 연결되어야 한다
    (요청 기준 최신 Run이나 전역 최신 Attempt가 아님)."""
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    gen_svc = StrategyDraftGenerationService(session)

    result_1 = _generate(session, request["strategy_request_id"])
    run_1_id = result_1["run"]["generation_run_id"]
    draft_1_id = result_1["run"]["draft_id"]
    assert draft_1_id is not None

    result_2 = _generate(session, request["strategy_request_id"])
    run_2_id = result_2["run"]["generation_run_id"]
    draft_2_id = result_2["run"]["draft_id"]
    assert draft_2_id is not None
    assert run_1_id != run_2_id
    assert draft_1_id != draft_2_id

    attempt_1 = gen_svc.get_latest_attempt_for_draft(draft_1_id)
    attempt_2 = gen_svc.get_latest_attempt_for_draft(draft_2_id)
    assert attempt_1 is not None and attempt_2 is not None
    assert attempt_1["generation_run_id"] == run_1_id
    assert attempt_2["generation_run_id"] == run_2_id
    # 두 번째(더 최신) Run이 생겼다고 해서 첫 Draft의 연결이 옮겨가지 않는다.
    assert attempt_1["generation_run_id"] != run_2_id


def test_get_latest_attempt_for_draft_ignores_failed_attempts(session) -> None:
    """실패한 Run(Draft 미생성)을 만든 뒤 재시도로 성공시켜도, 성공한
    Draft의 Attempt 조회는 실패 Attempt가 아니라 그 Draft를 만든 Run의
    SUCCEEDED Attempt를 반환해야 한다(실패 Run의 retry_of_run_id로
    연결돼 있어도 실패 Attempt는 절대 반환되지 않는다)."""
    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager, reset_ai_manager
    from stock_platform.ai.providers.mock_provider import MockAIProvider
    from stock_platform.ai.providers.registry import AIProviderRegistry

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    gen_svc = StrategyDraftGenerationService(session)
    created = gen_svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"],
        actor="admin:7",
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
        # StrategyDraftGenerationService.__init__은 ai_manager를 즉시
        # get_ai_manager()로 캡처하므로, 깨진 매니저를 실제로 쓰게 하려면
        # reset_ai_manager() 이후에 새로 생성해야 한다(위에서 만든 gen_svc는
        # 이미 기본 매니저를 캡처했으므로 여기서 재사용하면 안 된다).
        failing_svc = StrategyDraftGenerationService(session)
        failed_result = asyncio.run(
            failing_svc.generate(created["generation_run_id"], actor="admin:7")
        )
    finally:
        reset_ai_manager()

    assert failed_result["run"]["status"] == "FAILED"
    assert failed_result["run"]["draft_id"] is None

    retried = gen_svc.retry_generation(created["generation_run_id"], actor="admin:7")
    ok_result = asyncio.run(gen_svc.generate(retried["generation_run_id"], actor="admin:7"))
    assert ok_result["run"]["status"] == "SUCCEEDED"
    draft_id = ok_result["run"]["draft_id"]
    assert draft_id is not None

    attempt = gen_svc.get_latest_attempt_for_draft(draft_id)
    assert attempt is not None
    assert attempt["status"] == "SUCCEEDED"
    assert attempt["generation_run_id"] == retried["generation_run_id"]
    assert attempt["generation_run_id"] != created["generation_run_id"]


# ---------------------------------------------------------------------------
# 9~10: 수동 Revision 생성 / AI 원본 Draft 보존(PATCH 정책)
# ---------------------------------------------------------------------------


def test_manual_draft_can_still_be_patched(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    svc = StrategyDraftService(session)
    draft = svc.create(strategy_request_id=request["strategy_request_id"], **_draft_kwargs())
    updated = svc.update(draft["draft_id"], actor="admin:7", title="수정됨")
    assert updated["title"] == "수정됨"


def test_ai_generated_draft_blocks_direct_patch_requires_revision(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    assert result["run"]["status"] == "SUCCEEDED"
    draft_id = result["draft"]["draft_id"]
    original_title = result["draft"]["title"]

    svc = StrategyDraftService(session)
    with pytest.raises(StrategyDraftError) as exc:
        svc.update(draft_id, actor="admin:7", title="직접 수정 시도")
    assert exc.value.code == "AI_GENERATED_DRAFT_REQUIRES_REVISION"

    # 원본 보존 확인 — 직접 수정 시도가 거부됐으므로 내용이 그대로여야 한다.
    unchanged = svc.get(draft_id)
    assert unchanged["title"] == original_title

    # Revision 생성은 허용되고, 원본은 REGENERATED로 보존된다.
    revision = svc.create_revision(draft_id, actor="admin:7", title="Revision 제목")
    assert revision["title"] == "Revision 제목"
    original_after = svc.get(draft_id)
    assert original_after["status"] == "REGENERATED"
    assert original_after["title"] == original_title


# ---------------------------------------------------------------------------
# 11~14: 재생성(Retry)
# ---------------------------------------------------------------------------


def test_retry_creates_new_run_with_incremented_number_and_preserves_old(
    session,
) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    gen_svc = StrategyDraftGenerationService(session)
    created = gen_svc.create_generation_run(
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
    failed = asyncio.run(gen_svc.generate(created["generation_run_id"], actor="admin:7"))
    assert failed["run"]["status"] == "FAILED"

    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'PROMOTED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()

    retried = gen_svc.retry_generation(created["generation_run_id"], actor="admin:7")
    assert retried["retry_of_run_id"] == created["generation_run_id"]
    assert retried["retry_number"] == 1

    # 기존 Run은 불변(FAILED 그대로).
    old_reloaded = gen_svc.get_generation_run(created["generation_run_id"])
    assert old_reloaded["status"] == "FAILED"

    result = asyncio.run(gen_svc.generate(retried["generation_run_id"], actor="admin:7"))
    assert result["run"]["status"] == "SUCCEEDED"
    assert result["draft"] is not None


def test_active_run_blocks_new_generation_request(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    gen_svc = StrategyDraftGenerationService(session)
    gen_svc.create_generation_run(
        strategy_request_id=request["strategy_request_id"], actor="admin:7", provider_id="mock"
    )
    with pytest.raises(StrategyDraftGenerationError) as exc:
        gen_svc.create_generation_run(
            strategy_request_id=request["strategy_request_id"],
            actor="admin:7",
            provider_id="mock",
            idempotency_key="another-key",
        )
    assert exc.value.code == "DUPLICATE_ACTIVE_GENERATION_RUN"


# ---------------------------------------------------------------------------
# 15~16: Candidate 상태/fingerprint 변경 감지용 데이터 검증
#
# 프론트엔드 경고 배너는 클라이언트에서 계산하며(e2e 인프라 없음), 여기서는
# 그 배너가 의존하는 백엔드 데이터(스냅샷 vs 현재값)가 정확히 달라짐을
# 보여주는 것으로 검증을 대체한다.
# ---------------------------------------------------------------------------


def test_snapshot_vs_current_candidate_status_diverges_after_change(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    run = StrategyDraftGenerationService(session).get_generation_run(
        result["run"]["generation_run_id"]
    )
    assert run["candidate_lifecycle_status_at_request"] == "PROMOTED"

    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' "
            "WHERE candidate_id = :cid"
        ),
        {"cid": request["candidate_id"]},
    )
    session.commit()
    current_status = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": request["candidate_id"]},
    ).scalar()
    assert current_status != run["candidate_lifecycle_status_at_request"]


def test_snapshot_vs_current_fingerprint_diverges_after_change(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    run = StrategyDraftGenerationService(session).get_generation_run(
        result["run"]["generation_run_id"]
    )
    assert run["candidate_fingerprint_at_request"] == _FINGERPRINT

    session.execute(
        text(
            "UPDATE ai.candidate_lifecycle SET source_fingerprint = :fp "
            "WHERE candidate_id = :cid"
        ),
        {"fp": "aa" * 32, "cid": request["candidate_id"]},
    )
    session.commit()
    current_fp = session.execute(
        text("SELECT source_fingerprint FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": request["candidate_id"]},
    ).scalar()
    assert current_fp != run["candidate_fingerprint_at_request"]


# ---------------------------------------------------------------------------
# 17: Mock Provider 경고용 데이터
# ---------------------------------------------------------------------------


def test_ai_generated_draft_records_mock_provider(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    result = _generate(session, request["strategy_request_id"])
    assert result["draft"]["llm_provider"] == "mock"


# ---------------------------------------------------------------------------
# 18~20: Admin 인증 / User 차단 / IDOR
# ---------------------------------------------------------------------------


def test_new_endpoints_require_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.get("/api/v1/admin/strategy-draft-generations/1/attempts").status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/admin/strategy-drafts/1/comparison", params={"compare_draft_id": 2}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/admin/strategy-requests/1/draft-timeline"
        ).status_code
        == 401
    )


def test_new_endpoints_block_non_admin_user() -> None:
    """require_admin은 get_current_user에 의존하지 않는 자체 게이팅이므로,
    일반 User(JWT)로 오버라이드해도 관리자 자격 증명이 없으면 401이다."""
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_user] = lambda: _read_only_user(999)
    try:
        resp = client.get("/api/v1/admin/strategy-draft-generations/1/attempts")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 21: Audit 본문/Prompt 미기록
# ---------------------------------------------------------------------------


def test_audit_does_not_contain_prompt_or_secrets(session) -> None:
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

    client.get(
        f"/api/v1/admin/strategy-draft-generations/{run_id}",
        headers={"X-Admin-API-Key": admin_key},
    )

    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.event_type.like("STRATEGY_DRAFT_GENERATION%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(6)
    ).all()
    assert len(events) > 0
    for event in events:
        dumped = str(event.detail)
        assert "system_template" not in dumped
        assert "task_type: STRATEGY_DRAFT" not in dumped  # system prompt 본문 마커
        assert "api_key" not in dumped.lower()


# ---------------------------------------------------------------------------
# 22~27: Ollama — 이 샌드박스에 실행 중인 Ollama(qwen3.5:4b)로 실제 검증.
#
# STEP12-2-3A: 기존(STEP12-2-3) 단일 테스트는 SUCCEEDED/FAILED/TIMED_OUT을
# 모두 통과로 인정하는 관대한 기준이었다. 원인 조사 결과 세 가지 결함이
# 있었다(완료 보고 참고):
#   1) Ollama(0.32.4)는 JSON Schema의 문자열 maxLength>=~2000에서
#      grammar 컴파일에 실패해 400을 반환한다(summary/rationale/
#      reasoning_summary를 1900으로 하향).
#   2) `result` 하위 스키마에 "required"가 없어, grammar 제약 하에서도
#      모델이 title/summary/market_type 등 일부만 채우고 조기에 객체를
#      닫아버릴 수 있었다(schema.py Pydantic 필수 필드와 동일한
#      "required" 목록을 추가).
#   3) Prompt Template 시드가 get-or-create(고정 version=1)라 코드에서
#      스키마/텍스트를 바꿔도 DB의 stale 버전을 계속 재사용했다
#      (seed.py를 checksum 기반 자동 버저닝으로 변경).
# 세 가지를 모두 고친 뒤 실측으로 SUCCEEDED + Draft 생성을 확인했다.
# 이제 "성공 조건"과 "안전한 실패 조건"을 서로 다른 테스트로 분리한다.
# ---------------------------------------------------------------------------


def _live_ollama_manager(*, max_tokens: int, temperature: float, timeout_seconds: float = 180.0):
    from stock_platform.ai.providers.config import AIProviderConfig
    from stock_platform.ai.providers.manager import AIManager
    from stock_platform.ai.providers.ollama_provider import OllamaProvider
    from stock_platform.ai.providers.registry import AIProviderRegistry

    cfg = AIProviderConfig(
        provider_id="ollama", enabled=True, is_default=True, model="qwen3.5:4b",
        api_endpoint="http://127.0.0.1:11434", timeout_seconds=timeout_seconds, retry_max=0,
        max_tokens=max_tokens, temperature=temperature,
    )
    registry = AIProviderRegistry()
    registry.register(OllamaProvider(cfg), cfg)
    return AIManager(registry=registry)


@pytest.mark.live_ai
def test_step12_2_3a_ollama_live_success_smoke(session) -> None:
    """실제 Ollama(127.0.0.1:11434, qwen3.5:4b)로 Draft 생성 SUCCEEDED를
    끝까지 검증한다(STEP12-2-3A §2 Type B) — "우아한 실패"가 아니라 실제
    성공을 요구한다. temperature=0.0/max_tokens=4000(현재 도메인 기본값,
    §16 조사로 실측 확정)을 사용해 스키마를 준수하는 완전한 구조화 출력을
    받는다. 이 테스트가 실패하면 STEP12-3 착수 전제조건이 아직 충족되지
    않은 것이다(READY_FOR_STEP12_3 선언 금지 기준)."""
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    manager = _live_ollama_manager(max_tokens=4000, temperature=0.0)

    svc = StrategyDraftGenerationService(session, ai_manager=manager)
    try:
        result = asyncio.run(
            svc.generate_strategy_draft(
                strategy_request_id=request["strategy_request_id"],
                actor="admin:7",
                provider_id="ollama",
                model="qwen3.5:4b",
            )
        )
    except Exception as exc:  # noqa: BLE001 — Ollama가 이 실행 시점에 없을 수 있음
        pytest.skip(f"Ollama 호출 실패로 스킵: {exc}")

    run = result["run"]
    assert run["status"] == "SUCCEEDED", (
        f"실 Ollama 성공 Smoke Test 실패 — status={run['status']} "
        f"error_code={run.get('error_code')} error_message={run.get('error_message')}"
    )
    assert run["draft_id"] is not None
    assert result["draft"] is not None
    assert result["draft"]["llm_provider"] == "ollama"
    assert result["draft"]["llm_model"] == "qwen3.5:4b"

    full = svc.get_generation_run(run["generation_run_id"])
    assert len(full["attempts"]) == 1
    attempt = full["attempts"][0]
    assert attempt["status"] == "SUCCEEDED"
    assert attempt["structured_response"] is not None
    for field in ("title", "summary", "market_type", "entry_rules", "exit_rules"):
        assert field in attempt["structured_response"]
    assert attempt["total_tokens"] is not None and attempt["total_tokens"] > 0
    assert attempt["latency_ms"] is not None and attempt["latency_ms"] > 0
    assert attempt["prompt_hash"] is not None
    assert attempt["response_hash"] is not None

    # 후보/지문 재검증이 실제로 이 실행 경로에서도 통과했음을 증명한다
    # (draft 생성 자체가 StrategyDraftService.create()의 재검증을 거쳤어야
    # 성공했을 것이므로, 성공 자체가 재검증 통과의 증거다).
    assert result["draft"]["candidate_fingerprint"] == _FINGERPRINT

    dumped = str(full)
    assert "api_key" not in dumped.lower()


@pytest.mark.live_ai
def test_step12_2_3a_ollama_live_safety_failure(session) -> None:
    """실제 Ollama 연결은 성공하지만 응답을 완료하지 못하는 경우
    (STEP12-2-3A §2 Type A)를 실제 네트워크 호출로 재현해, 파이프라인이
    이를 안전하게(Draft 미생성, Run FAILED/TIMED_OUT으로 종결, 에러코드/
    지연시간 기록) 처리하는지 검증한다.

    실측 결과 grammar 제약(JSON Schema format) 도입 이후 qwen3.5:4b는
    max_tokens를 10~100 사이로 무엇을 주어도(실측: 10에서도) 스키마를
    만족하는 완전한 응답을 만들어낼 만큼 견고해졌다 — 즉 "모델이 스키마를
    못 지켜서 실패"하는 경로는 이제 실 모델로 안정적으로 재현하기 어렵다
    (이는 좋은 신호다: §16 성공 Smoke Test가 신뢰할 수 있다는 근거이기도
    하다). 대신 이 테스트는 실제 추론에 필요한 시간보다 훨씬 짧은
    timeout_seconds(0.5초)를 주어, "연결은 되지만 응답을 받기 전에
    타임아웃"되는 경우를 결정적으로 재현한다 — 이는 실제 네트워크 호출을
    거치는 진짜 실패 조건이며, 스펙(§2 Type A)이 명시한 FAILED/TIMED_OUT
    두 상태 모두를 안전한 실패로 인정하는 것과 부합한다. 깨진 응답을
    복구하는 관대한 파서를 만들지 않고, 실패를 있는 그대로 기록하는지가
    이 테스트의 목적이다.

    성공 Smoke Test와 서로 다른 result_id(따라서 서로 다른 candidate_id)를
    사용해 같은 pytest 세션에서 두 live_ai 테스트가 함께 실행되어도
    candidate_lifecycle 유니크 제약과 충돌하지 않도록 격리한다."""
    if len(session.info["result_ids"]) < 2:
        pytest.skip("서로 다른 result_id 2개 필요")
    request = _create_approved_request(session, result_id=session.info["result_ids"][1])
    manager = _live_ollama_manager(max_tokens=2000, temperature=0.0, timeout_seconds=0.5)

    svc = StrategyDraftGenerationService(session, ai_manager=manager)
    try:
        result = asyncio.run(
            svc.generate_strategy_draft(
                strategy_request_id=request["strategy_request_id"],
                actor="admin:7",
                provider_id="ollama",
                model="qwen3.5:4b",
            )
        )
    except Exception as exc:  # noqa: BLE001 — Ollama가 이 실행 시점에 없을 수 있음
        pytest.skip(f"Ollama 호출 실패로 스킵: {exc}")

    run = result["run"]
    assert run["status"] in {"FAILED", "TIMED_OUT"}
    assert result["draft"] is None
    assert run["error_code"] is not None

    full = svc.get_generation_run(run["generation_run_id"])
    assert len(full["attempts"]) == 1
    attempt = full["attempts"][0]
    assert attempt["status"] in {"FAILED", "TIMED_OUT"}
    assert attempt["latency_ms"] is not None and attempt["latency_ms"] > 0
    assert attempt["prompt_hash"] is not None
    # 응답이 도착하지 않은(타임아웃) 경우가 아니라면 response_hash가 남는다.
    if run["status"] != "TIMED_OUT":
        assert attempt["response_hash"] is not None

    dumped = str(full)
    assert "api_key" not in dumped.lower()
