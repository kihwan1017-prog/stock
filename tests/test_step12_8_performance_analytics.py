"""STEP 12-8 — Backtest 결과 기반 Performance Analytics Layer.

기존 `backtest.backtest_run`(+trade/equity, STEP12-6/12-7가 이미 저장한
구조)만 읽어 KPI/Strategy Score/Grade를 계산한다(새 Entity/Table/Migration
없음 — 계산 결과는 기존 `parameters` JSONB 컬럼에 병합 저장). 기존
BacktestEngine/BacktestResult는 전혀 수정하지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.api.main import app
from stock_platform.backtest.models import (
    BacktestPrice,
    BacktestResult,
    BacktestSummary,
    BacktestTrade,
)
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.performance.backtest_analytics import (
    PerformanceAnalyticsError,
    analyze_backtest_run,
    compute_kpi,
    compute_strategy_score,
)

pytestmark = pytest.mark.integration

_MARKER = "STEP12_8_TEST"


def _synthetic_result() -> BacktestResult:
    """손으로 검증 가능한 합성 결과 — 초기자본 1000, 최종자본 1200
    (총수익률 20%), 기간 정확히 365일(2023-01-01~2024-01-01)이라
    CAGR도 정확히 20%가 되도록 설계했다. 거래 4건(승2/패2)."""

    equity_curve = [
        (date(2023, 1, 1), Decimal("1000")),
        (date(2023, 2, 1), Decimal("1200")),
        (date(2023, 6, 1), Decimal("900")),
        (date(2023, 9, 1), Decimal("1350")),
        (date(2023, 12, 1), Decimal("1080")),
        (date(2024, 1, 1), Decimal("1200")),
    ]
    trades = [
        BacktestTrade(
            entry_date=date(2023, 1, 5), exit_date=date(2023, 1, 10),
            quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("110"),
            gross_profit_loss=Decimal("100"), fee_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_profit_loss=Decimal("100"), return_rate=Decimal("10"),
            entry_reason="RULE_ENTRY", exit_reason="RULE_EXIT",
        ),
        BacktestTrade(
            entry_date=date(2023, 1, 15), exit_date=date(2023, 1, 20),
            quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("105"),
            gross_profit_loss=Decimal("50"), fee_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_profit_loss=Decimal("50"), return_rate=Decimal("5"),
            entry_reason="RULE_ENTRY", exit_reason="RULE_EXIT",
        ),
        BacktestTrade(
            entry_date=date(2023, 2, 1), exit_date=date(2023, 2, 5),
            quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("92"),
            gross_profit_loss=Decimal("-80"), fee_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_profit_loss=Decimal("-80"), return_rate=Decimal("-8"),
            entry_reason="RULE_ENTRY", exit_reason="STOP_LOSS",
        ),
        BacktestTrade(
            entry_date=date(2023, 2, 10), exit_date=date(2023, 2, 15),
            quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("98"),
            gross_profit_loss=Decimal("-20"), fee_amount=Decimal("0"), tax_amount=Decimal("0"),
            net_profit_loss=Decimal("-20"), return_rate=Decimal("-2"),
            entry_reason="RULE_ENTRY", exit_reason="STOP_LOSS",
        ),
    ]
    summary = BacktestSummary(
        initial_capital=Decimal("1000"),
        final_equity=Decimal("1200"),
        total_return_rate=Decimal("20.0000"),
        maximum_drawdown_rate=Decimal("25.0000"),
        trade_count=4,
        win_count=2,
        loss_count=2,
        win_rate=Decimal("50.0000"),
        total_profit_loss=Decimal("200"),
        average_trade_return_rate=Decimal("1.25"),
    )
    return BacktestResult(
        exchange_code="KRX",
        symbol="STEP128T",
        start_date=date(2023, 1, 1),
        end_date=date(2024, 1, 1),
        summary=summary,
        trades=trades,
        equity_curve=equity_curve,
    )


_CLEANUP_SQL = [
    "DELETE FROM backtest.backtest_trade WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_code = :marker)",
    "DELETE FROM backtest.backtest_equity WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_code = :marker)",
    "DELETE FROM backtest.backtest_run WHERE strategy_code = :marker",
]


def _cleanup(s) -> None:
    for sql in _CLEANUP_SQL:
        s.execute(text(sql), {"marker": _MARKER})
    s.commit()


@pytest.fixture()
def session():
    Session = get_session_factory()
    s = Session()
    try:
        _cleanup(s)
        yield s
    finally:
        s.rollback()
        _cleanup(s)
        s.close()


def _seed_run(session) -> int:
    repo = BacktestRepository(session)
    run = repo.save_result(
        result=_synthetic_result(),
        strategy_code=_MARKER,
        parameters={"seed": "step12_8"},
    )
    return int(run.backtest_run_id)


# ---------------------------------------------------------------------------
# KPI 계산 — 실제 기대값과 정확히 비교(Boolean만이 아니라)
# ---------------------------------------------------------------------------


def test_kpi_total_return_and_cagr(session) -> None:
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    run = repo.get_run(run_id)
    kpi = compute_kpi(run=run, trades=repo.get_trades(run_id), equity_curve=repo.get_equity_curve(run_id))
    assert kpi["total_return_rate"] == Decimal("20.0000")
    # 기간이 정확히 365일이므로 CAGR == 총수익률(20%)이어야 한다.
    assert kpi["cagr"] == Decimal("20.0000")


def test_kpi_sharpe_sortino_ulcer_exact(session) -> None:
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    run = repo.get_run(run_id)
    kpi = compute_kpi(run=run, trades=repo.get_trades(run_id), equity_curve=repo.get_equity_curve(run_id))
    assert kpi["sharpe_ratio"] == Decimal("4.1655")
    assert kpi["sortino_ratio"] == Decimal("45.8597")
    assert kpi["ulcer_index"] == Decimal("13.8351")


def test_kpi_drawdown_and_recovery_and_calmar(session) -> None:
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    run = repo.get_run(run_id)
    kpi = compute_kpi(run=run, trades=repo.get_trades(run_id), equity_curve=repo.get_equity_curve(run_id))
    assert kpi["maximum_drawdown_rate"] == Decimal("25.0000")
    assert kpi["maximum_drawdown_amount"] == Decimal("300.00")
    # recovery_factor = net_profit(200) / max_drawdown_amount(300)
    assert kpi["recovery_factor"] == Decimal("0.6667")
    # calmar = cagr(20) / mdd(25)
    assert kpi["calmar_ratio"] == Decimal("0.8000")


def test_kpi_trade_statistics(session) -> None:
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    run = repo.get_run(run_id)
    kpi = compute_kpi(run=run, trades=repo.get_trades(run_id), equity_curve=repo.get_equity_curve(run_id))
    assert kpi["trade_count"] == 4
    assert kpi["long_trade_count"] == 4
    assert kpi["short_trade_count"] == 0
    assert kpi["winning_trade_count"] == 2
    assert kpi["losing_trade_count"] == 2
    assert kpi["win_rate"] == Decimal("50.0000")
    assert kpi["average_win"] == Decimal("75.00")
    assert kpi["average_loss"] == Decimal("-50.00")
    assert kpi["profit_factor"] == Decimal("1.5000")
    assert kpi["expectancy"] == Decimal("12.50")
    assert kpi["average_holding_days"] == Decimal("4.75")
    # 순서: 승,승,패,패 -> 연속 승 2, 연속 패 2
    assert kpi["consecutive_wins"] == 2
    assert kpi["consecutive_losses"] == 2


def test_kpi_monthly_and_yearly_return(session) -> None:
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    run = repo.get_run(run_id)
    kpi = compute_kpi(run=run, trades=repo.get_trades(run_id), equity_curve=repo.get_equity_curve(run_id))
    monthly = {m["period"]: m["return_rate"] for m in kpi["monthly_return"]}
    assert monthly["2023-01"] == Decimal("0")
    assert monthly["2023-02"] == Decimal("20.0000")
    assert monthly["2023-06"] == Decimal("-25.0000")
    assert monthly["2023-09"] == Decimal("50.0000")
    assert monthly["2023-12"] == Decimal("-20.0000")
    assert monthly["2024-01"] == Decimal("11.1111")

    yearly = {y["period"]: y["return_rate"] for y in kpi["yearly_return"]}
    assert yearly["2023"] == Decimal("8.0000")
    assert yearly["2024"] == Decimal("11.1111")
    assert kpi["annual_return"] == Decimal("9.5556")


def test_kpi_equity_and_drawdown_curve_length_and_no_lookahead(session) -> None:
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    run = repo.get_run(run_id)
    equity_curve = repo.get_equity_curve(run_id)
    kpi = compute_kpi(run=run, trades=repo.get_trades(run_id), equity_curve=equity_curve)
    assert len(kpi["equity_curve"]) == 6
    assert len(kpi["drawdown_curve"]) == 6
    # 3번째 지점(index2, 2023-06-01)까지의 drawdown은 이후 지점(더 높은 신고점인
    # 1350)의 영향을 받지 않고 그 시점까지의 peak(1200) 기준으로만 계산돼야
    # 한다 — Look-ahead 없음.
    assert kpi["drawdown_curve"][2]["drawdown_rate"] == Decimal("25.00")


# ---------------------------------------------------------------------------
# Insufficient data / 예외 상황
# ---------------------------------------------------------------------------


def test_kpi_insufficient_data_returns_none_not_zero(session) -> None:
    """거래가 하나도 없으면 profit_factor/expectancy 등은 0이 아니라
    None(계산 불가)이어야 한다 — 임의 기본값으로 대체 금지."""
    from stock_platform.backtest.models import BacktestPrice  # noqa: F401 (문서화용)

    repo = BacktestRepository(session)
    result = BacktestResult(
        exchange_code="KRX",
        symbol="STEP128T2",
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 2),
        summary=BacktestSummary(
            initial_capital=Decimal("1000"),
            final_equity=Decimal("1000"),
            total_return_rate=Decimal("0"),
            maximum_drawdown_rate=Decimal("0"),
            trade_count=0,
            win_count=0,
            loss_count=0,
            win_rate=Decimal("0"),
            total_profit_loss=Decimal("0"),
            average_trade_return_rate=Decimal("0"),
        ),
        trades=[],
        equity_curve=[
            (date(2023, 1, 1), Decimal("1000")),
            (date(2023, 1, 2), Decimal("1000")),
        ],
    )
    run = repo.save_result(result=result, strategy_code=_MARKER, parameters={})
    kpi = compute_kpi(run=run, trades=[], equity_curve=repo.get_equity_curve(run.backtest_run_id))
    assert kpi["profit_factor"] is None
    assert kpi["expectancy"] is None
    assert kpi["recovery_factor"] is None
    assert kpi["trade_count"] == 0


# ---------------------------------------------------------------------------
# Strategy Score / Grade
# ---------------------------------------------------------------------------


def test_score_high_quality_metrics_grades_well() -> None:
    kpi = {
        "sharpe_ratio": Decimal("2.0"),
        "maximum_drawdown_rate": Decimal("5"),
        "profit_factor": Decimal("3.0"),
        "win_rate": Decimal("70"),
        "calmar_ratio": Decimal("3.0"),
        "expectancy": Decimal("10"),
    }
    result = compute_strategy_score(kpi)
    # 가중 평균: sharpe(25*100)+mdd(20*90)+pf(20*100)+win_rate(15*70)
    #           +calmar(10*100)+expectancy(10*100) 전부 /100 = 93.50
    # (mdd=5%는 100-5*2=90점, win_rate=70은 70점으로 그대로 반영되어
    # 100점 만점이 아님 — 각 컴포넌트 공식이 실제로 반영된 값인지 확인).
    assert result["score"] == Decimal("93.50")
    assert result["grade"] == "A+"


def test_score_poor_metrics_grades_f() -> None:
    kpi = {
        "sharpe_ratio": Decimal("-1.0"),
        "maximum_drawdown_rate": Decimal("60"),
        "profit_factor": Decimal("0"),
        "win_rate": Decimal("10"),
        "calmar_ratio": Decimal("0"),
        "expectancy": Decimal("-5"),
    }
    result = compute_strategy_score(kpi)
    assert result["score"] < Decimal("35")
    assert result["grade"] == "F"


def test_score_missing_components_renormalizes_weights() -> None:
    kpi = {
        "sharpe_ratio": None,
        "maximum_drawdown_rate": None,
        "profit_factor": None,
        "win_rate": Decimal("50"),
        "calmar_ratio": None,
        "expectancy": None,
    }
    result = compute_strategy_score(kpi)
    # win_rate만 있으므로 그 컴포넌트 점수(50)가 그대로 최종 Score가 된다.
    assert result["score"] == Decimal("50.00")
    breakdown_names = {b["name"]: b["included"] for b in result["breakdown"]}
    assert breakdown_names["win_rate"] is True
    assert breakdown_names["sharpe_ratio"] is False


def test_score_all_missing_returns_none_not_default() -> None:
    result = compute_strategy_score(
        {
            "sharpe_ratio": None, "maximum_drawdown_rate": None, "profit_factor": None,
            "win_rate": None, "calmar_ratio": None, "expectancy": None,
        }
    )
    assert result["score"] is None
    assert result["grade"] is None
    assert result["reason"] == "insufficient_data"


def test_grade_boundaries() -> None:
    from stock_platform.performance.backtest_analytics import _grade_for_score

    assert _grade_for_score(Decimal("90")) == "A+"
    assert _grade_for_score(Decimal("89.99")) == "A"
    assert _grade_for_score(Decimal("80")) == "A"
    assert _grade_for_score(Decimal("65")) == "B"
    assert _grade_for_score(Decimal("50")) == "C"
    assert _grade_for_score(Decimal("35")) == "D"
    assert _grade_for_score(Decimal("34.99")) == "F"


# ---------------------------------------------------------------------------
# analyze_backtest_run — 저장(§ parameters 병합) + not-found
# ---------------------------------------------------------------------------


def test_analyze_backtest_run_persists_into_parameters(session) -> None:
    run_id = _seed_run(session)
    result = analyze_backtest_run(session, run_id)
    assert result["kpi"]["total_return_rate"] == Decimal("20.0000")
    assert result["score"]["grade"] is not None

    repo = BacktestRepository(session)
    session.expire_all()
    run = repo.get_run(run_id)
    assert "performance_analytics" in run.parameters
    assert run.parameters["performance_analytics"]["score"]["grade"] == result["score"]["grade"]


def test_analyze_backtest_run_deterministic_repeat(session) -> None:
    run_id = _seed_run(session)
    r1 = analyze_backtest_run(session, run_id)
    r2 = analyze_backtest_run(session, run_id)
    assert r1["kpi"]["sharpe_ratio"] == r2["kpi"]["sharpe_ratio"]
    assert r1["score"]["score"] == r2["score"]["score"]


def test_analyze_backtest_run_not_found(session) -> None:
    with pytest.raises(PerformanceAnalyticsError) as exc_info:
        analyze_backtest_run(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


def test_analyze_does_not_touch_backtest_engine_summary_fields(session) -> None:
    """Definition 불변성과 유사하게, 분석은 기존 Backtest 요약 필드(엔진이
    이미 계산한 값)를 절대 덮어쓰지 않는다 — 새 KPI만 parameters에 추가."""
    run_id = _seed_run(session)
    repo = BacktestRepository(session)
    before = repo.get_run(run_id)
    before_total_return = before.total_return_rate
    before_trade_count = before.trade_count
    analyze_backtest_run(session, run_id)
    session.expire_all()
    after = repo.get_run(run_id)
    assert after.total_return_rate == before_total_return
    assert after.trade_count == before_trade_count


# ---------------------------------------------------------------------------
# API / Auth / Audit
# ---------------------------------------------------------------------------


def test_performance_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/backtest-runs/1/performance").status_code == 401
    assert client.get("/api/v1/backtest-runs/1/summary").status_code == 401
    assert client.get("/api/v1/backtest-runs/1/score").status_code == 401


def test_performance_api_success(session) -> None:
    run_id = _seed_run(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/v1/backtest-runs/{run_id}/performance", headers={"X-Admin-API-Key": admin_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpi"]["trade_count"] == 4
    assert body["score"]["grade"] is not None


def test_summary_api_success(session) -> None:
    run_id = _seed_run(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/v1/backtest-runs/{run_id}/summary", headers={"X-Admin-API-Key": admin_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_count"] == 4
    assert "sharpe_ratio" in body


def test_score_api_success(session) -> None:
    run_id = _seed_run(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/v1/backtest-runs/{run_id}/score", headers={"X-Admin-API-Key": admin_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["grade"] is not None
    assert "breakdown" in body


def test_performance_api_not_found_returns_404(session) -> None:
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/backtest-runs/999999999/performance", headers={"X-Admin-API-Key": admin_key})
    assert resp.status_code == 404


def test_performance_and_score_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    run_id = _seed_run(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.get(f"/api/v1/backtest-runs/{run_id}/performance", headers={"X-Admin-API-Key": admin_key})
    client.get(f"/api/v1/backtest-runs/{run_id}/score", headers={"X-Admin-API-Key": admin_key})
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.run_id == str(run_id))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(5)
    ).all()
    event_types = {e[0] for e in events}
    assert "PERFORMANCE_ANALYZED" in event_types
    assert "STRATEGY_SCORED" in event_types


# ---------------------------------------------------------------------------
# STEP12-7 회귀
# ---------------------------------------------------------------------------


def test_step12_7_moving_average_backtest_regression() -> None:
    from stock_platform.backtest.engine import BacktestEngine
    from stock_platform.backtest.strategy import (
        MovingAverageCrossStrategy,
        MovingAverageStrategyConfig,
    )

    prices = [
        BacktestPrice(
            date(2024, 1, 1) + timedelta(days=i), Decimal(v), Decimal(v), Decimal(v), Decimal(v), Decimal(1)
        )
        for i, v in enumerate([100.0] * 25 + [110.0] * 10)
    ]
    strategy = MovingAverageCrossStrategy(MovingAverageStrategyConfig(short_window=5, long_window=20))
    result = BacktestEngine(strategy).run(
        exchange_code="KRX", symbol="005930", prices=prices, initial_capital=Decimal("1000000"),
    )
    assert result.summary.initial_capital == Decimal("1000000")
