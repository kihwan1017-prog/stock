"""STEP 12-16 — Promotion Commit.

STEP12-15의 Decision Package/Human Decision(APPROVE_FOR_PROMOTION)을
최종 재검증한 뒤, 관리자의 명시적 요청으로만 Promotion Commit(불변
기록)을 생성한다. Activation/Deployment/Runtime 등록은 수행하지
않는다."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.decision_package import (
    run_create_decision_package,
    run_record_human_decision,
)
from stock_platform.ai.strategy_draft_approval.explainability import (
    run_generate_explainability,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo import (
    run_monte_carlo_simulation,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    run_parameter_sensitivity,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    CONFIRMATION_TEXT_REQUIRED,
    PromotionCommitError,
    _normalize_confirmation_text,
    compute_promotion_commit_hash,
    get_promotion_commit,
    get_promotion_commit_history,
    get_promotion_commit_provenance,
    get_promotion_status,
    list_promotion_commits,
    run_create_promotion_commit,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_16_TEST"
_TEST_EXCHANGE = "KRX"
_TEST_SYMBOL = "STEP1216A"


@pytest.fixture()
def result_ids() -> list[int]:
    Session = get_session_factory()
    s = Session()
    try:
        rows = s.execute(
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 5")
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    # § STEP12-16R — strategy_promotion_state/history가 strategy_promotion
    # _commit을 FK로 참조하므로 반드시 먼저 지운다.
    "DELETE FROM trading.strategy_promotion_history WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_promotion_state WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_promotion_commit WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_human_decision WHERE package_id IN "
    "(SELECT package_id FROM trading.strategy_decision_package WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM trading.strategy_decision_package WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_explainability_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.monte_carlo_simulation_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.parameter_sensitivity_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_quality_gate_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.walk_forward_window_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_16%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_16%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_16%'",
    "DELETE FROM backtest.backtest_trade WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM backtest.backtest_equity WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM backtest.backtest_run WHERE strategy_definition_id IN "
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
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1216%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1216%'",
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
        _cleanup(s)
        yield s
    finally:
        s.rollback()
        _cleanup(s)
        s.close()


def _seed_prices(session, symbol: str, closes: list[float], *, start: date) -> None:
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-16 Test')
            RETURNING instrument_id
            """
        ),
        {"exchange": _TEST_EXCHANGE, "symbol": symbol},
    ).scalar_one()
    for i, close in enumerate(closes):
        trade_date = start + timedelta(days=i)
        session.execute(
            text(
                """
                INSERT INTO market.price_daily
                (instrument_id, trade_date, open_price, high_price, low_price, close_price, volume, source)
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_16_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _triangle_wave(num_days: int, *, period: int = 30, low: float = 50.0, high: float = 100.0) -> list[float]:
    half = period // 2
    closes: list[float] = []
    for i in range(num_days):
        phase = i % period
        if phase < half:
            value = low + (high - low) * (phase / half)
        else:
            value = high - (high - low) * ((phase - half) / half)
        closes.append(round(value, 2))
    return closes


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
        {"cid": result_id, "fp": f"{result_id:064d}", "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_approved_request(session, *, result_id: int) -> dict:
    candidate_id = _create_candidate(session, result_id=result_id)
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id, user_id=_REQUESTER_USER_ID, request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    return StrategyRequestService(session).approve(
        req["strategy_request_id"], reviewer_user_id=_REVIEWER_USER_ID, review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )


def _approve(session, strategy_request_id: int) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, actor="admin:7", title="수동 초안",
        timeframe="1D", market_type="KR_STOCK",
        entry_rule='[{"indicator":"RSI","operator":"LT","threshold":30,"lookback":14}]',
        exit_rule='[{"indicator":"RSI","operator":"GT","threshold":70,"lookback":14}]',
        stop_loss_rule='{"type":"PERCENT","value":5}', take_profit_rule='{"type":"PERCENT","value":10}',
        position_sizing_rule='{"method":"FIXED_PERCENT","value":0.1}',
    )
    return StrategyDraftApprovalService(session).approve(draft["draft_id"], actor="admin:7", reason="승인")


def _runtime_input(**overrides) -> dict:
    base = {
        "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
        "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
        "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
    }
    base.update(overrides)
    return base


def _run_backtest(session, strategy_definition_id: int) -> int:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    result = run_definition_backtest(
        session, strategy_definition_id, runtime_input=_runtime_input(), actor="STEP12_16_TEST:admin",
    )
    return result["backtest_run_id"]


def _seed_committable(session) -> dict:
    """승인 Strategy + Backtest/Quality Gate/Sensitivity/Monte Carlo/
    Explainability/Decision Package/APPROVE_FOR_PROMOTION Decision까지
    전부 생성해(Promotion Commit 직전 상태) 반환한다."""
    ids = session.info["result_ids"]
    _seed_prices(session, _TEST_SYMBOL, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_16_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(),
        actor="STEP12_16_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_16_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_16_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_16_TEST:admin",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="검토 완료, 승인합니다.",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_16_TEST:reviewer",
    )

    return {
        "strategy_id": strategy_id,
        "backtest_run_id": backtest_run_id,
        "package_id": package["package_id"],
        "decision_id": decision["decision_id"],
        "promotion_readiness_hash": decision["promotion_readiness_hash"],
    }


def _commit_kwargs(seed: dict, **overrides) -> dict:
    base = dict(
        decision_package_id=seed["package_id"], human_decision_id=seed["decision_id"],
        promotion_readiness_hash=seed["promotion_readiness_hash"], commit_reason="검토 완료, 승인합니다.",
        confirmation_text="PROMOTE", actor="STEP12_16_TEST:committer",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A: Confirmation / Hash — 순수 함수 단위.
# ---------------------------------------------------------------------------


def test_confirmation_text_case_and_whitespace_policy() -> None:
    assert _normalize_confirmation_text("promote") == CONFIRMATION_TEXT_REQUIRED
    assert _normalize_confirmation_text("  PROMOTE  ") == CONFIRMATION_TEXT_REQUIRED
    assert _normalize_confirmation_text("Promote") == CONFIRMATION_TEXT_REQUIRED
    assert _normalize_confirmation_text("PROMOTE!") != CONFIRMATION_TEXT_REQUIRED
    assert _normalize_confirmation_text("") != CONFIRMATION_TEXT_REQUIRED


def test_promotion_commit_hash_deterministic_and_sensitive() -> None:
    from datetime import datetime, timezone

    base_kwargs = dict(
        strategy_definition_id=1, strategy_definition_version=1, definition_hash="dh", executable_hash="eh",
        approval_snapshot_hash="ah", decision_package_id=10, package_input_hash="pih", human_decision_id=20,
        decision_input_hash="dih", promotion_readiness_hash="prh", previous_lifecycle_status="PROMOTED",
        committed_lifecycle_status="PROMOTED", committed_by="admin",
        committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), confirmation_hash="ch", algorithm_version="1.0.0",
    )
    assert compute_promotion_commit_hash(**base_kwargs) == compute_promotion_commit_hash(**base_kwargs)
    changed = {**base_kwargs, "definition_hash": "different"}
    assert compute_promotion_commit_hash(**base_kwargs) != compute_promotion_commit_hash(**changed)
    changed_actor = {**base_kwargs, "committed_by": "different_admin"}
    assert compute_promotion_commit_hash(**base_kwargs) != compute_promotion_commit_hash(**changed_actor)


# ---------------------------------------------------------------------------
# B: Promotion Commit 성공 / 결과 필드 고정값.
# ---------------------------------------------------------------------------


def test_promotion_commit_success_fixed_result_fields(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert result["promotion_committed"] is True
    assert result["current_lifecycle_status"] == "PROMOTED"
    assert result["activation_status"] == "NOT_STARTED"
    assert result["deployment_status"] == "NOT_STARTED"
    assert result["runtime_status"] == "NOT_REGISTERED"
    assert result["next_action"] == "REVIEW_ACTIVATION"


def test_promotion_commit_does_not_touch_candidate_lifecycle_table(session) -> None:
    """§ 모듈 docstring 핵심 결정 — ai.candidate_lifecycle을 절대 WRITE
    하지 않는다(읽기 전용 게이팅에만 사용)."""
    seed = _seed_committable(session)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    before = session.execute(
        text("SELECT lifecycle_status, updated_at FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).fetchone()

    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))

    after = session.execute(
        text("SELECT lifecycle_status, updated_at FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).fetchone()
    assert before == after


# ---------------------------------------------------------------------------
# C: Preconditions — 각 조건 실패 시 Fail Closed.
# ---------------------------------------------------------------------------


def test_precondition_strategy_not_found(session) -> None:
    seed = _seed_committable(session)
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, seed["strategy_id"] + 999999, **_commit_kwargs(seed))
    assert exc_info.value.code == "NOT_FOUND"


def test_precondition_package_not_found(session) -> None:
    seed = _seed_committable(session)
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(
            session, seed["strategy_id"], **_commit_kwargs(seed, decision_package_id=999999999)
        )
    assert exc_info.value.code == "PACKAGE_NOT_FOUND"


def test_precondition_decision_not_found(session) -> None:
    seed = _seed_committable(session)
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(
            session, seed["strategy_id"], **_commit_kwargs(seed, human_decision_id=999999999)
        )
    assert exc_info.value.code == "DECISION_NOT_FOUND"


def test_precondition_cross_strategy_package_blocked(session) -> None:
    seed_a = _seed_committable(session)
    ids = session.info["result_ids"]
    if len(ids) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 재현할 수 없음")
    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"])

    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, approval_b["strategy_definition_id"], **_commit_kwargs(seed_a))
    assert exc_info.value.code == "OWNERSHIP_MISMATCH"


def test_precondition_decision_type_mismatch(session) -> None:
    ids = session.info["result_ids"]
    _seed_prices(session, "STEP1216REJ", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run = run_definition_backtest(
        session, strategy_id, runtime_input=_runtime_input(symbol="STEP1216REJ"), actor="STEP12_16_TEST:admin",
    )
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_16_TEST:admin")
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=run["backtest_run_id"],
        quality_gate_report_id=quality_gate["quality_gate_report_id"], actor="STEP12_16_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_16_TEST:admin",
    )
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="REJECT",
        reason_code="UNACCEPTABLE_RISK", reason_text="위험", actor="STEP12_16_TEST:reviewer",
    )

    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(
            session, strategy_id, decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
            promotion_readiness_hash="whatever", commit_reason="ok", confirmation_text="PROMOTE",
            actor="STEP12_16_TEST:committer",
        )
    assert exc_info.value.code == "DECISION_TYPE_MISMATCH"


def test_precondition_readiness_hash_mismatch(session) -> None:
    seed = _seed_committable(session)
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(
            session, seed["strategy_id"], **_commit_kwargs(seed, promotion_readiness_hash="wrong-hash")
        )
    assert exc_info.value.code == "READINESS_HASH_MISMATCH"


def test_precondition_invalid_confirmation(session) -> None:
    seed = _seed_committable(session)
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed, confirmation_text="YES"))
    assert exc_info.value.code == "INVALID_CONFIRMATION"


def test_precondition_stale_promotion_readiness(session) -> None:
    seed = _seed_committable(session)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    session.execute(
        text("UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    )
    session.commit()

    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert exc_info.value.code in {"STALE_PROMOTION_READINESS", "LIFECYCLE_NOT_PROMOTABLE"}


def test_precondition_already_promoted(session) -> None:
    seed = _seed_committable(session)
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert exc_info.value.code == "ALREADY_PROMOTED"


def test_precondition_same_actor_warning_not_acknowledged_blocked(session) -> None:
    ids = session.info["result_ids"]
    _seed_prices(session, "STEP1216SAW", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run = run_definition_backtest(
        session, strategy_id, runtime_input=_runtime_input(symbol="STEP1216SAW"), actor="STEP12_16_TEST:admin",
    )
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_16_TEST:admin")
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=run["backtest_run_id"],
        quality_gate_report_id=quality_gate["quality_gate_report_id"], actor="STEP12_16_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_16_TEST:same_person",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="ok",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_16_TEST:same_person",
    )
    assert decision["same_actor_warning"] is True

    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(
            session, strategy_id, decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
            promotion_readiness_hash=decision["promotion_readiness_hash"], commit_reason="ok",
            confirmation_text="PROMOTE", acknowledge_same_actor_warning=False, actor="STEP12_16_TEST:same_person",
        )
    assert exc_info.value.code == "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED"

    result = run_create_promotion_commit(
        session, strategy_id, decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
        promotion_readiness_hash=decision["promotion_readiness_hash"], commit_reason="ok",
        confirmation_text="PROMOTE", acknowledge_same_actor_warning=True, actor="STEP12_16_TEST:same_person",
    )
    assert result["promotion_committed"] is True


# ---------------------------------------------------------------------------
# D: Idempotency.
# ---------------------------------------------------------------------------


def test_promotion_commit_idempotency_replay(session) -> None:
    seed = _seed_committable(session)
    r1 = run_create_promotion_commit(
        session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16-idem-1")
    )
    r2 = run_create_promotion_commit(
        session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16-idem-1")
    )
    assert r1["promotion_commit_id"] == r2["promotion_commit_id"]
    assert r2["idempotent_replay"] is True


def test_promotion_commit_different_idempotency_key_after_promoted_is_conflict(session) -> None:
    """이미 Promotion된 Strategy에 다른 idempotency_key로 재요청하면
    (재시도로 보이므로) IDEMPOTENCY_CONFLICT다."""
    seed = _seed_committable(session)
    run_create_promotion_commit(
        session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16-idem-a")
    )
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(
            session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16-idem-b")
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_promotion_commit_no_key_after_promoted_is_already_promoted(session) -> None:
    """idempotency_key 없이 이미 Promotion된 Strategy를 재요청하면
    ALREADY_PROMOTED다."""
    seed = _seed_committable(session)
    run_create_promotion_commit(
        session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16-idem-once")
    )
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert exc_info.value.code == "ALREADY_PROMOTED"


# ---------------------------------------------------------------------------
# E: Human Decision 불변성(Commit 전후).
# ---------------------------------------------------------------------------


def test_human_decision_unchanged_before_and_after_commit(session) -> None:
    from stock_platform.ai.strategy_draft_approval.decision_package import get_human_decision

    seed = _seed_committable(session)
    before = get_human_decision(session, seed["package_id"])
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    after = get_human_decision(session, seed["package_id"])
    assert before == after


def test_decision_package_unchanged_before_and_after_commit(session) -> None:
    from stock_platform.ai.strategy_draft_approval.decision_package import (
        get_decision_package_report,
    )

    seed = _seed_committable(session)
    before = get_decision_package_report(session, seed["package_id"])
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    after = get_decision_package_report(session, seed["package_id"])
    # effective_package_status는 has_decision/promotion 여부와 무관하게
    # Package 자체의 Stale/Decided 파생값이라 동일해야 한다(Commit이
    # Package 행을 변경하지 않음).
    assert before["package_status"] == after["package_status"]
    assert before["package_input_hash"] == after["package_input_hash"]


# ---------------------------------------------------------------------------
# F: Persistence / 조회 / API / Audit.
# ---------------------------------------------------------------------------


def test_promotion_commit_persists_and_retrievable(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    fetched = get_promotion_commit(session, result["promotion_commit_id"])
    assert fetched["promotion_commit_hash"] == result["promotion_commit_hash"]


def test_promotion_commit_list_and_history(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    commits = list_promotion_commits(session, seed["strategy_id"])
    assert len(commits) == 1
    assert commits[0]["promotion_commit_id"] == result["promotion_commit_id"]

    history = get_promotion_commit_history(session, seed["strategy_id"])
    assert len(history["history"]) == 1
    assert history["history"][0]["previous_status"] == "NOT_PROMOTED"
    assert history["history"][0]["new_status"] == "PROMOTION_COMMITTED"
    assert history["history"][0]["promotion_commit_id"] == result["promotion_commit_id"]

    provenance = get_promotion_commit_provenance(session, result["promotion_commit_id"])
    assert provenance["promotion_commit_hash"] == result["promotion_commit_hash"]


def test_promotion_status_before_and_after_commit(session) -> None:
    seed = _seed_committable(session)
    before = get_promotion_status(session, seed["strategy_id"])
    assert before["promotion_committed"] is False
    assert before["promotion_ready"] is True

    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    after = get_promotion_status(session, seed["strategy_id"])
    assert after["promotion_committed"] is True
    assert after["next_action"] == "REVIEW_ACTIVATION"


def test_promotion_commit_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategies/1/promotion-commits",
        json={"decision_package_id": 1, "human_decision_id": 1, "promotion_readiness_hash": "x", "commit_reason": "x", "confirmation_text": "PROMOTE"},
    )
    assert resp.status_code == 401


def test_promotion_commit_api_full_flow(session) -> None:
    seed = _seed_committable(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits",
        json={
            "decision_package_id": seed["package_id"], "human_decision_id": seed["decision_id"],
            "promotion_readiness_hash": seed["promotion_readiness_hash"], "commit_reason": "검토 완료",
            "confirmation_text": "PROMOTE",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["promotion_committed"] is True
    commit_id = body["promotion_commit_id"]

    for path in (
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits",
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits/{commit_id}",
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-status",
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits/{commit_id}/provenance",
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits/{commit_id}/history",
    ):
        r = client.get(path, headers={"X-Admin-API-Key": admin_key})
        assert r.status_code == 200


def test_promotion_commit_api_cross_strategy_404(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    other_strategy_id = seed["strategy_id"] + 999999
    resp = client.get(
        f"/api/v1/admin/strategies/{other_strategy_id}/promotion-commits/{result['promotion_commit_id']}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


def test_promotion_commit_api_invalid_confirmation(session) -> None:
    seed = _seed_committable(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits",
        json={
            "decision_package_id": seed["package_id"], "human_decision_id": seed["decision_id"],
            "promotion_readiness_hash": seed["promotion_readiness_hash"], "commit_reason": "ok",
            "confirmation_text": "NO",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 400


def test_promotion_commit_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    seed = _seed_committable(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits",
        json={
            "decision_package_id": seed["package_id"], "human_decision_id": seed["decision_id"],
            "promotion_readiness_hash": seed["promotion_readiness_hash"], "commit_reason": "검토 완료",
            "confirmation_text": "PROMOTE",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    commit_id = resp.json()["promotion_commit_id"]
    client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-status", headers={"X-Admin-API-Key": admin_key},
    )
    client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits/{commit_id}/provenance",
        headers={"X-Admin-API-Key": admin_key},
    )
    client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-commits/{commit_id}/history",
        headers={"X-Admin-API-Key": admin_key},
    )

    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("PROMOTION_%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(20)
    ).all()
    event_types = {e[0] for e in events}
    assert "PROMOTION_COMMIT_STARTED" in event_types
    assert "PROMOTION_COMMIT_COMPLETED" in event_types
    assert "PROMOTION_COMMIT_VIEWED" in event_types
    assert "PROMOTION_STATUS_VIEWED" in event_types
    assert "PROMOTION_PROVENANCE_VIEWED" in event_types
    assert "PROMOTION_HISTORY_VIEWED" in event_types


# ---------------------------------------------------------------------------
# G: Regression — STEP12-15/14/13/12.
# ---------------------------------------------------------------------------


def test_step12_15_decision_package_regression(session) -> None:
    seed = _seed_committable(session)
    from stock_platform.ai.strategy_draft_approval.decision_package import (
        get_decision_package_report,
    )

    package = get_decision_package_report(session, seed["package_id"])
    assert package["package_status"] == "READY_FOR_REVIEW"


def test_step12_10_quality_gate_regression(session) -> None:
    seed = _seed_committable(session)
    result = run_quality_gate(session, seed["strategy_id"], actor="STEP12_16_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}
