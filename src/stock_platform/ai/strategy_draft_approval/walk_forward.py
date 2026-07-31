"""STEP 12-9 — 승인 Strategy Definition의 Walk-Forward Analysis.

기존 STEP12-7 `run_definition_backtest()`(Definition -> Backtest 실행)와
STEP12-8 `analyze_backtest_run()`(Backtest 결과 -> KPI/Strategy Score)를
그대로 재사용해 In-Sample(train)/Out-of-Sample(test) 구간을 자동 분리하고
Rolling/Expanding Window로 반복 실행한다. 새 BacktestEngine을 만들지
않는다 — Definition은 각 Window마다 동일하게(불변) 재사용되며, 이 STEP은
파라미터 최적화(그리드서치)가 아니라 이미 승인된 고정 Definition의
시간 경과에 따른 신뢰성(강건성/과최적화 여부)을 검증하는 것이 목적이다.
(기존 `backtest/walk_forward_service.py`는 MovingAverage 파라미터 튜닝이
목적이라 서로 다른 관심사 — 그 경로는 건드리지 않는다.)

저장(신규 Table/Migration 없음): 기존 `trading.strategy_performance_run`
(PerformanceRunType.WALK_FORWARD, STEP8-3/STEP12-8 인프라 재사용) +
`trading.walk_forward_window_metric`(각 Window 1행) 재사용. Window 행의
top-level 컬럼(수익률/MDD/Sharpe/Sortino/win_rate/profit_factor 등)은
Out-of-Sample(Test) 결과를 대표값으로 채우고(기존 스키마 관례와 동일),
In-Sample 결과·Strategy Score/Grade·CAGR/Calmar·Overfitting 근거는 모두
`result_payload`(JSONB)에 함께 저장한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    EXECUTION_PURPOSE_WALK_FORWARD_WINDOW,
    BacktestExecutionError,
    run_definition_backtest,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    compile_specification,
)
from stock_platform.performance.backtest_analytics import (
    _to_jsonable,
    analyze_backtest_run,
)
from stock_platform.performance.entities import StrategyPerformanceRunEntity
from stock_platform.performance.models import (
    PerformanceRunType,
    StrategyPerformanceMetrics,
)
from stock_platform.performance.service import StrategyPerformanceService
from stock_platform.performance.walk_forward_entities import (
    WalkForwardWindowMetricEntity,
)
from stock_platform.performance.walk_forward_repository import (
    WalkForwardWindowMetricRepository,
)
from stock_platform.performance.walk_forward_stability import (
    WalkForwardStabilityAnalyzer,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")

WindowScheme = Literal["ROLLING", "EXPANDING"]
_VALID_SCHEMES = frozenset({"ROLLING", "EXPANDING"})

_OVERFITTING_THRESHOLDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("66"), "HIGH"),
    (Decimal("33"), "MEDIUM"),
)


class WalkForwardError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class WalkForwardWindowSpec:
    window_no: int
    train_start_date: date
    train_end_date: date
    test_start_date: date
    test_end_date: date


def build_windows(
    *,
    start_date: date,
    end_date: date,
    train_days: int,
    test_days: int,
    scheme: WindowScheme,
) -> list[WalkForwardWindowSpec]:
    """Rolling(고정 크기 train이 test_days만큼 슬라이딩) 또는
    Expanding(train_start 고정, train 구간이 test_days만큼씩 계속 확장) 방식으로
    In-Sample/Out-of-Sample Window를 자동 분리한다. Look-ahead 방지: 각
    Window의 test 구간은 항상 그 Window의 train 구간보다 뒤에 위치한다."""

    if scheme not in _VALID_SCHEMES:
        raise WalkForwardError("INVALID_WINDOW_SCHEME", f"지원하지 않는 scheme: {scheme}")
    if train_days <= 0 or test_days <= 0:
        raise WalkForwardError("INVALID_WINDOW", "train_days/test_days는 0보다 커야 합니다.")
    if start_date >= end_date:
        raise WalkForwardError("INVALID_WINDOW", "start_date는 end_date보다 이전이어야 합니다.")

    windows: list[WalkForwardWindowSpec] = []
    window_no = 1
    train_start = start_date
    current_train_days = train_days
    while True:
        train_end = train_start + timedelta(days=current_train_days - 1)
        test_start = train_end + timedelta(days=1)
        if test_start > end_date:
            break
        test_end = min(test_start + timedelta(days=test_days - 1), end_date)

        windows.append(
            WalkForwardWindowSpec(
                window_no=window_no,
                train_start_date=train_start,
                train_end_date=train_end,
                test_start_date=test_start,
                test_end_date=test_end,
            )
        )

        if test_end >= end_date:
            break

        if scheme == "ROLLING":
            train_start = train_start + timedelta(days=test_days)
        else:  # EXPANDING — train_start 고정, 다음 반복에서 train 구간만 확장
            current_train_days += test_days
        window_no += 1

    if not windows:
        raise WalkForwardError(
            "INVALID_WINDOW",
            "지정한 기간이 train_days+test_days보다 짧아 Window를 하나도 만들 수 없습니다.",
        )
    return windows


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _window_overfitting_score(in_return: Decimal, out_return: Decimal) -> Decimal:
    """In-Sample 대비 Out-of-Sample 수익률 저하 정도를 0~100으로 환산한다
    (높을수록 과최적화 의심). in_return<=0인 비정상 케이스는 저하를 판단할
    기준이 없으므로 out_return이 더 나쁠 때만 만점(100), 아니면 0으로 처리한다
    (임의 중간값 대체 금지)."""

    if in_return <= ZERO:
        return HUNDRED if out_return < in_return else ZERO
    degradation = (in_return - out_return) / abs(in_return) * HUNDRED
    return _clamp(degradation, ZERO, HUNDRED)


def _overfitting_grade(score: Decimal) -> str:
    for threshold, grade in _OVERFITTING_THRESHOLDS:
        if score >= threshold:
            return grade
    return "LOW"


def _consistency_score(out_returns: list[Decimal]) -> Decimal:
    """Out-of-Sample 수익률들의 변동계수(표준편차/평균절대값) 기반 0~100
    점수 — 변동성이 클수록 낮은 점수. 기존 WalkForwardStabilityAnalyzer의
    stability_score(양의 Window 비율-표준편차-MDD, 0~1 비율 스케일)와는
    별개의, 이번 STEP에서 새로 정의하는 0~100 스케일 지표다."""

    if len(out_returns) < 2:
        return HUNDRED if out_returns and out_returns[0] >= ZERO else ZERO
    mean_return = sum(out_returns, ZERO) / Decimal(len(out_returns))
    variance = sum(((r - mean_return) ** 2 for r in out_returns), ZERO) / Decimal(len(out_returns))
    stdev = variance.sqrt()
    denominator = max(abs(mean_return), Decimal("1"))
    coefficient_of_variation = stdev / denominator
    return _clamp(HUNDRED * (Decimal("1") - coefficient_of_variation), ZERO, HUNDRED)


def _compounded_return(returns_percent: list[Decimal]) -> Decimal:
    factor = Decimal("1")
    for r in returns_percent:
        factor *= Decimal("1") + r / HUNDRED
    return (factor - Decimal("1")) * HUNDRED


def run_walk_forward(
    session: Session,
    strategy_definition_id: int,
    *,
    start_date: date,
    end_date: date,
    train_days: int,
    test_days: int,
    scheme: WindowScheme,
    symbol: str,
    exchange_code: str,
    initial_capital: Decimal,
    fee_ratio: Decimal,
    sell_tax_ratio: Decimal,
    slippage_ratio: Decimal,
    actor: str,
) -> dict[str, Any]:
    """승인 Definition에 대해 Walk-Forward 실행. Window마다 in-sample/
    out-of-sample Backtest를 각각 실행(§ run_definition_backtest 재사용)하고
    KPI/Strategy Score를 계산(§ analyze_backtest_run 재사용)한다. 개별
    Window 실행 실패는 전체를 중단시키지 않고 failures에 기록한다(기존
    backtest/walk_forward_service.py와 동일한 fail-soft 정책)."""

    # Definition 자체가 준비되지 않았거나(readiness) Compile이 불가능하면
    # 모든 Window가 동일하게 실패할 구조적 문제이므로, Window별 fail-soft
    # 재시도로 흡수하지 않고 즉시 차단한다(§ Fail Closed — DEFINITION_NOT_READY
    # /PROVENANCE_INVALID를 개별 Window의 일시적 데이터 부족과 동일하게
    # 취급하지 않는다).
    try:
        specification = compile_specification(session, strategy_definition_id)
    except BacktestSpecificationError as exc:
        raise BacktestExecutionError(exc.code, exc.message) from exc
    if not specification["compilable"]:
        raise BacktestExecutionError(
            "DEFINITION_NOT_READY" if not specification["ready"] else "PROVENANCE_INVALID",
            "; ".join(specification["failure_reasons"]) or "컴파일 실패",
        )

    windows = build_windows(
        start_date=start_date, end_date=end_date,
        train_days=train_days, test_days=test_days, scheme=scheme,
    )

    performance_service = StrategyPerformanceService(session)
    run = performance_service.create_run(
        strategy_code=f"DEFINITION_{strategy_definition_id}",
        run_type=PerformanceRunType.WALK_FORWARD,
        market_code=exchange_code.upper(),
        symbol=symbol.upper(),
        period_start_date=start_date,
        period_end_date=end_date,
        parameter_payload={
            "strategy_definition_id": strategy_definition_id,
            "window_scheme": scheme,
            "train_days": train_days,
            "test_days": test_days,
            "requested_by": actor,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
        strategy_id=strategy_definition_id,
        requested_by_user_id=None,
    )

    window_entities: list[WalkForwardWindowMetricEntity] = []
    failures: list[dict[str, Any]] = []
    out_returns: list[Decimal] = []
    in_returns: list[Decimal] = []
    window_overfitting_scores: list[Decimal] = []
    window_reports: list[dict[str, Any]] = []

    def _runtime_input(w_start: date, w_end: date) -> dict[str, Any]:
        return {
            "symbol": symbol, "exchange_code": exchange_code,
            "start_date": w_start, "end_date": w_end,
            "initial_capital": initial_capital, "fee_ratio": fee_ratio,
            "sell_tax_ratio": sell_tax_ratio, "slippage_ratio": slippage_ratio,
        }

    for window in windows:
        try:
            in_run = run_definition_backtest(
                session, strategy_definition_id,
                runtime_input=_runtime_input(window.train_start_date, window.train_end_date),
                actor=actor, execution_purpose=EXECUTION_PURPOSE_WALK_FORWARD_WINDOW,
            )
            out_run = run_definition_backtest(
                session, strategy_definition_id,
                runtime_input=_runtime_input(window.test_start_date, window.test_end_date),
                actor=actor, execution_purpose=EXECUTION_PURPOSE_WALK_FORWARD_WINDOW,
            )
            in_analysis = analyze_backtest_run(session, in_run["backtest_run_id"])
            out_analysis = analyze_backtest_run(session, out_run["backtest_run_id"])
        except BacktestExecutionError as exc:
            failures.append(
                {
                    "window_no": window.window_no,
                    "train_start_date": window.train_start_date.isoformat(),
                    "train_end_date": window.train_end_date.isoformat(),
                    "test_start_date": window.test_start_date.isoformat(),
                    "test_end_date": window.test_end_date.isoformat(),
                    "code": exc.code,
                    "error": exc.message,
                }
            )
            continue

        in_return = in_analysis["kpi"]["total_return_rate"]
        out_return = out_analysis["kpi"]["total_return_rate"]
        window_overfitting = _window_overfitting_score(in_return, out_return)

        in_returns.append(in_return)
        out_returns.append(out_return)
        window_overfitting_scores.append(window_overfitting)

        out_run_entity_summary = out_run["summary"]
        window_entities.append(
            WalkForwardWindowMetricEntity(
                strategy_performance_run_id=0,  # save_many()가 실제 run_id로 채운다
                window_no=window.window_no,
                train_start_date=window.train_start_date,
                train_end_date=window.train_end_date,
                test_start_date=window.test_start_date,
                test_end_date=window.test_end_date,
                initial_capital=out_run_entity_summary["initial_capital"],
                final_capital=out_run_entity_summary["final_equity"],
                total_return_rate=out_return,
                maximum_drawdown_rate=out_analysis["kpi"]["maximum_drawdown_rate"],
                sharpe_ratio=out_analysis["kpi"]["sharpe_ratio"],
                sortino_ratio=out_analysis["kpi"]["sortino_ratio"],
                win_rate=out_analysis["kpi"]["win_rate"],
                profit_factor=out_analysis["kpi"]["profit_factor"],
                total_trade_count=out_analysis["kpi"]["trade_count"],
                net_profit_amount=(
                    out_run_entity_summary["final_equity"] - out_run_entity_summary["initial_capital"]
                ),
                parameter_payload=_to_jsonable(
                    {
                        "strategy_definition_id": strategy_definition_id,
                        "train_backtest_run_id": in_run["backtest_run_id"],
                        "test_backtest_run_id": out_run["backtest_run_id"],
                        "window_scheme": scheme,
                    }
                ),
                result_payload=_to_jsonable(
                    {
                        "in_sample": {
                            "cagr": in_analysis["kpi"]["cagr"],
                            "sharpe_ratio": in_analysis["kpi"]["sharpe_ratio"],
                            "sortino_ratio": in_analysis["kpi"]["sortino_ratio"],
                            "calmar_ratio": in_analysis["kpi"]["calmar_ratio"],
                            "profit_factor": in_analysis["kpi"]["profit_factor"],
                            "win_rate": in_analysis["kpi"]["win_rate"],
                            "maximum_drawdown_rate": in_analysis["kpi"]["maximum_drawdown_rate"],
                            "total_return_rate": in_return,
                            "strategy_score": in_analysis["score"]["score"],
                            "grade": in_analysis["score"]["grade"],
                        },
                        "out_of_sample": {
                            "cagr": out_analysis["kpi"]["cagr"],
                            "sharpe_ratio": out_analysis["kpi"]["sharpe_ratio"],
                            "sortino_ratio": out_analysis["kpi"]["sortino_ratio"],
                            "calmar_ratio": out_analysis["kpi"]["calmar_ratio"],
                            "profit_factor": out_analysis["kpi"]["profit_factor"],
                            "win_rate": out_analysis["kpi"]["win_rate"],
                            "maximum_drawdown_rate": out_analysis["kpi"]["maximum_drawdown_rate"],
                            "total_return_rate": out_return,
                            "strategy_score": out_analysis["score"]["score"],
                            "grade": out_analysis["score"]["grade"],
                        },
                        "window_overfitting_score": window_overfitting,
                    }
                ),
            )
        )
        window_reports.append(
            _to_jsonable(
                {
                    "window_no": window.window_no,
                    "train_start_date": window.train_start_date.isoformat(),
                    "train_end_date": window.train_end_date.isoformat(),
                    "test_start_date": window.test_start_date.isoformat(),
                    "test_end_date": window.test_end_date.isoformat(),
                    "in_sample": {"total_return_rate": in_return, **in_analysis["score"]},
                    "out_of_sample": {"total_return_rate": out_return, **out_analysis["score"]},
                    "window_overfitting_score": window_overfitting,
                }
            )
        )

    if not window_entities:
        performance_service._repository.fail_run(
            run_id=run.strategy_performance_run_id,
            error_message="모든 Window 실행이 실패했습니다.",
        )
        raise WalkForwardError(
            "ALL_WINDOWS_FAILED", "모든 Window 실행이 실패해 Walk-Forward를 완료할 수 없습니다."
        )

    stability = WalkForwardStabilityAnalyzer.analyze(window_entities)
    consistency_score = _consistency_score(out_returns).quantize(Decimal("0.01"))
    overfitting_score = (
        sum(window_overfitting_scores, ZERO) / Decimal(len(window_overfitting_scores))
    ).quantize(Decimal("0.01"))
    overfitting_grade = _overfitting_grade(overfitting_score)
    forward_performance = _compounded_return(out_returns).quantize(Decimal("0.0001"))
    profitable_out_count = sum(1 for r in out_returns if r > ZERO)
    success_ratio = (
        Decimal(profitable_out_count) / Decimal(len(out_returns)) * HUNDRED
    ).quantize(Decimal("0.01"))

    total_trade_count = sum(int(e.total_trade_count) for e in window_entities)
    weighted_win = sum(
        (Decimal(e.win_rate) * Decimal(e.total_trade_count) for e in window_entities), ZERO
    )
    aggregate_win_rate = (
        weighted_win / Decimal(total_trade_count) if total_trade_count > 0 else ZERO
    )
    net_profit = sum((Decimal(e.net_profit_amount) for e in window_entities), ZERO)
    metrics = StrategyPerformanceMetrics(
        initial_capital=Decimal(window_entities[0].initial_capital),
        final_capital=Decimal(window_entities[0].initial_capital) + net_profit,
        total_return_rate=forward_performance / HUNDRED,
        annualized_return_rate=None,
        maximum_drawdown_rate=max(Decimal(e.maximum_drawdown_rate) for e in window_entities),
        volatility_rate=None,
        sharpe_ratio=(
            sum((Decimal(e.sharpe_ratio) for e in window_entities if e.sharpe_ratio is not None), ZERO)
            / Decimal(sum(1 for e in window_entities if e.sharpe_ratio is not None))
            if any(e.sharpe_ratio is not None for e in window_entities)
            else None
        ),
        sortino_ratio=None,
        win_rate=aggregate_win_rate,
        profit_factor=None,
        total_trade_count=total_trade_count,
        winning_trade_count=0,
        losing_trade_count=0,
        average_profit_amount=ZERO,
        average_loss_amount=ZERO,
        gross_profit_amount=max(net_profit, ZERO),
        gross_loss_amount=min(net_profit, ZERO),
        net_profit_amount=net_profit,
    )

    result_payload = {
        "window_count": len(windows),
        "completed_window_count": len(window_entities),
        "failed_window_count": len(failures),
        "failures": failures,
        "window_scheme": scheme,
        "stability": stability,
        "consistency_score": str(consistency_score),
        "overfitting_score": str(overfitting_score),
        "overfitting_grade": overfitting_grade,
        "forward_performance": str(forward_performance),
        "success_ratio": str(success_ratio),
        "windows": window_reports,
    }

    completed_run = performance_service.complete_run(
        run_id=run.strategy_performance_run_id,
        metrics=metrics,
        result_payload=result_payload,
    )

    WalkForwardWindowMetricRepository(session).save_many(
        strategy_performance_run_id=completed_run.strategy_performance_run_id,
        rows=window_entities,
    )

    return {
        "strategy_performance_run_id": int(completed_run.strategy_performance_run_id),
        "strategy_definition_id": strategy_definition_id,
        "window_scheme": scheme,
        "window_count": len(windows),
        "completed_window_count": len(window_entities),
        "failed_window_count": len(failures),
        "failures": failures,
        "stability": stability,
        "consistency_score": consistency_score,
        "overfitting_score": overfitting_score,
        "overfitting_grade": overfitting_grade,
        "forward_performance": forward_performance,
        "success_ratio": success_ratio,
        "windows": window_reports,
    }


def get_walk_forward_detail(session: Session, run_id: int) -> dict[str, Any]:
    run = session.get(StrategyPerformanceRunEntity, run_id)
    if run is None or run.run_type != PerformanceRunType.WALK_FORWARD.value:
        raise WalkForwardError("NOT_FOUND", f"Walk-Forward run not found: {run_id}")

    windows = WalkForwardWindowMetricRepository(session).list_by_run(
        strategy_performance_run_id=run_id
    )
    return {
        "strategy_performance_run_id": int(run.strategy_performance_run_id),
        "strategy_id": run.strategy_id,
        "status_code": run.status_code,
        "period_start_date": run.period_start_date,
        "period_end_date": run.period_end_date,
        "parameter_payload": run.parameter_payload,
        "result_payload": run.result_payload,
        "windows": [
            {
                "window_no": w.window_no,
                "train_start_date": w.train_start_date,
                "train_end_date": w.train_end_date,
                "test_start_date": w.test_start_date,
                "test_end_date": w.test_end_date,
                "total_return_rate": w.total_return_rate,
                "maximum_drawdown_rate": w.maximum_drawdown_rate,
                "sharpe_ratio": w.sharpe_ratio,
                "sortino_ratio": w.sortino_ratio,
                "win_rate": w.win_rate,
                "profit_factor": w.profit_factor,
                "total_trade_count": w.total_trade_count,
                "result_payload": w.result_payload,
            }
            for w in windows
        ],
    }


def get_overfitting_report(session: Session, run_id: int) -> dict[str, Any]:
    detail = get_walk_forward_detail(session, run_id)
    payload = detail["result_payload"] or {}
    return {
        "strategy_performance_run_id": detail["strategy_performance_run_id"],
        "strategy_id": detail["strategy_id"],
        "overfitting_score": payload.get("overfitting_score"),
        "overfitting_grade": payload.get("overfitting_grade"),
        "consistency_score": payload.get("consistency_score"),
        "stability": payload.get("stability"),
        "success_ratio": payload.get("success_ratio"),
        "forward_performance": payload.get("forward_performance"),
        "per_window": [
            {
                "window_no": w["window_no"],
                "in_sample": w["result_payload"].get("in_sample"),
                "out_of_sample": w["result_payload"].get("out_of_sample"),
                "window_overfitting_score": w["result_payload"].get("window_overfitting_score"),
            }
            for w in detail["windows"]
        ],
    }
