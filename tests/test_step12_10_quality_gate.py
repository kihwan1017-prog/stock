"""STEP 12-10 — Strategy Quality Gate.

기존 STEP12-7 Backtest 결과/STEP12-8 Performance Analytics/STEP12-9
Walk-Forward 결과만 재사용해 Rule 기반 자동 품질 심사를 수행한다. 새
Backtest/Walk-Forward를 실행하지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.quality_gate import (
    QualityGateError,
    QualityGateThresholds,
    determine_recommendation,
    determine_risk_grade,
    evaluate_rules,
    get_quality_report,
    get_recommendation,
    run_quality_gate,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_draft_approval.walk_forward import run_walk_forward
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_10_TEST"
_FINGERPRINT = "d0" * 32
_TEST_SYMBOL = "STEP1210T"
_TEST_EXCHANGE = "KRX"

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
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 1")
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    "DELETE FROM trading.strategy_quality_gate_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.walk_forward_window_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_10%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_10%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_10%'",
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
    "(SELECT instrument_id FROM market.instrument WHERE symbol = :test_symbol)",
    "DELETE FROM market.instrument WHERE symbol = :test_symbol",
]


def _cleanup(s) -> None:
    for sql in _CLEANUP_SQL:
        s.execute(text(sql), {"marker": _MARKER, "test_symbol": _TEST_SYMBOL})
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


def _seed_prices(session, closes: list[float], *, start: date) -> None:
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-10 Test')
            RETURNING instrument_id
            """
        ),
        {"exchange": _TEST_EXCHANGE, "symbol": _TEST_SYMBOL},
    ).scalar_one()
    for i, close in enumerate(closes):
        trade_date = start + timedelta(days=i)
        session.execute(
            text(
                """
                INSERT INTO market.price_daily
                (instrument_id, trade_date, open_price, high_price, low_price, close_price, volume, source)
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_10_TEST')
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
        {"cid": result_id, "fp": _FINGERPRINT, "marker": _MARKER},
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


def _manual_draft_kwargs(**overrides) -> dict:
    base = {
        "actor": "admin:7", "title": "수동 초안", "timeframe": "1D", "market_type": "KR_STOCK",
        "entry_rule": _VALID_ENTRY, "exit_rule": _VALID_EXIT, "stop_loss_rule": _VALID_STOP_LOSS,
        "take_profit_rule": _VALID_TAKE_PROFIT, "position_sizing_rule": _VALID_POSITION_SIZING,
    }
    base.update(overrides)
    return base


def _approve(session, strategy_request_id: int, **draft_overrides) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, **_manual_draft_kwargs(**draft_overrides)
    )
    return StrategyDraftApprovalService(session).approve(draft["draft_id"], actor="admin:7", reason="승인")


def _seed_and_approve(session) -> dict:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = _triangle_wave(140, period=30)
    _seed_prices(session, closes, start=date(2024, 1, 1))
    return approval


def _run_backtest(session, strategy_definition_id: int) -> dict:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    return run_definition_backtest(
        session, strategy_definition_id,
        runtime_input={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
            "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
            "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
        },
        actor="STEP12_10_TEST:admin",
    )


# ---------------------------------------------------------------------------
# A: evaluate_rules — 실제 계산값 검증
# ---------------------------------------------------------------------------


def test_evaluate_rules_all_pass() -> None:
    thresholds = QualityGateThresholds()
    rules = evaluate_rules(
        trade_count=20, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("10"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=thresholds,
    )
    assert all(r.status == "PASS" for r in rules)
    assert len(rules) == 6


def test_evaluate_rules_trade_count_fail_vs_warning() -> None:
    thresholds = QualityGateThresholds()
    rules_fail = evaluate_rules(
        trade_count=2, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("10"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=thresholds,
    )
    trade_rule = next(r for r in rules_fail if r.rule_name == "MINIMUM_TRADE_COUNT")
    assert trade_rule.status == "FAIL"

    rules_warn = evaluate_rules(
        trade_count=10, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("10"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=thresholds,
    )
    trade_rule_warn = next(r for r in rules_warn if r.rule_name == "MINIMUM_TRADE_COUNT")
    assert trade_rule_warn.status == "WARNING"


def test_evaluate_rules_max_drawdown_boundaries() -> None:
    thresholds = QualityGateThresholds()
    rules = evaluate_rules(
        trade_count=20, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("50"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=thresholds,
    )
    dd_rule = next(r for r in rules if r.rule_name == "MAXIMUM_DRAWDOWN")
    assert dd_rule.status == "FAIL"
    assert "50%" in dd_rule.failure_reason


def test_evaluate_rules_missing_data_is_warning_not_pass() -> None:
    thresholds = QualityGateThresholds()
    rules = evaluate_rules(
        trade_count=20, sharpe_ratio=None, maximum_drawdown_rate=Decimal("10"),
        profit_factor=None, stability_score=None, overfitting_score=None,
        thresholds=thresholds,
    )
    for name in ("MINIMUM_SHARPE_RATIO", "MINIMUM_PROFIT_FACTOR", "MINIMUM_STABILITY_SCORE", "MAXIMUM_OVERFITTING_SCORE"):
        rule = next(r for r in rules if r.rule_name == name)
        assert rule.status == "WARNING"
        assert rule.actual_value is None


# ---------------------------------------------------------------------------
# B: Recommendation / Risk Grade
# ---------------------------------------------------------------------------


def test_recommendation_approve_when_all_pass() -> None:
    rules = evaluate_rules(
        trade_count=20, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("10"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=QualityGateThresholds(),
    )
    assert determine_recommendation(rules) == "APPROVE"
    grade, reason = determine_risk_grade(rules)
    assert grade == "SAFE"
    assert reason["fail_count"] == 0


def test_recommendation_manual_review_on_warning() -> None:
    rules = evaluate_rules(
        trade_count=10, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("10"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=QualityGateThresholds(),
    )
    assert determine_recommendation(rules) == "MANUAL_REVIEW"
    grade, _ = determine_risk_grade(rules)
    assert grade == "CAUTION"


def test_recommendation_reject_on_fail() -> None:
    rules = evaluate_rules(
        trade_count=1, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("10"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=QualityGateThresholds(),
    )
    assert determine_recommendation(rules) == "REJECT"
    grade, reason = determine_risk_grade(rules)
    assert grade == "DANGER"
    assert reason["fail_count"] == 1


def test_risk_grade_normal_when_pass_but_not_comfortable() -> None:
    # 전부 PASS이나 MDD(24%)가 SAFE 기준(<=15%)을 넘어 NORMAL이어야 한다.
    rules = evaluate_rules(
        trade_count=20, sharpe_ratio=Decimal("1.0"), maximum_drawdown_rate=Decimal("24"),
        profit_factor=Decimal("2.0"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=QualityGateThresholds(),
    )
    assert all(r.status == "PASS" for r in rules)
    grade, _ = determine_risk_grade(rules)
    assert grade == "NORMAL"


def test_risk_grade_danger_on_many_warnings() -> None:
    rules = evaluate_rules(
        trade_count=10, sharpe_ratio=Decimal("0.2"), maximum_drawdown_rate=Decimal("30"),
        profit_factor=Decimal("1.1"), stability_score=Decimal("0.1"), overfitting_score=Decimal("20"),
        thresholds=QualityGateThresholds(),
    )
    warning_count = sum(1 for r in rules if r.status == "WARNING")
    assert warning_count >= 3
    grade, _ = determine_risk_grade(rules)
    assert grade == "DANGER"


# ---------------------------------------------------------------------------
# C: run_quality_gate 종단 간
# ---------------------------------------------------------------------------


def test_run_quality_gate_without_backtest_blocks(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    with pytest.raises(QualityGateError) as exc_info:
        run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_10_TEST:admin")
    assert exc_info.value.code == "NO_BACKTEST_AVAILABLE"


def test_run_quality_gate_with_backtest_only(session) -> None:
    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_10_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}
    assert result["risk_grade"] in {"SAFE", "NORMAL", "CAUTION", "DANGER"}
    assert result["walk_forward_run_id"] is None
    stability_rule = next(r for r in result["rules"] if r["rule_name"] == "MINIMUM_STABILITY_SCORE")
    assert stability_rule["status"] == "WARNING"  # Walk-Forward 미실행 -> 데이터 없음


def test_run_quality_gate_with_walk_forward(session) -> None:
    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    wf_result = run_walk_forward(
        session, approval["strategy_definition_id"],
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30),
        train_days=45, test_days=45, scheme="ROLLING",
        symbol=_TEST_SYMBOL, exchange_code=_TEST_EXCHANGE,
        initial_capital=Decimal("1000000"), fee_ratio=Decimal("0.00015"),
        sell_tax_ratio=Decimal("0.0018"), slippage_ratio=Decimal("0"),
        actor="STEP12_10_TEST:admin",
    )
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_10_TEST:admin")
    assert result["walk_forward_run_id"] == wf_result["strategy_performance_run_id"]
    stability_rule = next(r for r in result["rules"] if r["rule_name"] == "MINIMUM_STABILITY_SCORE")
    assert stability_rule["actual_value"] is not None


def test_get_quality_report_and_recommendation(session) -> None:
    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_10_TEST:admin")
    fetched = get_quality_report(session, result["quality_gate_report_id"])
    assert fetched["recommendation"] == result["recommendation"]
    recommendation = get_recommendation(session, result["quality_gate_report_id"])
    assert recommendation["risk_grade"] == result["risk_grade"]
    assert "recommendation" in recommendation


def test_get_quality_report_not_found(session) -> None:
    with pytest.raises(QualityGateError) as exc_info:
        get_quality_report(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


def test_get_quality_report_rejects_cross_strategy_access(session) -> None:
    """STEP12-11 인수 조건 §4에서 발견된 수정 — report_id만으로 조회할 때
    URL의 strategy_id와 실제 소유 Strategy가 다르면 차단해야 한다."""
    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_10_TEST:admin")
    other_strategy_id = approval["strategy_definition_id"] + 999_999
    with pytest.raises(QualityGateError) as exc_info:
        get_quality_report(
            session, result["quality_gate_report_id"], strategy_definition_id=other_strategy_id
        )
    assert exc_info.value.code == "NOT_FOUND"
    # 올바른 strategy_id를 주면 정상 조회된다.
    fetched = get_quality_report(
        session, result["quality_gate_report_id"],
        strategy_definition_id=approval["strategy_definition_id"],
    )
    assert fetched["quality_gate_report_id"] == result["quality_gate_report_id"]


def test_run_quality_gate_persists_report(session) -> None:
    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_10_TEST:admin")
    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_quality_gate_report WHERE quality_gate_report_id = :rid"
        ),
        {"rid": result["quality_gate_report_id"]},
    ).scalar_one()
    assert count == 1


# ---------------------------------------------------------------------------
# D: API / Auth / Audit
# ---------------------------------------------------------------------------


def test_quality_gate_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/v1/admin/strategies/1/quality-gate").status_code == 401
    assert client.get("/api/v1/admin/strategies/1/quality-gate/1").status_code == 401


def test_quality_gate_api_success_and_get(session) -> None:
    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/quality-gate",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    report_id = resp.json()["quality_gate_report_id"]

    get_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/quality-gate/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert get_resp.status_code == 200

    rec_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/quality-gate/{report_id}/recommendation",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert rec_resp.status_code == 200
    assert rec_resp.json()["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}


def test_quality_gate_api_no_backtest_returns_400(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/quality-gate",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 400


def test_quality_gate_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    approval = _seed_and_approve(session)
    _run_backtest(session, approval["strategy_definition_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/quality-gate",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.strategy_id == str(approval["strategy_definition_id"]))
        .where(AuditEvent.event_type.in_(["QUALITY_GATE_STARTED", "QUALITY_GATE_COMPLETED"]))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(5)
    ).all()
    event_types = {e[0] for e in events}
    assert "QUALITY_GATE_STARTED" in event_types
    assert "QUALITY_GATE_COMPLETED" in event_types


# ---------------------------------------------------------------------------
# E: STEP12-9 회귀
# ---------------------------------------------------------------------------


def test_step12_9_walk_forward_regression(session) -> None:
    approval = _seed_and_approve(session)
    result = run_walk_forward(
        session, approval["strategy_definition_id"],
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30),
        train_days=45, test_days=45, scheme="ROLLING",
        symbol=_TEST_SYMBOL, exchange_code=_TEST_EXCHANGE,
        initial_capital=Decimal("1000000"), fee_ratio=Decimal("0.00015"),
        sell_tax_ratio=Decimal("0.0018"), slippage_ratio=Decimal("0"),
        actor="STEP12_10_TEST:admin",
    )
    assert result["completed_window_count"] == 2
