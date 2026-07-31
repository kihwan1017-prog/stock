"""STEP 12-8 — Backtest 결과 기반 Performance Analytics Layer.

기존 `backtest.backtest_run`(+trade/equity, STEP12-6/12-7에서 이미 저장)을
그대로 읽기만 하고(`BacktestRepository` 재사용, 신규 Repository 없음),
Sharpe/Sortino/Calmar/Ulcer Index/Recovery Factor/Expectancy/연속 승패 등
기존 코드베이스 어디에도 실제 계산 로직이 없던 KPI를 여기서 새로 계산한다.

기존 `performance` 도메인(`StrategyPerformanceMetrics` 등)은 이미 계산된
값을 "입력"으로 받아 저장하는 범용 다중 Run-Type(BACKTEST/WALK_FORWARD/
PAPER/LIVE) 추적 시스템이라 이번 요구사항(Backtest 전용 상세 KPI +
Strategy Score/Grade)과는 목적이 달라 중복 확장하지 않고, 이 모듈을
그 옆에 별도로 둔다. 계산 결과는 새 테이블 없이 기존 `backtest_run
.parameters`(JSONB) 컬럼에 병합 저장한다(§ STEP12-7의 Provenance 저장과
동일한 패턴 재사용 — 새 Migration 불필요).

가정(문서화, 임의 변경 금지):
- 무위험 이자율(risk-free rate) = 0
- Sharpe/Sortino 연율화 계수 = sqrt(252)(1일봉 기준)
- Long-only 엔진(STEP12-7에서 확인)이므로 전 거래를 Long으로 집계
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.backtest.persistence_models import (
    BacktestEquityEntity,
    BacktestRunEntity,
    BacktestTradeEntity,
)
from stock_platform.backtest.repository import BacktestRepository

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TRADING_DAYS_PER_YEAR = Decimal("252")
DAYS_PER_YEAR = Decimal("365")

_GRADE_THRESHOLDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("90"), "A+"),
    (Decimal("80"), "A"),
    (Decimal("65"), "B"),
    (Decimal("50"), "C"),
    (Decimal("35"), "D"),
)


class PerformanceAnalyticsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _sqrt(value: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.sqrt()


@dataclass(frozen=True, slots=True)
class EquityPoint:
    trade_date: date
    equity_value: Decimal


@dataclass(frozen=True, slots=True)
class DrawdownPoint:
    trade_date: date
    drawdown_rate: Decimal  # percent, 0 이상


def _drawdown_curve(points: list[EquityPoint]) -> list[DrawdownPoint]:
    curve: list[DrawdownPoint] = []
    peak = None
    for point in points:
        peak = point.equity_value if peak is None else max(peak, point.equity_value)
        drawdown = (
            (peak - point.equity_value) / peak * HUNDRED if peak > ZERO else ZERO
        )
        curve.append(DrawdownPoint(trade_date=point.trade_date, drawdown_rate=drawdown))
    return curve


def _daily_returns(points: list[EquityPoint]) -> list[Decimal]:
    returns: list[Decimal] = []
    for prev, cur in zip(points, points[1:]):
        if prev.equity_value > ZERO:
            returns.append((cur.equity_value - prev.equity_value) / prev.equity_value)
    return returns


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return sum(values, ZERO) / Decimal(len(values))


def _stdev_population(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return ZERO
    m = _mean(values)
    variance = sum(((v - m) ** 2 for v in values), ZERO) / Decimal(len(values))
    return _sqrt(variance)


def _monthly_yearly_returns(
    points: list[EquityPoint], initial_capital: Decimal
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """월별/연도별 마지막 시점 자산으로 구간 수익률을 계산한다(직전 구간
    마지막 자산 대비 — 첫 구간은 initial_capital 대비)."""

    monthly_last: dict[str, EquityPoint] = {}
    yearly_last: dict[str, EquityPoint] = {}
    for point in points:
        month_key = f"{point.trade_date.year:04d}-{point.trade_date.month:02d}"
        year_key = f"{point.trade_date.year:04d}"
        monthly_last[month_key] = point
        yearly_last[year_key] = point

    def _to_series(last_by_key: dict[str, EquityPoint]) -> list[dict[str, Any]]:
        ordered_keys = sorted(last_by_key.keys())
        series: list[dict[str, Any]] = []
        previous_equity = initial_capital
        for key in ordered_keys:
            equity = last_by_key[key].equity_value
            return_rate = (
                (equity - previous_equity) / previous_equity * HUNDRED
                if previous_equity > ZERO
                else ZERO
            )
            series.append(
                {"period": key, "equity": equity, "return_rate": return_rate.quantize(Decimal("0.0001"))}
            )
            previous_equity = equity
        return series

    return _to_series(monthly_last), _to_series(yearly_last)


def _consecutive_streaks(trades: list[BacktestTradeEntity]) -> tuple[int, int]:
    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0
    for trade in trades:
        if trade.net_profit_loss > ZERO:
            current_win += 1
            current_loss = 0
        else:
            current_loss += 1
            current_win = 0
        max_win_streak = max(max_win_streak, current_win)
        max_loss_streak = max(max_loss_streak, current_loss)
    return max_win_streak, max_loss_streak


@dataclass(slots=True)
class ScoreComponent:
    name: str
    weight: Decimal
    raw_value: Decimal | None
    score: Decimal | None


def _score_components(kpi: dict[str, Any]) -> list[ScoreComponent]:
    sharpe = kpi.get("sharpe_ratio")
    mdd = kpi.get("maximum_drawdown_rate")
    profit_factor = kpi.get("profit_factor")
    win_rate = kpi.get("win_rate")
    calmar = kpi.get("calmar_ratio")
    expectancy = kpi.get("expectancy")

    components: list[ScoreComponent] = []

    components.append(
        ScoreComponent(
            name="sharpe_ratio",
            weight=Decimal("25"),
            raw_value=sharpe,
            score=(
                _clamp((sharpe + Decimal("1")) / Decimal("3") * HUNDRED, ZERO, HUNDRED)
                if sharpe is not None
                else None
            ),
        )
    )
    components.append(
        ScoreComponent(
            name="maximum_drawdown_rate",
            weight=Decimal("20"),
            raw_value=mdd,
            score=_clamp(HUNDRED - mdd * Decimal("2"), ZERO, HUNDRED) if mdd is not None else None,
        )
    )
    components.append(
        ScoreComponent(
            name="profit_factor",
            weight=Decimal("20"),
            raw_value=profit_factor,
            score=(
                _clamp(profit_factor / Decimal("3") * HUNDRED, ZERO, HUNDRED)
                if profit_factor is not None
                else None
            ),
        )
    )
    components.append(
        ScoreComponent(
            name="win_rate",
            weight=Decimal("15"),
            raw_value=win_rate,
            score=_clamp(win_rate, ZERO, HUNDRED) if win_rate is not None else None,
        )
    )
    components.append(
        ScoreComponent(
            name="calmar_ratio",
            weight=Decimal("10"),
            raw_value=calmar,
            score=(
                _clamp(calmar / Decimal("3") * HUNDRED, ZERO, HUNDRED)
                if calmar is not None
                else None
            ),
        )
    )
    components.append(
        ScoreComponent(
            name="expectancy",
            weight=Decimal("10"),
            raw_value=expectancy,
            score=(
                None
                if expectancy is None
                else (HUNDRED if expectancy > ZERO else (ZERO if expectancy < ZERO else Decimal("50")))
            ),
        )
    )
    return components


def _grade_for_score(score: Decimal) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def compute_strategy_score(kpi: dict[str, Any]) -> dict[str, Any]:
    """0~100 Strategy Score + 등급(A+/A/B/C/D/F) + 산정 근거를 계산한다.

    데이터 부족으로 계산 불가능한 항목(sharpe_ratio 등, None)은 가중치를
    제외하고 나머지 항목의 가중치를 재정규화한다(전부 None이면 Score도
    None — 임의로 50점 등 fallback 값을 만들지 않는다, Fail Closed).
    """

    components = _score_components(kpi)
    available = [c for c in components if c.score is not None]
    total_weight = sum((c.weight for c in available), ZERO)

    breakdown = [
        {
            "name": c.name,
            "weight": c.weight,
            "raw_value": c.raw_value,
            "component_score": c.score,
            "included": c.score is not None,
        }
        for c in components
    ]

    if total_weight == ZERO:
        return {"score": None, "grade": None, "breakdown": breakdown, "reason": "insufficient_data"}

    weighted_sum = sum((c.score * c.weight for c in available), ZERO)
    score = (weighted_sum / total_weight).quantize(Decimal("0.01"))
    grade = _grade_for_score(score)
    return {"score": score, "grade": grade, "breakdown": breakdown, "reason": None}


def compute_kpi(
    *,
    run: BacktestRunEntity,
    trades: list[BacktestTradeEntity],
    equity_curve: list[BacktestEquityEntity],
) -> dict[str, Any]:
    """§ KPI 계산 — 결정적, run/trades/equity_curve만으로 계산되며 외부
    상태(현재 시각/난수)에 의존하지 않는다(동일 입력 -> 동일 출력)."""

    points = [EquityPoint(e.trade_date, e.equity_value) for e in equity_curve]
    initial_capital = _dec(run.initial_capital)
    final_equity = _dec(run.final_equity)

    total_days = (run.end_date - run.start_date).days
    cagr = None
    if total_days > 0 and initial_capital > ZERO and final_equity >= ZERO:
        growth = final_equity / initial_capital
        try:
            cagr = (
                growth ** (DAYS_PER_YEAR / Decimal(total_days)) - Decimal("1")
            ) * HUNDRED
        except (InvalidOperation, OverflowError):
            cagr = None

    monthly_returns, yearly_returns = _monthly_yearly_returns(points, initial_capital)
    annual_return = _mean([r["return_rate"] for r in yearly_returns]) if yearly_returns else None

    daily_returns = _daily_returns(points)
    mean_return = _mean(daily_returns)
    stdev_return = _stdev_population(daily_returns)
    sharpe_ratio = (
        (mean_return / stdev_return) * _sqrt(TRADING_DAYS_PER_YEAR)
        if stdev_return > ZERO
        else None
    )
    downside_returns = [r for r in daily_returns if r < ZERO]
    downside_stdev = _stdev_population(downside_returns) if len(downside_returns) >= 2 else ZERO
    sortino_ratio = (
        (mean_return / downside_stdev) * _sqrt(TRADING_DAYS_PER_YEAR)
        if downside_stdev > ZERO
        else None
    )

    drawdown_curve = _drawdown_curve(points)
    maximum_drawdown_rate = _dec(run.maximum_drawdown_rate)
    max_drawdown_amount = ZERO
    peak = None
    for point in points:
        peak = point.equity_value if peak is None else max(peak, point.equity_value)
        max_drawdown_amount = max(max_drawdown_amount, peak - point.equity_value)

    calmar_ratio = (
        cagr / maximum_drawdown_rate if cagr is not None and maximum_drawdown_rate > ZERO else None
    )

    ulcer_index = None
    if drawdown_curve:
        squared = [d.drawdown_rate ** 2 for d in drawdown_curve]
        ulcer_index = _sqrt(_mean(squared))

    winning_trades = [t for t in trades if t.net_profit_loss > ZERO]
    losing_trades = [t for t in trades if t.net_profit_loss <= ZERO]
    gross_profit = sum((t.net_profit_loss for t in winning_trades), ZERO)
    gross_loss = sum((t.net_profit_loss for t in losing_trades), ZERO)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != ZERO else None

    net_profit_amount = final_equity - initial_capital
    recovery_factor = (
        net_profit_amount / max_drawdown_amount if max_drawdown_amount > ZERO else None
    )

    trade_count = len(trades)
    average_win = _mean([t.net_profit_loss for t in winning_trades]) if winning_trades else ZERO
    average_loss = _mean([t.net_profit_loss for t in losing_trades]) if losing_trades else ZERO
    win_rate = (
        Decimal(len(winning_trades)) / Decimal(trade_count) * HUNDRED if trade_count else ZERO
    )
    loss_rate = HUNDRED - win_rate if trade_count else ZERO
    expectancy = (
        (win_rate / HUNDRED * average_win) - (loss_rate / HUNDRED * abs(average_loss))
        if trade_count
        else None
    )

    holding_days = [
        (t.exit_date - t.entry_date).days for t in trades if t.exit_date >= t.entry_date
    ]
    average_holding_days = _mean([Decimal(d) for d in holding_days]) if holding_days else ZERO

    max_win_streak, max_loss_streak = _consecutive_streaks(trades)

    return {
        "total_return_rate": _dec(run.total_return_rate),
        "cagr": cagr.quantize(Decimal("0.0001")) if cagr is not None else None,
        "annual_return": annual_return.quantize(Decimal("0.0001")) if annual_return is not None else None,
        "sharpe_ratio": sharpe_ratio.quantize(Decimal("0.0001")) if sharpe_ratio is not None else None,
        "sortino_ratio": sortino_ratio.quantize(Decimal("0.0001")) if sortino_ratio is not None else None,
        "calmar_ratio": calmar_ratio.quantize(Decimal("0.0001")) if calmar_ratio is not None else None,
        "profit_factor": profit_factor.quantize(Decimal("0.0001")) if profit_factor is not None else None,
        "recovery_factor": recovery_factor.quantize(Decimal("0.0001")) if recovery_factor is not None else None,
        "expectancy": expectancy.quantize(Decimal("0.01")) if expectancy is not None else None,
        "win_rate": win_rate.quantize(Decimal("0.0001")),
        "average_win": average_win.quantize(Decimal("0.01")),
        "average_loss": average_loss.quantize(Decimal("0.01")),
        "average_holding_days": average_holding_days.quantize(Decimal("0.01")),
        "maximum_drawdown_rate": maximum_drawdown_rate,
        "maximum_drawdown_amount": max_drawdown_amount.quantize(Decimal("0.01")),
        "ulcer_index": ulcer_index.quantize(Decimal("0.0001")) if ulcer_index is not None else None,
        "trade_count": trade_count,
        "long_trade_count": trade_count,
        "short_trade_count": 0,
        "winning_trade_count": len(winning_trades),
        "losing_trade_count": len(losing_trades),
        "consecutive_wins": max_win_streak,
        "consecutive_losses": max_loss_streak,
        "equity_curve": [
            {"trade_date": p.trade_date.isoformat(), "equity_value": p.equity_value} for p in points
        ],
        "drawdown_curve": [
            {"trade_date": d.trade_date.isoformat(), "drawdown_rate": d.drawdown_rate}
            for d in drawdown_curve
        ],
        "monthly_return": monthly_returns,
        "yearly_return": yearly_returns,
    }


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def analyze_backtest_run(session: Session, backtest_run_id: int) -> dict[str, Any]:
    """KPI + Strategy Score/Grade를 계산하고, 근거를 포함해 기존
    `backtest_run.parameters`(JSONB)에 병합 저장한다(신규 Entity/Table
    없음 — STEP12-7의 Provenance 저장과 동일한 재사용 패턴)."""

    repository = BacktestRepository(session)
    run = repository.get_run(backtest_run_id)
    if run is None:
        raise PerformanceAnalyticsError("NOT_FOUND", f"Backtest run not found: {backtest_run_id}")

    trades = repository.get_trades(backtest_run_id)
    equity_curve = repository.get_equity_curve(backtest_run_id)

    kpi = compute_kpi(run=run, trades=trades, equity_curve=equity_curve)
    score = compute_strategy_score(kpi)

    analytics_payload = {"kpi": _to_jsonable(kpi), "score": _to_jsonable(score)}

    from sqlalchemy.orm.attributes import flag_modified

    parameters = dict(run.parameters or {})
    parameters["performance_analytics"] = analytics_payload
    run.parameters = parameters
    flag_modified(run, "parameters")
    session.commit()

    return {
        "backtest_run_id": int(run.backtest_run_id),
        "strategy_definition_id": run.strategy_definition_id,
        "kpi": kpi,
        "score": score,
    }
