"""STEP 12-15 — Decision Package & Human Decision.

이미 생성된 Strategy Definition/Approval Snapshot/Backtest/Performance/
Walk-Forward/Quality Gate/Parameter Sensitivity/Monte Carlo/Portfolio
Validation/Explainability(STEP12-5~14) 결과를 하나의 동결된 Decision
Package로 묶고, 관리자가 APPROVE_FOR_PROMOTION/REQUEST_CHANGES/REJECT
중 하나를 불변으로 기록한다. 이번 STEP은 Decision 기록까지만 하고 실제
Promotion Commit/Runtime 등록은 수행하지 않는다."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.decision_package import (
    DECISION_TYPES,
    REASON_CODES_BY_DECISION_TYPE,
    DecisionPackageError,
    _build_checklist_template,
    _determine_next_action,
    check_package_staleness,
    compute_decision_input_hash,
    compute_package_input_hash,
    compute_promotion_readiness_hash,
    get_decision_package_report,
    get_decision_package_summary,
    get_human_decision,
    get_promotion_readiness,
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
_MARKER = "STEP12_15_TEST"
_TEST_EXCHANGE = "KRX"
_TEST_SYMBOL = "STEP1215A"


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
    # API를 통해 생성된 행은 package_created_by/decided_by가 테스트 마커가
    # 아니라 실제 admin 사용자명이라(§ STEP12-13/14에서 이미 발견된 동일
    # 유형의 버그) 패턴 매칭이 아니라 Strategy 소유 체인으로 걸러야 한다.
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
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_15%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_15%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_15%'",
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
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1215%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1215%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-15 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_15_TEST')
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
        session, strategy_definition_id, runtime_input=_runtime_input(), actor="STEP12_15_TEST:admin",
    )
    return result["backtest_run_id"]


def _seed_ready_package_inputs(session) -> dict:
    """승인 Strategy + Backtest/Quality Gate/Sensitivity/Monte Carlo +
    Explainability Report까지 전부 생성해(APPROVE 가능한 상태) 반환한다."""
    ids = session.info["result_ids"]
    _seed_prices(session, _TEST_SYMBOL, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_15_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(),
        actor="STEP12_15_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_15_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_15_TEST:admin",
    )

    return {
        "strategy_id": strategy_id,
        "backtest_run_id": backtest_run_id,
        "quality_gate_report_id": quality_gate["quality_gate_report_id"],
        "parameter_sensitivity_report_id": sensitivity["parameter_sensitivity_report_id"],
        "monte_carlo_report_id": monte_carlo["monte_carlo_report_id"],
        "explainability_report_id": explainability["explainability_report_id"],
        "explainability": explainability,
    }


def _create_ready_package(session, seed: dict, *, actor: str = "STEP12_15_TEST:admin", idempotency_key=None) -> dict:
    return run_create_decision_package(
        session, seed["strategy_id"], explainability_report_id=seed["explainability_report_id"],
        actor=actor, idempotency_key=idempotency_key,
    )


def _approve_ready_package(session, seed: dict, package: dict, *, actor: str = "STEP12_15_TEST:reviewer") -> dict:
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    confirmations = {code: True for code in required_codes}
    acknowledged = ["ALL"] if package["warning_evidence_count"] > 0 else []
    return run_record_human_decision(
        session, seed["strategy_id"], package["package_id"],
        decision_type="APPROVE_FOR_PROMOTION", reason_code="EVIDENCE_REVIEW_COMPLETED",
        reason_text="검토 완료, 승인합니다.", checklist_confirmations=confirmations,
        acknowledged_warnings=acknowledged, actor=actor,
    )


# ---------------------------------------------------------------------------
# A: Checklist Template / Readiness / Hash — 순수 함수 단위.
# ---------------------------------------------------------------------------


def test_checklist_template_conditional_items_required_only_when_present() -> None:
    template = _build_checklist_template(
        has_walk_forward=False, has_sensitivity=True, has_monte_carlo=False, has_portfolio=False,
    )
    by_code = {c["checklist_code"]: c for c in template}
    assert by_code["WALK_FORWARD_OVERFITTING_CONFIRMED"]["required"] is False
    assert by_code["SENSITIVITY_STABLE_RANGE_CONFIRMED"]["required"] is True
    assert by_code["MONTE_CARLO_RISK_OF_RUIN_CONFIRMED"]["required"] is False
    assert by_code["PORTFOLIO_EXPOSURE_CONFIRMED"]["required"] is False
    assert by_code["DEFINITION_VERSION_CONFIRMED"]["required"] is True


def test_reason_code_decision_type_combinations_are_disjoint() -> None:
    approve = REASON_CODES_BY_DECISION_TYPE["APPROVE_FOR_PROMOTION"]
    reject = REASON_CODES_BY_DECISION_TYPE["REJECT"]
    assert approve.isdisjoint(reject)
    assert "QUALITY_GATE_REJECTED" in reject
    assert "EVIDENCE_REVIEW_COMPLETED" in approve


def test_next_action_stale_takes_priority() -> None:
    action = _determine_next_action(
        stale=True, has_decision=True, decision_type="APPROVE_FOR_PROMOTION",
        required_evidence_complete=True, blocking_evidence_count=0, warning_evidence_count=0,
    )
    assert action == "RECREATE_STALE_PACKAGE"


def test_next_action_decided_approve_ready_for_commit() -> None:
    action = _determine_next_action(
        stale=False, has_decision=True, decision_type="APPROVE_FOR_PROMOTION",
        required_evidence_complete=True, blocking_evidence_count=0, warning_evidence_count=0,
    )
    assert action == "READY_FOR_PROMOTION_COMMIT"


def test_next_action_decided_reject_no_action() -> None:
    action = _determine_next_action(
        stale=False, has_decision=True, decision_type="REJECT",
        required_evidence_complete=True, blocking_evidence_count=0, warning_evidence_count=0,
    )
    assert action == "NO_ACTION_REJECTED"


def test_next_action_missing_evidence_before_decision() -> None:
    action = _determine_next_action(
        stale=False, has_decision=False, decision_type=None,
        required_evidence_complete=False, blocking_evidence_count=0, warning_evidence_count=0,
    )
    assert action == "COMPLETE_EVIDENCE"


def test_next_action_warnings_before_decision() -> None:
    action = _determine_next_action(
        stale=False, has_decision=False, decision_type=None,
        required_evidence_complete=True, blocking_evidence_count=0, warning_evidence_count=2,
    )
    assert action == "REVIEW_WARNINGS"


def test_package_input_hash_stable_and_sensitive() -> None:
    base_kwargs = dict(
        strategy_definition_id=1, strategy_definition_version=1, executable_hash="h",
        selected_report_ids={"backtest": 10, "quality_gate": 20}, explainability_input_hash="eih",
        package_algorithm_version="1.0.0",
    )
    assert compute_package_input_hash(**base_kwargs) == compute_package_input_hash(**base_kwargs)
    changed = {**base_kwargs, "executable_hash": "different"}
    assert compute_package_input_hash(**base_kwargs) != compute_package_input_hash(**changed)


def test_decision_input_hash_sensitive_to_reason_text() -> None:
    base_kwargs = dict(
        package_id=1, package_input_hash="p", decision_type="REJECT", reason_code="POLICY_VIOLATION",
        reason_text="사유 A", checklist_payload=[{"checklist_code": "X", "confirmed": True}],
        acknowledged_warnings=[], decided_by="admin", algorithm_version="1.0.0",
    )
    changed = {**base_kwargs, "reason_text": "사유 B"}
    assert compute_decision_input_hash(**base_kwargs) != compute_decision_input_hash(**changed)


def test_promotion_readiness_hash_deterministic() -> None:
    from datetime import datetime, timezone

    kwargs = dict(
        package_id=1, package_input_hash="p", decision_id=5, decision_type="APPROVE_FOR_PROMOTION",
        decided_by="admin", checklist_payload=[{"checklist_code": "X", "confirmed": True}],
        acknowledged_warnings=[], reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="ok",
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc), algorithm_version="1.0.0",
    )
    assert compute_promotion_readiness_hash(**kwargs) == compute_promotion_readiness_hash(**kwargs)


# ---------------------------------------------------------------------------
# B: Package 생성 — Source Evidence Validation / Readiness / Persistence.
# ---------------------------------------------------------------------------


def test_create_decision_package_success_ready_for_review(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    assert package["package_status"] == "READY_FOR_REVIEW"
    assert package["required_evidence_complete"] is True
    assert package["stale"] is False
    assert package["blocking_evidence_count"] == 0


def test_create_decision_package_reuses_explainability_source_reports(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    assert package["quality_gate_report_id"] == seed["quality_gate_report_id"]
    assert package["parameter_sensitivity_report_id"] == seed["parameter_sensitivity_report_id"]
    assert package["monte_carlo_report_id"] == seed["monte_carlo_report_id"]


def test_create_decision_package_explicit_report_id_mismatch_blocked(session) -> None:
    seed = _seed_ready_package_inputs(session)
    with pytest.raises(DecisionPackageError) as exc_info:
        run_create_decision_package(
            session, seed["strategy_id"], explainability_report_id=seed["explainability_report_id"],
            quality_gate_report_id=seed["quality_gate_report_id"] + 999999,
            actor="STEP12_15_TEST:admin",
        )
    assert exc_info.value.code == "REPORT_ID_MISMATCH"


def test_create_decision_package_explicit_report_id_matching_allowed(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = run_create_decision_package(
        session, seed["strategy_id"], explainability_report_id=seed["explainability_report_id"],
        quality_gate_report_id=seed["quality_gate_report_id"], actor="STEP12_15_TEST:admin",
    )
    assert package["quality_gate_report_id"] == seed["quality_gate_report_id"]


def test_create_decision_package_cross_strategy_explainability_blocked(session) -> None:
    seed_a = _seed_ready_package_inputs(session)
    ids = session.info["result_ids"]
    if len(ids) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 재현할 수 없음")
    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"])

    with pytest.raises(DecisionPackageError) as exc_info:
        run_create_decision_package(
            session, approval_b["strategy_definition_id"],
            explainability_report_id=seed_a["explainability_report_id"], actor="STEP12_15_TEST:admin",
        )
    assert exc_info.value.code == "OWNERSHIP_MISMATCH"


def test_create_decision_package_blocked_when_quality_gate_missing_in_explainability(session) -> None:
    """필수 Evidence(Quality Gate)가 Explainability 자체에 없으면 Package는
    BLOCKED다(임의로 READY_FOR_REVIEW로 만들지 않는다)."""
    ids = session.info["result_ids"]
    _seed_prices(session, "STEP1215NOQG", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input=_runtime_input(symbol="STEP1215NOQG"), actor="STEP12_15_TEST:admin",
    )
    explainability = run_generate_explainability(
        session, approval["strategy_definition_id"], backtest_run_id=run["backtest_run_id"],
        use_latest_when_missing=False, actor="STEP12_15_TEST:admin",
    )
    package = run_create_decision_package(
        session, approval["strategy_definition_id"], explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_15_TEST:admin",
    )
    assert package["package_status"] == "BLOCKED"
    assert "QUALITY_GATE_NOT_AVAILABLE" in package["readiness_reason_codes"]


def test_create_decision_package_persists_and_immutable(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    fetched = get_decision_package_report(session, package["package_id"])
    assert fetched["package_status"] == package["package_status"]
    assert fetched["package_input_hash"] == package["package_input_hash"]


def test_create_decision_package_rerun_creates_new_package(session) -> None:
    seed = _seed_ready_package_inputs(session)
    p1 = _create_ready_package(session, seed)
    p2 = _create_ready_package(session, seed)
    assert p1["package_id"] != p2["package_id"]


def test_create_decision_package_idempotency_replay(session) -> None:
    seed = _seed_ready_package_inputs(session)
    p1 = _create_ready_package(session, seed, idempotency_key="step12-15-pkg-1")
    p2 = _create_ready_package(session, seed, idempotency_key="step12-15-pkg-1")
    assert p1["package_id"] == p2["package_id"]
    assert p2["idempotent_replay"] is True


def test_create_decision_package_idempotency_conflict(session) -> None:
    """package_input_hash는 explainability_input_hash에 의존하므로, 실제로
    다른 Package 내용을 만들려면 다른 Quality Gate Report ID를 참조하는
    "두 번째" Explainability Report가 필요하다(package_note처럼 해시에
    포함되지 않는 자유 텍스트만 바꿔서는 진짜 다른 내용이 되지 않는다)."""
    seed = _seed_ready_package_inputs(session)
    _create_ready_package(session, seed, idempotency_key="step12-15-pkg-conflict")

    second_quality_gate = run_quality_gate(session, seed["strategy_id"], actor="STEP12_15_TEST:admin")
    second_explainability = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"],
        quality_gate_report_id=second_quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=seed["parameter_sensitivity_report_id"],
        monte_carlo_report_id=seed["monte_carlo_report_id"], actor="STEP12_15_TEST:admin",
    )
    with pytest.raises(DecisionPackageError) as exc_info:
        run_create_decision_package(
            session, seed["strategy_id"], explainability_report_id=second_explainability["explainability_report_id"],
            actor="STEP12_15_TEST:admin", idempotency_key="step12-15-pkg-conflict",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


# ---------------------------------------------------------------------------
# C: Stale Detection.
# ---------------------------------------------------------------------------


def test_package_not_stale_immediately_after_creation(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    from stock_platform.ai.strategy_draft_approval.decision_package_entities import (
        StrategyDecisionPackageEntity,
    )

    entity = session.get(StrategyDecisionPackageEntity, package["package_id"])
    stale, reasons = check_package_staleness(session, entity)
    assert stale is False
    assert reasons == []


def test_package_stale_after_lifecycle_revoked(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    from stock_platform.ai.strategy_draft_approval.decision_package_entities import (
        StrategyDecisionPackageEntity,
    )
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    session.execute(
        text("UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    )
    session.commit()

    entity = session.get(StrategyDecisionPackageEntity, package["package_id"])
    stale, reasons = check_package_staleness(session, entity)
    assert stale is True
    assert any(r.startswith("LIFECYCLE_") for r in reasons)


def test_stale_package_blocks_decision(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    session.execute(
        text("UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    )
    session.commit()

    with pytest.raises(DecisionPackageError) as exc_info:
        _approve_ready_package(session, seed, package)
    assert exc_info.value.code == "STALE_PACKAGE"


# ---------------------------------------------------------------------------
# D: Human Decision.
# ---------------------------------------------------------------------------


def test_approve_for_promotion_success(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    decision = _approve_ready_package(session, seed, package)
    assert decision["decision_type"] == "APPROVE_FOR_PROMOTION"
    assert decision["promotion_ready"] is True
    assert decision["promotion_readiness_hash"] is not None


def test_request_changes_success(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    decision = run_record_human_decision(
        session, seed["strategy_id"], package["package_id"],
        decision_type="REQUEST_CHANGES", reason_code="PARAMETER_FRAGILITY",
        reason_text="파라미터 민감도가 우려됩니다.", actor="STEP12_15_TEST:reviewer",
    )
    assert decision["decision_type"] == "REQUEST_CHANGES"
    assert decision["promotion_ready"] is False


def test_reject_success(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    decision = run_record_human_decision(
        session, seed["strategy_id"], package["package_id"],
        decision_type="REJECT", reason_code="UNACCEPTABLE_RISK",
        reason_text="위험 수준이 허용 범위를 벗어납니다.", actor="STEP12_15_TEST:reviewer",
    )
    assert decision["decision_type"] == "REJECT"
    assert decision["promotion_ready"] is False


def test_approve_requires_package_ready(session) -> None:
    ids = session.info["result_ids"]
    _seed_prices(session, "STEP1215BLK", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input=_runtime_input(symbol="STEP1215BLK"), actor="STEP12_15_TEST:admin",
    )
    explainability = run_generate_explainability(
        session, approval["strategy_definition_id"], backtest_run_id=run["backtest_run_id"],
        use_latest_when_missing=False, actor="STEP12_15_TEST:admin",
    )
    package = run_create_decision_package(
        session, approval["strategy_definition_id"], explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_15_TEST:admin",
    )
    assert package["package_status"] == "BLOCKED"

    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, approval["strategy_definition_id"], package["package_id"],
            decision_type="APPROVE_FOR_PROMOTION", reason_code="EVIDENCE_REVIEW_COMPLETED",
            reason_text="ok", actor="STEP12_15_TEST:reviewer",
        )
    assert exc_info.value.code == "PACKAGE_NOT_READY"


def test_approve_requires_full_checklist(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"],
            decision_type="APPROVE_FOR_PROMOTION", reason_code="EVIDENCE_REVIEW_COMPLETED",
            reason_text="ok", checklist_confirmations={}, actor="STEP12_15_TEST:reviewer",
        )
    assert exc_info.value.code == "INCOMPLETE_CHECKLIST"


def test_reason_text_required(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"],
            decision_type="REJECT", reason_code="UNACCEPTABLE_RISK", reason_text="   ",
            actor="STEP12_15_TEST:reviewer",
        )
    assert exc_info.value.code == "REASON_TEXT_REQUIRED"


def test_reason_code_decision_type_mismatch_blocked(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"],
            decision_type="REJECT", reason_code="EVIDENCE_REVIEW_COMPLETED",  # APPROVE 전용 코드
            reason_text="ok", actor="STEP12_15_TEST:reviewer",
        )
    assert exc_info.value.code == "INVALID_REASON_CODE"


def test_duplicate_decision_blocked(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    _approve_ready_package(session, seed, package)
    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"],
            decision_type="REJECT", reason_code="UNACCEPTABLE_RISK", reason_text="다시 반려",
            actor="STEP12_15_TEST:reviewer2",
        )
    assert exc_info.value.code == "DUPLICATE_DECISION"


def test_decision_idempotency_replay(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    confirmations = {code: True for code in required_codes}
    d1 = run_record_human_decision(
        session, seed["strategy_id"], package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="ok", checklist_confirmations=confirmations,
        acknowledged_warnings=["ALL"], actor="STEP12_15_TEST:reviewer", idempotency_key="step12-15-dec-1",
    )
    d2 = run_record_human_decision(
        session, seed["strategy_id"], package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="ok", checklist_confirmations=confirmations,
        acknowledged_warnings=["ALL"], actor="STEP12_15_TEST:reviewer", idempotency_key="step12-15-dec-1",
    )
    assert d1["decision_id"] == d2["decision_id"]
    assert d2["idempotent_replay"] is True


def test_decision_idempotency_conflict(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    confirmations = {code: True for code in required_codes}
    run_record_human_decision(
        session, seed["strategy_id"], package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="ok", checklist_confirmations=confirmations,
        acknowledged_warnings=["ALL"], actor="STEP12_15_TEST:reviewer", idempotency_key="step12-15-dec-conflict",
    )
    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"], decision_type="REJECT",
            reason_code="UNACCEPTABLE_RISK", reason_text="다른 사유", checklist_confirmations={},
            actor="STEP12_15_TEST:reviewer", idempotency_key="step12-15-dec-conflict",
        )
    assert exc_info.value.code in {"IDEMPOTENCY_CONFLICT", "DUPLICATE_DECISION"}


def test_same_actor_warning_true_when_creator_equals_decider(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = run_create_decision_package(
        session, seed["strategy_id"], explainability_report_id=seed["explainability_report_id"],
        actor="STEP12_15_TEST:same_person",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, seed["strategy_id"], package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="ok",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_15_TEST:same_person",
    )
    assert decision["same_actor_warning"] is True


def test_same_actor_warning_false_when_different_reviewer(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed, actor="STEP12_15_TEST:creator")
    decision = _approve_ready_package(session, seed, package, actor="STEP12_15_TEST:different_reviewer")
    assert decision["same_actor_warning"] is False


# ---------------------------------------------------------------------------
# E: Promotion Readiness.
# ---------------------------------------------------------------------------


def test_promotion_readiness_true_after_approve(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    _approve_ready_package(session, seed, package)
    readiness = get_promotion_readiness(session, seed["strategy_id"])
    assert readiness["ready"] is True
    assert readiness["promotion_readiness_hash"] is not None
    assert readiness["next_action"] == "READY_FOR_PROMOTION_COMMIT"


def test_promotion_readiness_false_when_no_decision(session) -> None:
    seed = _seed_ready_package_inputs(session)
    readiness = get_promotion_readiness(session, seed["strategy_id"])
    assert readiness["ready"] is False
    assert readiness["decision_id"] is None


def test_promotion_readiness_false_after_reject(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    run_record_human_decision(
        session, seed["strategy_id"], package["package_id"], decision_type="REJECT",
        reason_code="UNACCEPTABLE_RISK", reason_text="위험", actor="STEP12_15_TEST:reviewer",
    )
    readiness = get_promotion_readiness(session, seed["strategy_id"])
    assert readiness["ready"] is False


def test_promotion_readiness_stale_after_decision(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    _approve_ready_package(session, seed, package)

    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    session.execute(
        text("UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    )
    session.commit()

    readiness = get_promotion_readiness(session, seed["strategy_id"])
    assert readiness["stale_after_decision"] is True
    assert readiness["ready"] is False
    assert readiness["next_action"] == "STALE_AFTER_DECISION"


def test_promotion_readiness_does_not_touch_lifecycle_or_definition(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    before = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    before_snapshot = (before.definition_hash, before.approval_id, before.is_active)

    _approve_ready_package(session, seed, package)
    get_promotion_readiness(session, seed["strategy_id"])

    session.expire_all()
    after = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    after_snapshot = (after.definition_hash, after.approval_id, after.is_active)
    assert after_snapshot == before_snapshot


# ---------------------------------------------------------------------------
# F: API / Audit.
# ---------------------------------------------------------------------------


def test_decision_package_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/v1/admin/strategies/1/decision-packages", json={"explainability_report_id": 1})
    assert resp.status_code == 401


def test_decision_package_api_full_flow(session) -> None:
    seed = _seed_ready_package_inputs(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages",
        json={"explainability_report_id": seed["explainability_report_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    package_id = resp.json()["package_id"]

    for suffix in ("", "/summary", "/checklist", "/staleness"):
        r = client.get(
            f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}{suffix}",
            headers={"X-Admin-API-Key": admin_key},
        )
        assert r.status_code == 200

    checklist_resp = client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}/checklist",
        headers={"X-Admin-API-Key": admin_key},
    )
    required_codes = [c["checklist_code"] for c in checklist_resp.json()["checklist_template"] if c["required"]]

    decision_resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}/decisions",
        json={
            "decision_type": "APPROVE_FOR_PROMOTION", "reason_code": "EVIDENCE_REVIEW_COMPLETED",
            "reason_text": "검토 완료", "checklist_confirmations": {c: True for c in required_codes},
            "acknowledged_warnings": ["ALL"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert decision_resp.status_code == 201
    assert decision_resp.json()["promotion_ready"] is True

    decision_get = client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}/decision",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert decision_get.status_code == 200

    readiness_resp = client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-readiness",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert readiness_resp.status_code == 200
    assert readiness_resp.json()["ready"] is True


def test_decision_package_api_cross_strategy_404(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    other_strategy_id = seed["strategy_id"] + 999999
    resp = client.get(
        f"/api/v1/admin/strategies/{other_strategy_id}/decision-packages/{package['package_id']}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


def test_decision_package_api_invalid_reason_code(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package['package_id']}/decisions",
        json={"decision_type": "REJECT", "reason_code": "NOT_A_REAL_CODE", "reason_text": "ok"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 400


def test_decision_package_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    seed = _seed_ready_package_inputs(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages",
        json={"explainability_report_id": seed["explainability_report_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    package_id = resp.json()["package_id"]
    client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}/staleness",
        headers={"X-Admin-API-Key": admin_key},
    )
    checklist_resp = client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}/checklist",
        headers={"X-Admin-API-Key": admin_key},
    )
    required_codes = [c["checklist_code"] for c in checklist_resp.json()["checklist_template"] if c["required"]]
    client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/decision-packages/{package_id}/decisions",
        json={
            "decision_type": "APPROVE_FOR_PROMOTION", "reason_code": "EVIDENCE_REVIEW_COMPLETED",
            "reason_text": "검토 완료", "checklist_confirmations": {c: True for c in required_codes},
            "acknowledged_warnings": ["ALL"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/promotion-readiness",
        headers={"X-Admin-API-Key": admin_key},
    )

    events = session.execute(
        select(AuditEvent.event_type)
        .where(
            AuditEvent.event_type.like("DECISION_PACKAGE_%")
            | AuditEvent.event_type.like("HUMAN_DECISION_%")
            | AuditEvent.event_type.like("PROMOTION_READINESS_%")
        )
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(20)
    ).all()
    event_types = {e[0] for e in events}
    assert "DECISION_PACKAGE_STARTED" in event_types
    assert "DECISION_PACKAGE_COMPLETED" in event_types
    assert "DECISION_PACKAGE_STALENESS_CHECKED" in event_types
    assert "HUMAN_DECISION_STARTED" in event_types
    assert "HUMAN_DECISION_APPROVED_FOR_PROMOTION" in event_types
    assert "PROMOTION_READINESS_VIEWED" in event_types


# ---------------------------------------------------------------------------
# G: Regression — STEP12-14/13/12/11/10.
# ---------------------------------------------------------------------------


def test_step12_14_explainability_regression(session) -> None:
    seed = _seed_ready_package_inputs(session)
    assert seed["explainability"]["completeness_status"] in {"COMPLETE", "SUBSTANTIAL", "PARTIAL", "INSUFFICIENT"}


def test_step12_10_quality_gate_regression(session) -> None:
    seed = _seed_ready_package_inputs(session)
    result = run_quality_gate(session, seed["strategy_id"], actor="STEP12_15_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}


# ---------------------------------------------------------------------------
# H: STEP12-15 필수 인수 보완(STEP12-16 착수 전 확인·수정).
# ---------------------------------------------------------------------------


def test_decision_meaning_and_promotion_committed_false_on_approve(session) -> None:
    """§1 — Decision만으로는 실제 Promotion이 아직 이뤄지지 않았음을
    명시해야 한다."""
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    decision = _approve_ready_package(session, seed, package)
    assert decision["decision_meaning"] == "PROMOTION_COMMIT_ALLOWED"
    assert decision["promotion_committed"] is False


def test_decision_meaning_for_request_changes_and_reject(session) -> None:
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    decision = run_record_human_decision(
        session, seed["strategy_id"], package["package_id"], decision_type="REJECT",
        reason_code="UNACCEPTABLE_RISK", reason_text="위험", actor="STEP12_15_TEST:reviewer",
    )
    assert decision["decision_meaning"] == "REJECTED_NOT_PROMOTABLE"
    assert decision["promotion_committed"] is False


def test_quality_gate_provenance_hash_deterministic_and_sensitive_to_source(session) -> None:
    """§2 — 동일 Report는 항상 동일 Hash, Source(Backtest Run 등)가
    다르면 다른 Hash가 나와야 한다."""
    from stock_platform.ai.strategy_draft_approval.quality_gate import (
        compute_quality_gate_provenance_hash,
    )
    from stock_platform.ai.strategy_draft_approval.quality_gate_entities import (
        StrategyQualityGateReportEntity,
    )

    seed = _seed_ready_package_inputs(session)
    report = session.get(StrategyQualityGateReportEntity, seed["quality_gate_report_id"])
    h1 = compute_quality_gate_provenance_hash(session, report)
    h2 = compute_quality_gate_provenance_hash(session, report)
    assert h1 == h2

    second_quality_gate = run_quality_gate(session, seed["strategy_id"], actor="STEP12_15_TEST:admin")
    second_report = session.get(StrategyQualityGateReportEntity, second_quality_gate["quality_gate_report_id"])
    h3 = compute_quality_gate_provenance_hash(session, second_report)
    # 다른 quality_gate_report_id + Rule 평가 시점 차이로 다른 Hash여야 한다.
    assert h1 != h3


def test_decision_package_reuses_quality_gate_provenance_hash_helper(session) -> None:
    """§2 — Decision Package의 Quality Gate 지문이 공용 Helper와 동일해야
    한다(중복 계산 없음)."""
    from stock_platform.ai.strategy_draft_approval.quality_gate import (
        compute_quality_gate_provenance_hash,
    )
    from stock_platform.ai.strategy_draft_approval.quality_gate_entities import (
        StrategyQualityGateReportEntity,
    )

    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    report = session.get(StrategyQualityGateReportEntity, seed["quality_gate_report_id"])
    expected_hash = compute_quality_gate_provenance_hash(session, report)
    assert package["selected_report_hashes"]["quality_gate"] == expected_hash


def test_package_status_field_aliases_match(session) -> None:
    """§3 — created_package_status/current_effective_status가 기존
    package_status/effective_package_status와 동일 값을 가리켜야 한다."""
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    assert package["created_package_status"] == package["package_status"]
    assert package["current_effective_status"] == package["effective_package_status"]
    assert package["created_package_status"] == "READY_FOR_REVIEW"


def test_stale_package_blocks_request_changes(session) -> None:
    """§4 — Stale이면 REQUEST_CHANGES도 차단돼야 한다(APPROVE뿐 아니라)."""
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    session.execute(
        text("UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    )
    session.commit()

    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"], decision_type="REQUEST_CHANGES",
            reason_code="PARAMETER_FRAGILITY", reason_text="재검토 필요", actor="STEP12_15_TEST:reviewer",
        )
    assert exc_info.value.code == "STALE_PACKAGE"


def test_stale_package_blocks_reject(session) -> None:
    """§4 — Stale이면 REJECT도 차단돼야 한다."""
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    session.execute(
        text("UPDATE ai.candidate_lifecycle SET lifecycle_status = 'REVOKED' WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    )
    session.commit()

    with pytest.raises(DecisionPackageError) as exc_info:
        run_record_human_decision(
            session, seed["strategy_id"], package["package_id"], decision_type="REJECT",
            reason_code="UNACCEPTABLE_RISK", reason_text="위험", actor="STEP12_15_TEST:reviewer",
        )
    assert exc_info.value.code == "STALE_PACKAGE"


def test_human_decision_immutable_across_repeated_reads(session) -> None:
    """§5 — Decision 생성 후 반복 조회해도 값이 완전히 동일해야 한다(경로
    상 UPDATE가 전혀 없음을 간접 확인)."""
    seed = _seed_ready_package_inputs(session)
    package = _create_ready_package(session, seed)
    _approve_ready_package(session, seed, package)

    first = get_human_decision(session, package["package_id"])
    second = get_human_decision(session, package["package_id"])
    assert first == second


def test_legacy_standalone_backtest_included_as_primary_candidate(session) -> None:
    """§6 — execution_purpose 마커가 없어도(legacy) Walk-Forward/Sensitivity
    저장소에 전혀 참조되지 않는 순수 Standalone Run은 대표 후보에서
    제외되지 않아야 한다."""
    from sqlalchemy.orm.attributes import flag_modified

    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        get_latest_primary_backtest_run_id,
    )
    from stock_platform.backtest.persistence_models import BacktestRunEntity

    seed = _seed_ready_package_inputs(session)
    run = session.get(BacktestRunEntity, seed["backtest_run_id"])
    params = dict(run.parameters or {})
    params.pop("execution_purpose", None)  # STEP12-15 이전 legacy 상태로 되돌림
    run.parameters = params
    flag_modified(run, "parameters")
    session.commit()

    latest = get_latest_primary_backtest_run_id(session, seed["strategy_id"])
    assert latest == seed["backtest_run_id"]


def test_legacy_walk_forward_window_run_excluded_even_without_marker(session) -> None:
    """§6 — Walk-Forward Window Run은 execution_purpose 마커를 지워도(legacy
    상태 재현) walk_forward_window_metric 역참조로 여전히 제외돼야 한다."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm.attributes import flag_modified

    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        get_latest_primary_backtest_run_id,
    )
    from stock_platform.ai.strategy_draft_approval.walk_forward import run_walk_forward
    from stock_platform.backtest.persistence_models import BacktestRunEntity
    from stock_platform.performance.walk_forward_entities import WalkForwardWindowMetricEntity

    seed = _seed_ready_package_inputs(session)
    run_walk_forward(
        session, seed["strategy_id"], start_date=date(2024, 1, 1), end_date=date(2024, 4, 30),
        train_days=45, test_days=45, scheme="ROLLING", symbol=_TEST_SYMBOL, exchange_code=_TEST_EXCHANGE,
        initial_capital=Decimal("1000000"), fee_ratio=Decimal("0.00015"), sell_tax_ratio=Decimal("0.0018"),
        slippage_ratio=Decimal("0"), actor="STEP12_15_TEST:admin",
    )

    from stock_platform.performance.entities import StrategyPerformanceRunEntity

    window_row = session.scalars(
        sa_select(WalkForwardWindowMetricEntity)
        .join(
            StrategyPerformanceRunEntity,
            StrategyPerformanceRunEntity.strategy_performance_run_id
            == WalkForwardWindowMetricEntity.strategy_performance_run_id,
        )
        .where(StrategyPerformanceRunEntity.strategy_id == seed["strategy_id"])
    ).first()
    window_run_id = window_row.parameter_payload["test_backtest_run_id"]
    window_run = session.get(BacktestRunEntity, window_run_id)
    params = dict(window_run.parameters or {})
    params.pop("execution_purpose", None)  # legacy 상태 재현
    window_run.parameters = params
    flag_modified(window_run, "parameters")
    session.commit()

    latest = get_latest_primary_backtest_run_id(session, seed["strategy_id"])
    assert latest != window_run_id
    assert latest == seed["backtest_run_id"]


