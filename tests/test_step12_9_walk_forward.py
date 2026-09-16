"""STEP 12-9 — 승인 Strategy Definition의 Walk-Forward Analysis.

기존 STEP12-7 run_definition_backtest()/STEP12-8 analyze_backtest_run()를
그대로 재사용하고, 기존 trading.strategy_performance_run(PerformanceRunType
.WALK_FORWARD)/trading.walk_forward_window_metric에 저장한다(신규 Table
없음). 새 BacktestEngine을 만들지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_draft_approval.walk_forward import (
    WalkForwardError,
    _consistency_score,
    _overfitting_grade,
    _window_overfitting_score,
    build_windows,
    get_overfitting_report,
    get_walk_forward_detail,
    run_walk_forward,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.performance.entities import StrategyPerformanceRunEntity

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_9_TEST"
_FINGERPRINT = "c9" * 32
_TEST_SYMBOL = "STEP129T"
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
    "DELETE FROM trading.walk_forward_window_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_9%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_9%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_9%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-9 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_9_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _triangle_wave(num_days: int, *, period: int = 30, low: float = 50.0, high: float = 100.0) -> list[float]:
    """상승/하락을 반복하는 삼각파 — 각 구간(train/test)마다 RSI가 과매도(<30)
    /과매수(>70) 영역을 모두 지나가도록 설계(Entry/Exit이 최소 한 번은
    발생할 수 있게)."""

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


def _default_wf_kwargs(**overrides) -> dict:
    base = {
        "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
        "train_days": 45, "test_days": 45, "scheme": "ROLLING",
        "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
        "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
        "actor": "STEP12_9_TEST:admin",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A: build_windows — Rolling / Expanding
# ---------------------------------------------------------------------------


def test_rolling_window_slides_train_start() -> None:
    windows = build_windows(
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30), train_days=45, test_days=45, scheme="ROLLING",
    )
    assert len(windows) == 2
    w1, w2 = windows
    assert w1.train_start_date == date(2024, 1, 1)
    assert w1.train_end_date == date(2024, 2, 14)
    assert w1.test_start_date == date(2024, 2, 15)
    assert w1.test_end_date == date(2024, 3, 30)
    # Rolling: train 크기(45일)는 유지된 채 train_start가 test_days(45)만큼 슬라이딩.
    assert w2.train_start_date == date(2024, 2, 15)
    assert (w2.train_end_date - w2.train_start_date).days == (w1.train_end_date - w1.train_start_date).days
    assert w2.test_end_date == date(2024, 4, 30)


def test_expanding_window_keeps_train_start_fixed() -> None:
    windows = build_windows(
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30), train_days=45, test_days=45, scheme="EXPANDING",
    )
    assert len(windows) == 2
    w1, w2 = windows
    assert w1.train_start_date == date(2024, 1, 1)
    assert w2.train_start_date == date(2024, 1, 1)  # 고정
    # Expanding: train 구간이 test_days만큼 더 늘어난다.
    assert (w2.train_end_date - w2.train_start_date).days > (w1.train_end_date - w1.train_start_date).days
    assert w2.train_end_date == w1.test_end_date


def test_build_windows_rejects_invalid_range() -> None:
    with pytest.raises(WalkForwardError) as exc_info:
        build_windows(start_date=date(2024, 1, 1), end_date=date(2024, 1, 1), train_days=10, test_days=10, scheme="ROLLING")
    assert exc_info.value.code == "INVALID_WINDOW"


def test_build_windows_rejects_period_shorter_than_train_plus_test() -> None:
    with pytest.raises(WalkForwardError) as exc_info:
        build_windows(start_date=date(2024, 1, 1), end_date=date(2024, 1, 10), train_days=30, test_days=30, scheme="ROLLING")
    assert exc_info.value.code == "INVALID_WINDOW"


def test_build_windows_rejects_unknown_scheme() -> None:
    with pytest.raises(WalkForwardError) as exc_info:
        build_windows(start_date=date(2024, 1, 1), end_date=date(2024, 4, 1), train_days=30, test_days=30, scheme="RANDOM")
    assert exc_info.value.code == "INVALID_WINDOW_SCHEME"


# ---------------------------------------------------------------------------
# B: Overfitting / Consistency 순수 함수 — 실제 계산값 검증
# ---------------------------------------------------------------------------


def test_window_overfitting_score_no_degradation() -> None:
    assert _window_overfitting_score(Decimal("10"), Decimal("10")) == Decimal("0")


def test_window_overfitting_score_full_degradation() -> None:
    # (10-0)/10*100 = 100
    assert _window_overfitting_score(Decimal("10"), Decimal("0")) == Decimal("100")


def test_window_overfitting_score_partial_degradation() -> None:
    # (10-5)/10*100 = 50
    assert _window_overfitting_score(Decimal("10"), Decimal("5")) == Decimal("50")


def test_window_overfitting_score_negative_in_sample_edge_case() -> None:
    # in_return<=0인 비정상 케이스: out이 더 나쁘면 100, 개선되면 0.
    assert _window_overfitting_score(Decimal("-5"), Decimal("-10")) == Decimal("100")
    assert _window_overfitting_score(Decimal("-5"), Decimal("0")) == Decimal("0")


def test_overfitting_grade_boundaries() -> None:
    assert _overfitting_grade(Decimal("66")) == "HIGH"
    assert _overfitting_grade(Decimal("65.99")) == "MEDIUM"
    assert _overfitting_grade(Decimal("33")) == "MEDIUM"
    assert _overfitting_grade(Decimal("32.99")) == "LOW"


def test_consistency_score_identical_returns_is_perfect() -> None:
    score = _consistency_score([Decimal("10"), Decimal("10"), Decimal("10")])
    assert score == Decimal("100")


def test_consistency_score_volatile_returns_is_lower() -> None:
    stable = _consistency_score([Decimal("10"), Decimal("10"), Decimal("10")])
    volatile = _consistency_score([Decimal("50"), Decimal("-40"), Decimal("60"), Decimal("-30")])
    assert volatile < stable


# ---------------------------------------------------------------------------
# C: run_walk_forward 종단 간(합성 데이터)
# ---------------------------------------------------------------------------


def test_run_walk_forward_rolling_success(session) -> None:
    approval = _seed_and_approve(session)
    result = run_walk_forward(session, approval["strategy_definition_id"], **_default_wf_kwargs())
    assert result["window_count"] == 2
    assert result["completed_window_count"] == 2
    assert result["failed_window_count"] == 0
    assert result["overfitting_grade"] in {"LOW", "MEDIUM", "HIGH"}
    assert len(result["windows"]) == 2


def test_run_walk_forward_expanding_success(session) -> None:
    approval = _seed_and_approve(session)
    result = run_walk_forward(
        session, approval["strategy_definition_id"], **_default_wf_kwargs(scheme="EXPANDING")
    )
    assert result["window_count"] == 2
    assert result["completed_window_count"] == 2


def test_run_walk_forward_persists_run_and_windows(session) -> None:
    approval = _seed_and_approve(session)
    result = run_walk_forward(session, approval["strategy_definition_id"], **_default_wf_kwargs())

    run = session.get(StrategyPerformanceRunEntity, result["strategy_performance_run_id"])
    assert run is not None
    assert run.status_code == "COMPLETED"
    assert run.strategy_id == approval["strategy_definition_id"]

    windows = session.execute(
        text(
            "SELECT window_no FROM trading.walk_forward_window_metric "
            "WHERE strategy_performance_run_id = :rid ORDER BY window_no"
        ),
        {"rid": result["strategy_performance_run_id"]},
    ).fetchall()
    assert len(windows) == 2
    assert [w[0] for w in windows] == [1, 2]


def test_run_walk_forward_deterministic(session) -> None:
    approval = _seed_and_approve(session)
    r1 = run_walk_forward(session, approval["strategy_definition_id"], **_default_wf_kwargs())
    r2 = run_walk_forward(session, approval["strategy_definition_id"], **_default_wf_kwargs())
    assert r1["forward_performance"] == r2["forward_performance"]
    assert r1["overfitting_score"] == r2["overfitting_score"]
    assert r1["stability"]["stability_score"] == r2["stability"]["stability_score"]


def test_run_walk_forward_blocks_when_not_ready(session) -> None:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        BacktestExecutionError,
    )

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_manual_draft_kwargs()
    )
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")
    with pytest.raises(BacktestExecutionError):
        run_walk_forward(
            session, approval["strategy_definition_id"], **_default_wf_kwargs()
        )


def test_get_walk_forward_detail_not_found(session) -> None:
    with pytest.raises(WalkForwardError) as exc_info:
        get_walk_forward_detail(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


def test_get_overfitting_report_contains_per_window(session) -> None:
    approval = _seed_and_approve(session)
    result = run_walk_forward(session, approval["strategy_definition_id"], **_default_wf_kwargs())
    report = get_overfitting_report(session, result["strategy_performance_run_id"])
    assert report["overfitting_grade"] in {"LOW", "MEDIUM", "HIGH"}
    assert len(report["per_window"]) == 2
    assert "in_sample" in report["per_window"][0]
    assert "out_of_sample" in report["per_window"][0]


# ---------------------------------------------------------------------------
# D: API / Auth / Audit
# ---------------------------------------------------------------------------


def test_walk_forward_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategies/1/walk-forward",
        json={
            "symbol": "X", "exchange_code": "KRX", "start_date": "2024-01-01", "end_date": "2024-04-30",
            "train_days": 45, "test_days": 45, "initial_capital": "1000000",
        },
    )
    assert resp.status_code == 401


def test_walk_forward_api_success_and_detail(session) -> None:
    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/walk-forward",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "train_days": 45, "test_days": 45, "window_scheme": "ROLLING",
            "initial_capital": "1000000",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    body = resp.json()
    run_id = body["strategy_performance_run_id"]

    detail_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/walk-forward/{run_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["windows"]) == 2

    overfitting_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/walk-forward/{run_id}/overfitting",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert overfitting_resp.status_code == 200
    assert overfitting_resp.json()["overfitting_grade"] in {"LOW", "MEDIUM", "HIGH"}


def test_walk_forward_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/walk-forward",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "train_days": 45, "test_days": 45, "initial_capital": "1000000",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    run_id = resp.json()["strategy_performance_run_id"]
    client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/walk-forward/{run_id}/overfitting",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.strategy_id == str(approval["strategy_definition_id"]))
        .where(
            AuditEvent.event_type.in_(
                ["WALK_FORWARD_STARTED", "WALK_FORWARD_COMPLETED", "OVERFITTING_ANALYZED"]
            )
        )
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    event_types = {e[0] for e in events}
    assert "WALK_FORWARD_STARTED" in event_types
    assert "WALK_FORWARD_COMPLETED" in event_types
    assert "OVERFITTING_ANALYZED" in event_types


# ---------------------------------------------------------------------------
# E: STEP12-8 회귀
# ---------------------------------------------------------------------------


def test_step12_8_analyze_backtest_run_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )
    from stock_platform.performance.backtest_analytics import analyze_backtest_run

    approval = _seed_and_approve(session)
    result = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": date(2024, 1, 1), "end_date": date(2024, 2, 20),
            "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
            "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
        },
        actor="STEP12_9_TEST:admin",
    )
    analysis = analyze_backtest_run(session, result["backtest_run_id"])
    assert analysis["score"]["grade"] is not None or analysis["score"]["score"] is None