def test_legacy_parameter_sensitivity_variation_excluded_even_without_marker(session) -> None:
    """§6 — Parameter Sensitivity Base/Variation Run도 legacy 상태에서
    parameter_sensitivity_report 역참조로 제외돼야 한다."""
    from sqlalchemy.orm.attributes import flag_modified

    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        get_latest_primary_backtest_run_id,
    )
    from stock_platform.backtest.persistence_models import BacktestRunEntity

    seed = _seed_ready_package_inputs(session)
    base_run_id = seed["backtest_run_id"]  # 이미 base로 재사용된 것은 아니므로 sensitivity가 새로 만든 base를 찾는다.
    from stock_platform.ai.strategy_draft_approval.parameter_sensitivity_entities import (
        ParameterSensitivityReportEntity,
    )

    report = session.get(ParameterSensitivityReportEntity, seed["parameter_sensitivity_report_id"])
    sensitivity_base_run_id = report.base_backtest_run_id
    run = session.get(BacktestRunEntity, sensitivity_base_run_id)
    params = dict(run.parameters or {})
    params.pop("execution_purpose", None)
    run.parameters = params
    flag_modified(run, "parameters")
    session.commit()

    latest = get_latest_primary_backtest_run_id(session, seed["strategy_id"])
    assert latest != sensitivity_base_run_id
    assert latest == base_run_id
