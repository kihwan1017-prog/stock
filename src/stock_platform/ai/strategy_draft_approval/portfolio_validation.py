"""STEP 12-13 — Portfolio Validation.

복수의 승인된 Strategy Definition과 기존 Backtest 결과(이미 완료된
backtest.backtest_run + 그 Equity Curve)만 조합해 전략 간 상관관계·
집중도·분산 효과·포트폴리오 성과·위험 기여도·중복 노출을 평가한다.
실제 Portfolio를 생성/운영하지 않고, 새 Backtest를 실행하지 않으며,
Weight를 자동 최적화하지 않는다.

재사용(중복 생성 금지 확인):
- 조사 결과 `backtest/portfolio_models.py`/`portfolio_service.py`/
  `portfolio_report.py`(기존 `PortfolioBacktestResult` 등)는 "여러
  종목(Asset)에 자본을 배분해 동일 MovingAverage 전략을 새로 실행"하는
  완전히 다른 기능(신규 Backtest 실행, Asset 단위)이라 이번 STEP의
  목적(이미 승인된 서로 다른 Strategy Definition들의 이미 완료된 Backtest
  결과 조합, 신규 실행 없음)과 근본적으로 달라 재사용/확장하지 않는다.
- 상관관계/공분산 계산 유틸은 이 프로젝트 어디에도 없어(조사 결과) 순수
  Decimal 기반으로 새로 구현한다(numpy 미도입, STEP12-12와 동일 원칙).
- Portfolio KPI는 STEP12-8 `performance/backtest_analytics.py`의 순수
  계산 프리미티브(`EquityPoint`/`_drawdown_curve`/`_daily_returns`/
  `_mean`/`_stdev_population`/`_sqrt`/`_clamp`)를 그대로 재사용한다(새
  Analyzer 없음) — 이 함수들은 Trade가 아니라 Equity Curve만 필요로 해
  Portfolio Equity Curve에도 그대로 적용 가능함을 확인했다.
- Provenance 검증은 STEP12-5 `check_readiness()`, Specification은
  STEP12-6 `compile_specification()`을 그대로 재사용한다.
- 저장은 기존 4개 STEP의 저장 구조 전부가 단일 Strategy/단일 Run 기준
  스키마라 이 STEP의 다대다 조합 내용을 담을 수 없어 최소 전용 불변
  테이블 1개만 추가한다(§ 완료보고 Migration 항목).

Alignment Policy: INTERSECTION만 완전히 구현한다. UNION_FORWARD_FILL은
Forward-Fill 경계 조건(각 전략의 시작 이전 구간 처리, 아직 시작되지 않은
구간의 Weight 처리)이 이번 STEP 범위 안에서 안전하게 확정하기 어려워
명시적으로 차단한다(요구사항 문서가 이 경우 명시적 차단을 허용함)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    _canonical_json,
    _hash,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.portfolio_validation_entities import (
    PortfolioValidationReportEntity,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    check_readiness,
)
from stock_platform.backtest.persistence_models import BacktestRunEntity
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.performance.backtest_analytics import (
    EquityPoint,
    _daily_returns,
    _drawdown_curve,
    _mean,
    _stdev_population,
    _sqrt,
    _to_jsonable,
)

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

ALGORITHM_VERSION = "1.0.0"
MIN_STRATEGIES = 2
MAX_STRATEGIES = 10
# STEP12-13 인수 조건 §3 — Portfolio Equity/KPI가 "매일 목표 비중으로
# 재조정한다고 가정한 가상 Portfolio"라는 전제를 API/Frontend에 항상
# 명시한다(실제 체결 기반 Buy-and-Hold Portfolio로 오해되지 않도록).
METHODOLOGY_NOTE = (
    "Daily Rebalanced Hypothetical Portfolio: 매일 목표 비중으로 재조정한다고 "
    "가정한 가상의 Portfolio 결과입니다. 실제 체결 기반 Buy-and-Hold "
    "Portfolio의 결과가 아닙니다."
)
WEIGHTING_METHODS = frozenset({"EQUAL_WEIGHT", "CUSTOM_WEIGHT"})
ALIGNMENT_POLICIES = frozenset({"INTERSECTION", "UNION_FORWARD_FILL"})
DEFAULT_MINIMUM_OVERLAP_DAYS = 60
DEFAULT_INITIAL_CAPITAL = Decimal("10000000")
DEFAULT_CORRELATION_THRESHOLD = Decimal("0.7")
DEFAULT_CONCENTRATION_THRESHOLD = Decimal("0.40")
# Custom Weight 합계 허용 오차(Decimal 반올림 누적 오차 대응, 문서화된 값).
WEIGHT_SUM_TOLERANCE = Decimal("0.0001")
MIN_VALID_OBSERVATIONS_FOR_ANALYSIS = 30


class PortfolioValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Strategy / Backtest Validation — 구조적 오류는 전체 실행을 즉시 중단한다
# (개별 전략을 임의로 제외하고 진행하지 않는다).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategyBacktestBundle:
    strategy_definition_id: int
    backtest_run_id: int
    run: BacktestRunEntity
    equity_curve: list[EquityPoint]
    executable_hash: str
    runtime_input_hash: str
    market_type: str | None
    timeframe: str | None
    symbol: str
    exchange_code: str
    signal_signature_hash: str


def _compute_signal_signature_hash(specification: dict[str, Any]) -> str:
    canonical = {
        "entry_rules": specification["entry_rules"],
        "exit_rules": specification["exit_rules"],
        "stop_loss_rule": specification["stop_loss_rule"],
        "take_profit_rule": specification["take_profit_rule"],
        "position_sizing_rule": specification["position_sizing_rule"],
    }
    return _hash(_canonical_json(_to_jsonable(canonical)))


def validate_and_load_strategy(
    session: Session, *, strategy_definition_id: int, backtest_run_id: int
) -> StrategyBacktestBundle:
    """§ Strategy 및 Backtest 검증. 하나라도 실패하면 즉시 예외를
    던진다(fail-soft로 일부만 제외하지 않음)."""

    try:
        readiness = check_readiness(session, strategy_definition_id)
    except ReadinessError as exc:
        raise PortfolioValidationError(exc.code, exc.message) from exc
    if not readiness["ready"]:
        raise PortfolioValidationError(
            "DEFINITION_NOT_READY",
            f"Strategy Definition #{strategy_definition_id}: " + ("; ".join(readiness["failure_reasons"]) or "준비되지 않음"),
        )

    try:
        specification = compile_specification(session, strategy_definition_id)
    except BacktestSpecificationError as exc:
        raise PortfolioValidationError(exc.code, exc.message) from exc
    if not specification["compilable"]:
        raise PortfolioValidationError(
            "SPECIFICATION_NOT_COMPILABLE",
            f"Strategy Definition #{strategy_definition_id}: " + ("; ".join(specification["failure_reasons"]) or "컴파일 실패"),
        )

    repo = BacktestRepository(session)
    run = repo.get_run(backtest_run_id)
    if run is None:
        raise PortfolioValidationError("BACKTEST_RUN_NOT_FOUND", f"Backtest run not found: {backtest_run_id}")
    if run.strategy_definition_id != strategy_definition_id:
        raise PortfolioValidationError(
            "OWNERSHIP_MISMATCH",
            f"Backtest Run #{backtest_run_id}은 Strategy Definition #{strategy_definition_id}의 결과가 아닙니다.",
        )
    if run.status_code != "SUCCESS":
        raise PortfolioValidationError(
            "BACKTEST_NOT_COMPLETED", f"Backtest Run #{backtest_run_id}이 완료 상태가 아닙니다({run.status_code})."
        )

    run_parameters = run.parameters or {}
    executable_hash = run_parameters.get("executable_hash")
    runtime_input_hash = run_parameters.get("runtime_input_hash")
    if not executable_hash:
        raise PortfolioValidationError(
            "EXECUTABLE_HASH_MISSING", f"Backtest Run #{backtest_run_id}에 executable_hash가 없습니다."
        )
    if not runtime_input_hash:
        raise PortfolioValidationError(
            "RUNTIME_INPUT_HASH_MISSING", f"Backtest Run #{backtest_run_id}에 runtime_input_hash가 없습니다."
        )
    if executable_hash != specification["executable_hash"]:
        raise PortfolioValidationError(
            "PROVENANCE_MISMATCH",
            f"Backtest Run #{backtest_run_id}의 executable_hash가 현재 Definition의 Specification과 일치하지 않습니다.",
        )

    equity_rows = repo.get_equity_curve(backtest_run_id)
    if not equity_rows:
        raise PortfolioValidationError(
            "EQUITY_CURVE_MISSING", f"Backtest Run #{backtest_run_id}에 Equity Curve가 없습니다."
        )
    equity_curve = [EquityPoint(row.trade_date, Decimal(row.equity_value)) for row in equity_rows]

    return StrategyBacktestBundle(
        strategy_definition_id=strategy_definition_id,
        backtest_run_id=backtest_run_id,
        run=run,
        equity_curve=equity_curve,
        executable_hash=executable_hash,
        runtime_input_hash=runtime_input_hash,
        market_type=specification.get("market_type"),
        timeframe=specification.get("timeframe"),
        symbol=run.symbol,
        exchange_code=run.exchange_code,
        signal_signature_hash=_compute_signal_signature_hash(specification),
    )


# ---------------------------------------------------------------------------
# Weight Validation / Generation.
# ---------------------------------------------------------------------------


def resolve_weights(
    *,
    strategy_definition_ids: list[int],
    weighting_method: str,
    strategy_weights: dict[int, Decimal] | None,
) -> dict[int, Decimal]:
    if weighting_method not in WEIGHTING_METHODS:
        raise PortfolioValidationError("UNSUPPORTED_WEIGHTING_METHOD", f"지원하지 않는 weighting_method: {weighting_method}")

    ordered_ids = sorted(strategy_definition_ids)  # 결정적 순서(입력 순서 무관 재현성)
    n = len(ordered_ids)

    if weighting_method == "EQUAL_WEIGHT":
        base = (ONE / Decimal(n)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        weights = {sid: base for sid in ordered_ids}
        # 마지막(정렬 기준) 전략에서 누적 절삭 오차를 결정적으로 보정해
        # 합계가 정확히 1이 되도록 한다.
        remainder = ONE - base * Decimal(n - 1)
        weights[ordered_ids[-1]] = remainder
        return weights

    # CUSTOM_WEIGHT
    if strategy_weights is None or set(strategy_weights.keys()) != set(ordered_ids):
        raise PortfolioValidationError(
            "MISSING_WEIGHT", "CUSTOM_WEIGHT는 모든 Strategy에 대한 Weight가 필요합니다."
        )
    for sid, w in strategy_weights.items():
        if w <= ZERO:
            raise PortfolioValidationError("INVALID_WEIGHT", f"Strategy #{sid}의 Weight는 0보다 커야 합니다.")
    total = sum(strategy_weights.values(), ZERO)
    # 이 프로젝트는 비율(ratio) 단위를 사용한다(§ STEP12-2-2 position_sizing_rule.value
    # 관례 재사용 — FIXED_PERCENT/KELLY_FRACTION은 0~1 비율). Weight 합계도
    # 100이 아니라 1을 기준으로 한다. 허용 오차를 벗어나면 임의로 정규화해
    # 숨기지 않고 차단한다.
    if abs(total - ONE) > WEIGHT_SUM_TOLERANCE:
        raise PortfolioValidationError(
            "INVALID_WEIGHT_SUM", f"Weight 합계는 1이어야 합니다(허용 오차 {WEIGHT_SUM_TOLERANCE}, 실제 합계: {total})."
        )
    return dict(strategy_weights)


def validate_strategy_count_and_uniqueness(
    strategy_definition_ids: list[int], backtest_run_ids: list[int]
) -> None:
    if len(strategy_definition_ids) < MIN_STRATEGIES:
        raise PortfolioValidationError(
            "TOO_FEW_STRATEGIES", f"Strategy는 최소 {MIN_STRATEGIES}개 이상이어야 합니다."
        )
    if len(strategy_definition_ids) > MAX_STRATEGIES:
        raise PortfolioValidationError(
            "TOO_MANY_STRATEGIES", f"Strategy는 최대 {MAX_STRATEGIES}개까지만 지원합니다."
        )
    if len(set(strategy_definition_ids)) != len(strategy_definition_ids):
        raise PortfolioValidationError("DUPLICATE_STRATEGY", "동일 Strategy Definition을 중복 입력할 수 없습니다.")
    if len(set(backtest_run_ids)) != len(backtest_run_ids):
        raise PortfolioValidationError("DUPLICATE_BACKTEST_RUN", "동일 Backtest Run을 중복 입력할 수 없습니다.")
    if len(strategy_definition_ids) != len(backtest_run_ids):
        raise PortfolioValidationError(
            "INVALID_REQUEST", "strategy_definition_ids와 backtest_run_ids의 개수가 일치해야 합니다."
        )


# ---------------------------------------------------------------------------
# Date Alignment — INTERSECTION만 완전 구현(§ 모듈 docstring).
# ---------------------------------------------------------------------------


def align_equity_curves(
    *,
    bundles: list[StrategyBacktestBundle],
    alignment_policy: str,
    minimum_overlap_days: int,
) -> tuple[list[date], dict[int, list[Decimal]]]:
    """`minimum_overlap_days`는 Return Observation Count 기준이다(STEP12-13
    인수 조건 §4에서 발견 — 기존에는 Equity Observation Count 기준이라
    Return 계산 시 항상 실제 관측치가 1개 적었다). Equity 교집합이
    `minimum_overlap_days + 1`개 이상이어야(Return이 `minimum_overlap_days`
    개 이상 나오도록) 통과시킨다."""
    if alignment_policy not in ALIGNMENT_POLICIES:
        raise PortfolioValidationError("UNSUPPORTED_ALIGNMENT_POLICY", f"지원하지 않는 alignment_policy: {alignment_policy}")
    if alignment_policy == "UNION_FORWARD_FILL":
        raise PortfolioValidationError(
            "UNSUPPORTED_ALIGNMENT_POLICY",
            "UNION_FORWARD_FILL은 이번 STEP에서 지원하지 않습니다(경계 조건 미확정으로 명시적 차단).",
        )

    date_sets: list[set[date]] = []
    for bundle in bundles:
        seen: set[date] = set()
        for point in bundle.equity_curve:
            if point.trade_date in seen:
                raise PortfolioValidationError(
                    "DUPLICATE_DATE",
                    f"Strategy #{bundle.strategy_definition_id}의 Equity Curve에 중복 날짜가 있습니다: {point.trade_date}",
                )
            seen.add(point.trade_date)
            if point.equity_value <= ZERO:
                raise PortfolioValidationError(
                    "INVALID_EQUITY_VALUE",
                    f"Strategy #{bundle.strategy_definition_id}의 Equity가 0 이하입니다({point.trade_date}).",
                )
        date_sets.append(seen)

    common_dates = sorted(set.intersection(*date_sets)) if date_sets else []
    return_observation_count = max(len(common_dates) - 1, 0)
    if return_observation_count < minimum_overlap_days:
        raise PortfolioValidationError(
            "INSUFFICIENT_OVERLAP",
            f"공통 기간의 Return Observation 수({return_observation_count}개)가 "
            f"최소 기준({minimum_overlap_days}개) 미만입니다.",
        )

    aligned: dict[int, list[Decimal]] = {}
    for bundle in bundles:
        by_date = {p.trade_date: p.equity_value for p in bundle.equity_curve}
        aligned[bundle.strategy_definition_id] = [by_date[d] for d in common_dates]
    return common_dates, aligned


# ---------------------------------------------------------------------------
# Return Series — Look-ahead 없음(각 시점은 그 이전 시점 대비로만 계산).
# ---------------------------------------------------------------------------


def compute_return_series(equities: list[Decimal]) -> list[Decimal]:
    returns: list[Decimal] = []
    for prev, cur in zip(equities, equities[1:]):
        if prev <= ZERO:
            raise PortfolioValidationError("INVALID_EQUITY_VALUE", "Equity가 0 이하인 구간은 Return을 계산할 수 없습니다.")
        returns.append(cur / prev - ONE)
    return returns


# ---------------------------------------------------------------------------
# Portfolio Equity Curve — Daily Rebalancing 가정(Weight Drift 없음).
# ---------------------------------------------------------------------------


def compute_portfolio_returns(
    *, strategy_returns: dict[int, list[Decimal]], weights: dict[int, Decimal]
) -> list[Decimal]:
    ids = list(strategy_returns.keys())
    n_days = len(strategy_returns[ids[0]])
    portfolio_returns: list[Decimal] = []
    for t in range(n_days):
        total = sum((strategy_returns[sid][t] * weights[sid] for sid in ids), ZERO)
        portfolio_returns.append(total)
    return portfolio_returns


def compute_portfolio_equity_curve(
    *, initial_capital: Decimal, portfolio_returns: list[Decimal], dates: list[date]
) -> list[EquityPoint]:
    equity = initial_capital
    curve = [EquityPoint(dates[0], initial_capital)]
    for i, r in enumerate(portfolio_returns):
        equity = equity * (ONE + r)
        curve.append(EquityPoint(dates[i + 1], equity))
    return curve


# ---------------------------------------------------------------------------
# Portfolio KPI — STEP12-8 계산 프리미티브 재사용.
# ---------------------------------------------------------------------------


def compute_portfolio_kpi(curve: list[EquityPoint], initial_capital: Decimal) -> dict[str, Any]:
    final_equity = curve[-1].equity_value
    total_days = (curve[-1].trade_date - curve[0].trade_date).days
    total_return = ((final_equity - initial_capital) / initial_capital * HUNDRED).quantize(Decimal("0.0001"))

    cagr = None
    if total_days > 0:
        growth = final_equity / initial_capital
        try:
            cagr = ((growth ** (Decimal(365) / Decimal(total_days))) - ONE) * HUNDRED
            cagr = cagr.quantize(Decimal("0.0001"))
        except (ArithmeticError, ValueError):
            cagr = None

    daily_returns = _daily_returns(curve)
    obs_count = len(daily_returns)
    mean_r = _mean(daily_returns)
    stdev_r = _stdev_population(daily_returns)
    sharpe = ((mean_r / stdev_r) * _sqrt(Decimal(252))).quantize(Decimal("0.0001")) if stdev_r > ZERO else None
    downside = [r for r in daily_returns if r < ZERO]
    downside_stdev = _stdev_population(downside) if len(downside) >= 2 else ZERO
    sortino = (
        ((mean_r / downside_stdev) * _sqrt(Decimal(252))).quantize(Decimal("0.0001"))
        if downside_stdev > ZERO else None
    )

    drawdown_curve = _drawdown_curve(curve)
    max_dd_percent = max((d.drawdown_rate for d in drawdown_curve), default=ZERO).quantize(Decimal("0.0001"))
    peak = None
    max_dd_amount = ZERO
    for point in curve:
        peak = point.equity_value if peak is None else max(peak, point.equity_value)
        max_dd_amount = max(max_dd_amount, peak - point.equity_value)
    max_dd_amount = max_dd_amount.quantize(Decimal("0.01"))

    calmar = (cagr / max_dd_percent).quantize(Decimal("0.0001")) if (cagr is not None and max_dd_percent > ZERO) else None
    ulcer = (
        _sqrt(_mean([d.drawdown_rate ** 2 for d in drawdown_curve])).quantize(Decimal("0.0001"))
        if drawdown_curve else None
    )
    volatility = (stdev_r * _sqrt(Decimal(252)) * HUNDRED).quantize(Decimal("0.0001")) if obs_count >= 2 else None

    positive_days = sum(1 for r in daily_returns if r > ZERO)
    negative_days = sum(1 for r in daily_returns if r < ZERO)
    positive_ratio = (Decimal(positive_days) / Decimal(obs_count) * HUNDRED).quantize(Decimal("0.01")) if obs_count else None
    negative_ratio = (Decimal(negative_days) / Decimal(obs_count) * HUNDRED).quantize(Decimal("0.01")) if obs_count else None

    return {
        "total_return": total_return,
        "cagr": cagr,
        "annual_return": cagr,  # Daily Rebalancing 단일 Curve라 CAGR과 동일 정의 사용(문서화)
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "maximum_drawdown_amount": max_dd_amount,
        "maximum_drawdown_percent": max_dd_percent,
        "ulcer_index": ulcer,
        "volatility": volatility,
        "positive_day_ratio": positive_ratio,
        "negative_day_ratio": negative_ratio,
        "observation_count": obs_count,
        # Trade 기반 KPI는 Portfolio Daily Return만으로 자연스럽게 계산할 수
        # 없어 강제 산출하지 않는다(§ 명시적 N/A).
        "profit_factor": None,
        "trade_count": None,
        "win_rate": None,
        "average_holding_days": None,
    }


def compute_standalone_kpi_for_strategy(equities: list[Decimal], dates: list[date]) -> dict[str, Any]:
    curve = [EquityPoint(d, e) for d, e in zip(dates, equities)]
    return compute_portfolio_kpi(curve, equities[0])


# ---------------------------------------------------------------------------
# Correlation Matrix.
# ---------------------------------------------------------------------------


def compute_pairwise_correlation(returns_a: list[Decimal], returns_b: list[Decimal]) -> Decimal | None:
    n = len(returns_a)
    if n < 2:
        return None
    mean_a, mean_b = _mean(returns_a), _mean(returns_b)
    cov = sum(((returns_a[i] - mean_a) * (returns_b[i] - mean_b) for i in range(n)), ZERO) / Decimal(n)
    std_a, std_b = _stdev_population(returns_a), _stdev_population(returns_b)
    if std_a == ZERO or std_b == ZERO:
        return None
    corr = cov / (std_a * std_b)
    corr = max(Decimal("-1"), min(ONE, corr))
    return corr.quantize(Decimal("0.0001"))


def compute_correlation_matrix(
    strategy_ids: list[int], returns: dict[int, list[Decimal]]
) -> dict[str, Any]:
    ordered = sorted(strategy_ids)
    matrix: dict[int, dict[int, str | None]] = {sid: {} for sid in ordered}
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(ordered):
        for b in ordered:
            if a == b:
                matrix[a][b] = str(ONE)
        for j in range(i + 1, len(ordered)):
            b = ordered[j]
            corr = compute_pairwise_correlation(returns[a], returns[b])
            matrix[a][b] = str(corr) if corr is not None else None
            matrix[b][a] = str(corr) if corr is not None else None
            pairs.append({"strategy_a": a, "strategy_b": b, "correlation": corr})

    valid = [p["correlation"] for p in pairs if p["correlation"] is not None]
    average = _mean(valid).quantize(Decimal("0.0001")) if valid else None
    maximum = max(valid) if valid else None
    return {
        "matrix": matrix,
        "pairs": _to_jsonable(pairs),
        "average_pairwise_correlation": average,
        "maximum_pairwise_correlation": maximum,
    }


def find_highly_correlated_pairs(
    pairs: list[dict[str, Any]], *, correlation_threshold: Decimal
) -> list[dict[str, Any]]:
    return [p for p in pairs if p["correlation"] is not None and Decimal(str(p["correlation"])) > correlation_threshold]


# ---------------------------------------------------------------------------
# Concentration Analysis.
# ---------------------------------------------------------------------------


def compute_concentration(
    weights: dict[int, Decimal], *, concentration_threshold: Decimal = DEFAULT_CONCENTRATION_THRESHOLD
) -> dict[str, Any]:
    """HHI(Herfindahl-Hirschman Index) 기반 집중도. `concentration_threshold`
    를 HIGH 판정 HHI 상한으로 사용하고, MEDIUM 상한은 그 62.5%(기존
    0.40/0.25 기본값 비율을 그대로 유지, 문서화된 비율)로 파생시켜
    호출자가 지정한 threshold가 실제로 판정에 반영되도록 한다(이전에는
    이 파라미터가 받아지기만 하고 전혀 사용되지 않던 것을 수정)."""
    sorted_weights = sorted(weights.values(), reverse=True)
    largest = sorted_weights[0]
    top2 = sum(sorted_weights[:2], ZERO)
    hhi = sum((w ** 2 for w in weights.values()), ZERO)
    effective_n = (ONE / hhi).quantize(Decimal("0.01")) if hhi > ZERO else None

    medium_threshold = (concentration_threshold * Decimal("0.625")).quantize(Decimal("0.0001"))
    if hhi >= concentration_threshold:
        status = "HIGH"
    elif hhi >= medium_threshold:
        status = "MEDIUM"
    else:
        status = "LOW"

    return {
        "largest_strategy_weight": largest,
        "top2_weight_sum": top2,
        "herfindahl_hirschman_index": hhi.quantize(Decimal("0.0001")),
        "effective_number_of_strategies": effective_n,
        "concentration_status": status,
    }


# ---------------------------------------------------------------------------
# Risk Contribution — Covariance 기반 Marginal/Component Contribution.
# ---------------------------------------------------------------------------


def compute_risk_contribution(
    strategy_ids: list[int], weights: dict[int, Decimal], returns: dict[int, list[Decimal]]
) -> dict[str, Any]:
    ordered = sorted(strategy_ids)
    n_obs = len(returns[ordered[0]])
    means = {sid: _mean(returns[sid]) for sid in ordered}
    covariance: dict[tuple[int, int], Decimal] = {}
    for a in ordered:
        for b in ordered:
            covariance[(a, b)] = sum(
                ((returns[a][i] - means[a]) * (returns[b][i] - means[b]) for i in range(n_obs)), ZERO
            ) / Decimal(n_obs)

    portfolio_variance = sum(
        (weights[a] * weights[b] * covariance[(a, b)] for a in ordered for b in ordered), ZERO
    )

    if portfolio_variance <= ZERO:
        return {
            "portfolio_variance": None,
            "contributions": [
                {
                    "strategy_definition_id": sid, "weight": weights[sid],
                    "volatility": _stdev_population(returns[sid]),
                    "marginal_risk_contribution": None, "component_risk_contribution": None,
                    "risk_contribution_percent": None,
                }
                for sid in ordered
            ],
            "total_risk_contribution_percent": None,
        }

    contributions = []
    total_pct = ZERO
    for a in ordered:
        marginal = sum((weights[b] * covariance[(a, b)] for b in ordered), ZERO)
        component = weights[a] * marginal
        pct = (component / portfolio_variance * HUNDRED).quantize(Decimal("0.01"))
        total_pct += pct
        contributions.append(
            {
                "strategy_definition_id": a, "weight": weights[a],
                "volatility": _stdev_population(returns[a]).quantize(Decimal("0.000001")),
                "marginal_risk_contribution": marginal.quantize(Decimal("0.00000001")),
                "component_risk_contribution": component.quantize(Decimal("0.00000001")),
                "risk_contribution_percent": pct,
            }
        )
    return {
        "portfolio_variance": portfolio_variance.quantize(Decimal("0.00000001")),
        "contributions": contributions,
        "total_risk_contribution_percent": total_pct.quantize(Decimal("0.01")),
    }


# ---------------------------------------------------------------------------
# Diversification Benefit.
# ---------------------------------------------------------------------------


def compute_diversification_benefit(
    *,
    weights: dict[int, Decimal],
    standalone_volatility: dict[int, Decimal],
    portfolio_volatility: Decimal | None,
    standalone_mdd: dict[int, Decimal],
    portfolio_mdd: Decimal,
) -> dict[str, Any]:
    weighted_avg_volatility = sum((weights[sid] * standalone_volatility[sid] for sid in weights), ZERO)
    benefit = None
    if weighted_avg_volatility > ZERO and portfolio_volatility is not None:
        benefit = (ONE - portfolio_volatility / weighted_avg_volatility).quantize(Decimal("0.0001"))

    weighted_avg_mdd = sum((weights[sid] * standalone_mdd[sid] for sid in weights), ZERO)
    mdd_reduction = (weighted_avg_mdd - portfolio_mdd).quantize(Decimal("0.0001"))

    return {
        "weighted_average_standalone_volatility": weighted_avg_volatility.quantize(Decimal("0.0001")),
        "portfolio_volatility": portfolio_volatility,
        "diversification_benefit": benefit,
        "weighted_average_standalone_maximum_drawdown": weighted_avg_mdd.quantize(Decimal("0.0001")),
        "portfolio_maximum_drawdown": portfolio_mdd,
        "maximum_drawdown_reduction": mdd_reduction,
    }


# ---------------------------------------------------------------------------
# Duplicate Exposure Detection.
# ---------------------------------------------------------------------------


def detect_duplicate_exposures(
    bundles: list[StrategyBacktestBundle], *, correlation_pairs: list[dict[str, Any]], correlation_threshold: Decimal
) -> list[dict[str, Any]]:
    by_id = {b.strategy_definition_id: b for b in bundles}
    correlation_by_pair = {
        frozenset((p["strategy_a"], p["strategy_b"])): p["correlation"] for p in correlation_pairs
    }
    ordered = sorted(by_id.keys())
    results: list[dict[str, Any]] = []
    for i, a in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            b = ordered[j]
            bundle_a, bundle_b = by_id[a], by_id[b]
            reasons: list[str] = []

            same_symbol = bundle_a.symbol == bundle_b.symbol and bundle_a.exchange_code == bundle_b.exchange_code
            if same_symbol:
                reasons.append("SAME_SYMBOL")
            if bundle_a.market_type is not None and bundle_a.market_type == bundle_b.market_type:
                reasons.append("SAME_MARKET")
            if bundle_a.timeframe is not None and bundle_a.timeframe == bundle_b.timeframe:
                reasons.append("SAME_TIMEFRAME")
            if bundle_a.signal_signature_hash == bundle_b.signal_signature_hash:
                reasons.append("SAME_SIGNAL_SIGNATURE")
            if (
                same_symbol
                and bundle_a.run.start_date == bundle_b.run.start_date
                and bundle_a.run.end_date == bundle_b.run.end_date
            ):
                reasons.append("SAME_BACKTEST_DATA_SERIES")
            corr = correlation_by_pair.get(frozenset((a, b)))
            if corr is not None and Decimal(str(corr)) > correlation_threshold:
                reasons.append("HIGH_RETURN_CORRELATION")

            if not reasons:
                continue

            reason_set = set(reasons)
            if {"SAME_SIGNAL_SIGNATURE", "SAME_SYMBOL", "SAME_TIMEFRAME"} <= reason_set:
                severity = "HIGH"
            elif "SAME_BACKTEST_DATA_SERIES" in reason_set or "HIGH_RETURN_CORRELATION" in reason_set:
                severity = "WARNING"
            else:
                severity = "INFO"

            results.append(
                {
                    "strategy_a": a, "strategy_b": b, "reasons": sorted(reason_set), "severity": severity,
                }
            )
    return results


# ---------------------------------------------------------------------------
# Portfolio Robustness Score.
# ---------------------------------------------------------------------------


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def compute_portfolio_robustness_score(
    *,
    diversification_benefit: Decimal | None,
    average_pairwise_correlation: Decimal | None,
    maximum_pairwise_correlation: Decimal | None,
    concentration_hhi: Decimal | None,
    risk_contribution_stdev_percent: Decimal | None,
    portfolio_mdd_percent: Decimal | None,
    strategy_count: int,
    duplicate_exposure_severities: list[str],
    valid_observation_ratio_percent: Decimal | None,
) -> dict[str, Any]:
    """0~100. 9개 요소 가중 조합(가중치 합 100): Diversification Benefit 18
    / Average Pairwise Correlation 13 / Maximum Pairwise Correlation 9 /
    Concentration(HHI) 13 / Risk Contribution Balance 9 / Portfolio
    Drawdown 13 / Strategy Count 5 / Duplicate Exposure Severity 9 /
    유효 관측 비율 11. 계산 불가 항목은 0점이 아니라 제외 후 재정규화."""

    components: list[dict[str, Any]] = []
    components.append(
        {
            "name": "diversification_benefit", "weight": Decimal("18"),
            "score": (
                _clamp(Decimal("50") + diversification_benefit * HUNDRED, ZERO, HUNDRED)
                if diversification_benefit is not None else None
            ),
        }
    )
    components.append(
        {
            "name": "average_pairwise_correlation", "weight": Decimal("13"),
            "score": (
                _clamp((ONE - average_pairwise_correlation) / Decimal("2") * HUNDRED, ZERO, HUNDRED)
                if average_pairwise_correlation is not None else None
            ),
        }
    )
    components.append(
        {
            "name": "maximum_pairwise_correlation", "weight": Decimal("9"),
            "score": (
                _clamp((ONE - maximum_pairwise_correlation) / Decimal("2") * HUNDRED, ZERO, HUNDRED)
                if maximum_pairwise_correlation is not None else None
            ),
        }
    )
    components.append(
        {
            "name": "concentration", "weight": Decimal("13"),
            "score": _clamp(HUNDRED - concentration_hhi * HUNDRED, ZERO, HUNDRED) if concentration_hhi is not None else None,
        }
    )
    components.append(
        {
            "name": "risk_contribution_balance", "weight": Decimal("9"),
            "score": (
                _clamp(HUNDRED - risk_contribution_stdev_percent * Decimal("2"), ZERO, HUNDRED)
                if risk_contribution_stdev_percent is not None else None
            ),
        }
    )
    components.append(
        {
            "name": "portfolio_drawdown", "weight": Decimal("13"),
            "score": (
                _clamp(HUNDRED - portfolio_mdd_percent * Decimal("1.5"), ZERO, HUNDRED)
                if portfolio_mdd_percent is not None else None
            ),
        }
    )
    components.append(
        {
            "name": "strategy_count", "weight": Decimal("5"),
            "score": _clamp(
                (Decimal(strategy_count - MIN_STRATEGIES) / Decimal(MAX_STRATEGIES - MIN_STRATEGIES)) * HUNDRED,
                ZERO, HUNDRED,
            ),
        }
    )
    if duplicate_exposure_severities:
        if "HIGH" in duplicate_exposure_severities:
            exposure_score = Decimal("20")
        elif "WARNING" in duplicate_exposure_severities:
            exposure_score = Decimal("50")
        else:
            exposure_score = Decimal("80")
    else:
        exposure_score = HUNDRED
    components.append({"name": "duplicate_exposure_severity", "weight": Decimal("9"), "score": exposure_score})
    components.append(
        {
            "name": "valid_observation_ratio", "weight": Decimal("11"),
            "score": _clamp(valid_observation_ratio_percent, ZERO, HUNDRED) if valid_observation_ratio_percent is not None else None,
        }
    )

    available = [c for c in components if c["score"] is not None]
    breakdown = [
        {"name": c["name"], "weight": c["weight"], "component_score": c["score"], "included": c["score"] is not None}
        for c in components
    ]
    total_weight = sum((c["weight"] for c in available), ZERO)
    if total_weight == ZERO:
        return {"score": None, "breakdown": breakdown}
    weighted = sum((c["score"] * c["weight"] for c in available), ZERO)
    return {"score": (weighted / total_weight).quantize(Decimal("0.01")), "breakdown": breakdown}


# ---------------------------------------------------------------------------
# Portfolio Validation Status.
# ---------------------------------------------------------------------------


def determine_validation_status(
    *,
    observation_count: int,
    robustness_score: Decimal | None,
    portfolio_mdd_percent: Decimal | None,
    risk_contribution_max_percent: Decimal | None,
    duplicate_exposure_severities: list[str],
    average_pairwise_correlation: Decimal | None,
    diversification_benefit: Decimal | None,
    concentration_status: str,
) -> tuple[str, dict[str, Any]]:
    reason: dict[str, Any] = {
        "observation_count": observation_count, "robustness_score": robustness_score,
    }
    if observation_count < MIN_VALID_OBSERVATIONS_FOR_ANALYSIS or robustness_score is None:
        reason["basis"] = f"관측 수({observation_count})가 최소 기준({MIN_VALID_OBSERVATIONS_FOR_ANALYSIS}) 미만이거나 Robustness Score 계산 불가"
        return "INSUFFICIENT_DATA", reason

    high_exposure_count = sum(1 for s in duplicate_exposure_severities if s == "HIGH")
    if (
        (portfolio_mdd_percent is not None and portfolio_mdd_percent >= Decimal("50"))
        or (risk_contribution_max_percent is not None and risk_contribution_max_percent >= Decimal("70"))
        or high_exposure_count >= 2
    ):
        reason["basis"] = "Portfolio MDD>=50% 또는 단일 전략 Risk Contribution>=70% 또는 HIGH 중복 노출 2건 이상"
        return "HIGH_RISK", reason

    if (
        (average_pairwise_correlation is not None and average_pairwise_correlation >= Decimal("0.7"))
        or (diversification_benefit is not None and diversification_benefit <= Decimal("0.05"))
    ):
        reason["basis"] = "평균 상관관계>=0.7 또는 Diversification Benefit<=5%"
        return "HIGHLY_CORRELATED", reason

    if concentration_status == "HIGH":
        reason["basis"] = "Concentration Status=HIGH"
        return "CONCENTRATED", reason

    if (
        robustness_score >= Decimal("70")
        and (average_pairwise_correlation is not None and average_pairwise_correlation < Decimal("0.4"))
        and (diversification_benefit is not None and diversification_benefit > Decimal("0.15"))
        and concentration_status == "LOW"
    ):
        reason["basis"] = "Robustness Score>=70, 낮은 상관관계, 양호한 Diversification Benefit, 낮은 Concentration"
        return "DIVERSIFIED", reason

    reason["basis"] = "일부 위험 요인이 있으나 전체적으로 허용 가능한 수준"
    return "ACCEPTABLE", reason


# ---------------------------------------------------------------------------
# Provenance / Input Hash.
# ---------------------------------------------------------------------------


def compute_report_input_hash(
    *,
    strategy_definition_ids: list[int],
    backtest_run_ids: list[int],
    executable_hashes: dict[int, str],
    runtime_input_hashes: dict[int, str],
    equity_curve_hashes: dict[int, str],
    weights: dict[int, Decimal],
    weighting_method: str,
    alignment_policy: str,
    common_start_date: date,
    common_end_date: date,
    observation_count: int,
    minimum_overlap_days: int,
    initial_capital: Decimal,
    correlation_threshold: Decimal,
    concentration_threshold: Decimal,
) -> str:
    """이 해시가 다르면 실제로 산출된 Report 내용도 달라져야 한다(재현성
    기준). initial_capital은 Portfolio Equity/Drawdown 절대값에, 나머지
    threshold들은 Concentration/Duplicate Exposure/Validation Status
    판정에 직접 영향을 주므로 전부 포함한다 — 그렇지 않으면 서로 다른
    입력의 두 요청이 같은 idempotency_key 아래 같은 해시로 충돌 감지를
    피해가며 Report를 오검증(재사용)할 수 있다."""
    ordered = sorted(strategy_definition_ids)
    canonical = {
        "strategy_definition_ids": ordered,
        "backtest_run_ids": [
            next(bid for sid, bid in zip(strategy_definition_ids, backtest_run_ids) if sid == s) for s in ordered
        ],
        "executable_hashes": {str(s): executable_hashes[s] for s in ordered},
        "runtime_input_hashes": {str(s): runtime_input_hashes[s] for s in ordered},
        "equity_curve_hashes": {str(s): equity_curve_hashes[s] for s in ordered},
        "weights": {str(s): str(weights[s]) for s in ordered},
        "weighting_method": weighting_method,
        "alignment_policy": alignment_policy,
        "common_start_date": common_start_date.isoformat(),
        "common_end_date": common_end_date.isoformat(),
        "observation_count": observation_count,
        "minimum_overlap_days": minimum_overlap_days,
        "initial_capital": str(initial_capital),
        "correlation_threshold": str(correlation_threshold),
        "concentration_threshold": str(concentration_threshold),
        "algorithm_version": ALGORITHM_VERSION,
    }
    return _hash(_canonical_json(canonical))


def compute_equity_curve_hash(dates: list[date], equities: list[Decimal]) -> str:
    canonical = {"dates": [d.isoformat() for d in dates], "equities": [str(e) for e in equities]}
    return _hash(_canonical_json(canonical))


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def run_portfolio_validation(
    session: Session,
    *,
    strategy_definition_ids: list[int],
    backtest_run_ids: list[int],
    weighting_method: str,
    strategy_weights: dict[int, Decimal] | None,
    alignment_policy: str,
    minimum_overlap_days: int,
    initial_capital: Decimal,
    correlation_threshold: Decimal,
    concentration_threshold: Decimal,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    validate_strategy_count_and_uniqueness(strategy_definition_ids, backtest_run_ids)

    bundles = [
        validate_and_load_strategy(session, strategy_definition_id=sid, backtest_run_id=bid)
        for sid, bid in zip(strategy_definition_ids, backtest_run_ids)
    ]
    weights = resolve_weights(
        strategy_definition_ids=strategy_definition_ids, weighting_method=weighting_method,
        strategy_weights=strategy_weights,
    )

    common_dates, aligned_equities = align_equity_curves(
        bundles=bundles, alignment_policy=alignment_policy, minimum_overlap_days=minimum_overlap_days,
    )

    executable_hashes = {b.strategy_definition_id: b.executable_hash for b in bundles}
    runtime_input_hashes = {b.strategy_definition_id: b.runtime_input_hash for b in bundles}
    equity_curve_hashes = {
        b.strategy_definition_id: compute_equity_curve_hash(common_dates, aligned_equities[b.strategy_definition_id])
        for b in bundles
    }

    report_input_hash = compute_report_input_hash(
        strategy_definition_ids=strategy_definition_ids, backtest_run_ids=backtest_run_ids,
        executable_hashes=executable_hashes, runtime_input_hashes=runtime_input_hashes,
        equity_curve_hashes=equity_curve_hashes, weights=weights, weighting_method=weighting_method,
        alignment_policy=alignment_policy, common_start_date=common_dates[0], common_end_date=common_dates[-1],
        observation_count=len(common_dates), minimum_overlap_days=minimum_overlap_days,
        initial_capital=initial_capital, correlation_threshold=correlation_threshold,
        concentration_threshold=concentration_threshold,
    )

    if idempotency_key:
        existing = session.scalar(
            select(PortfolioValidationReportEntity).where(
                PortfolioValidationReportEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.report_input_hash == report_input_hash:
                return _to_report_dict(existing, idempotent_replay=True)
            raise PortfolioValidationError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 요청 내용으로 사용되었습니다."
            )

    strategy_returns = {sid: compute_return_series(aligned_equities[sid]) for sid in aligned_equities}
    portfolio_returns = compute_portfolio_returns(strategy_returns=strategy_returns, weights=weights)
    portfolio_curve = compute_portfolio_equity_curve(
        initial_capital=initial_capital, portfolio_returns=portfolio_returns, dates=common_dates,
    )
    portfolio_kpi = compute_portfolio_kpi(portfolio_curve, initial_capital)

    standalone_kpi = {
        sid: compute_standalone_kpi_for_strategy(aligned_equities[sid], common_dates) for sid in aligned_equities
    }
    standalone_volatility = {
        sid: (_stdev_population(strategy_returns[sid]) * _sqrt(Decimal(252)) * HUNDRED) for sid in strategy_returns
    }
    standalone_mdd = {sid: standalone_kpi[sid]["maximum_drawdown_percent"] for sid in standalone_kpi}

    correlation = compute_correlation_matrix(strategy_definition_ids, strategy_returns)
    highly_correlated = find_highly_correlated_pairs(correlation["pairs"], correlation_threshold=correlation_threshold)

    concentration = compute_concentration(weights, concentration_threshold=concentration_threshold)
    risk_contribution = compute_risk_contribution(strategy_definition_ids, weights, strategy_returns)

    portfolio_volatility_pct = (
        _stdev_population(portfolio_returns) * _sqrt(Decimal(252)) * HUNDRED
    ).quantize(Decimal("0.0001")) if len(portfolio_returns) >= 2 else None

    diversification = compute_diversification_benefit(
        weights=weights, standalone_volatility=standalone_volatility, portfolio_volatility=portfolio_volatility_pct,
        standalone_mdd=standalone_mdd, portfolio_mdd=portfolio_kpi["maximum_drawdown_percent"],
    )

    duplicate_exposures = detect_duplicate_exposures(
        bundles, correlation_pairs=correlation["pairs"], correlation_threshold=correlation_threshold,
    )
    exposure_severities = [e["severity"] for e in duplicate_exposures]

    risk_pcts = [
        Decimal(str(c["risk_contribution_percent"])) for c in risk_contribution["contributions"]
        if c["risk_contribution_percent"] is not None
    ]
    risk_contribution_stdev = _stdev_population(risk_pcts) if len(risk_pcts) >= 2 else None
    risk_contribution_max = max(risk_pcts) if risk_pcts else None

    union_dates: set[date] = set()
    for b in bundles:
        union_dates.update(p.trade_date for p in b.equity_curve)
    valid_observation_ratio = (
        (Decimal(len(common_dates)) / Decimal(len(union_dates)) * HUNDRED).quantize(Decimal("0.01"))
        if union_dates else None
    )

    robustness = compute_portfolio_robustness_score(
        diversification_benefit=diversification["diversification_benefit"],
        average_pairwise_correlation=correlation["average_pairwise_correlation"],
        maximum_pairwise_correlation=correlation["maximum_pairwise_correlation"],
        concentration_hhi=concentration["herfindahl_hirschman_index"],
        risk_contribution_stdev_percent=risk_contribution_stdev,
        portfolio_mdd_percent=portfolio_kpi["maximum_drawdown_percent"],
        strategy_count=len(strategy_definition_ids),
        duplicate_exposure_severities=exposure_severities,
        valid_observation_ratio_percent=valid_observation_ratio,
    )

    status, status_reason = determine_validation_status(
        observation_count=len(portfolio_returns), robustness_score=robustness["score"],
        portfolio_mdd_percent=portfolio_kpi["maximum_drawdown_percent"], risk_contribution_max_percent=risk_contribution_max,
        duplicate_exposure_severities=exposure_severities,
        average_pairwise_correlation=correlation["average_pairwise_correlation"],
        diversification_benefit=diversification["diversification_benefit"],
        concentration_status=concentration["concentration_status"],
    )

    existing_validation_summary = _load_existing_validation_summary(session, strategy_definition_ids)

    provenance_payload = {
        "strategy_definition_ids": sorted(strategy_definition_ids),
        "backtest_run_ids": backtest_run_ids,
        "executable_hashes": executable_hashes,
        "runtime_input_hashes": runtime_input_hashes,
        "equity_curve_hashes": equity_curve_hashes,
    }

    report = PortfolioValidationReportEntity(
        strategy_definition_ids=_to_jsonable(sorted(strategy_definition_ids)),
        backtest_run_ids=_to_jsonable(backtest_run_ids),
        weighting_method=weighting_method,
        alignment_policy=alignment_policy,
        common_start_date=common_dates[0],
        common_end_date=common_dates[-1],
        observation_count=len(portfolio_returns),
        strategy_count=len(strategy_definition_ids),
        robustness_score=robustness["score"],
        validation_status=status,
        weights_payload=_to_jsonable({str(k): v for k, v in weights.items()}),
        common_period_payload=_to_jsonable(
            {
                "start_date": common_dates[0].isoformat(),
                "end_date": common_dates[-1].isoformat(),
                "observation_count": len(portfolio_returns),
            }
        ),
        portfolio_kpi_payload=_to_jsonable(portfolio_kpi),
        correlation_payload=_to_jsonable(
            {**correlation, "highly_correlated_pairs": highly_correlated, "correlation_threshold": correlation_threshold}
        ),
        concentration_payload=_to_jsonable(concentration),
        risk_contribution_payload=_to_jsonable(risk_contribution),
        diversification_payload=_to_jsonable(diversification),
        duplicate_exposure_payload=_to_jsonable(duplicate_exposures),
        portfolio_equity_payload=_to_jsonable(
            [{"trade_date": p.trade_date.isoformat(), "equity_value": p.equity_value} for p in portfolio_curve]
        ),
        existing_validation_summary_payload=_to_jsonable(existing_validation_summary),
        robustness_breakdown_payload=_to_jsonable(robustness["breakdown"]),
        status_reason_payload=_to_jsonable(status_reason),
        provenance_payload=_to_jsonable(provenance_payload),
        algorithm_version=ALGORITHM_VERSION,
        report_input_hash=report_input_hash,
        idempotency_key=(idempotency_key or None),
        requested_by=actor,
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    return _to_report_dict(report, idempotent_replay=False)


def _load_existing_validation_summary(session: Session, strategy_definition_ids: list[int]) -> dict[str, Any]:
    """§ 기존 검증 결과 연계 — 각 Strategy의 최신 Quality Gate/Parameter
    Sensitivity/Monte Carlo 결과가 있으면 조회해 요약에 포함한다(수정하지
    않음, 자동 Promotion에 사용하지 않음). 없으면 임의 PASS 대신
    NOT_AVAILABLE로 명시한다."""

    from sqlalchemy import select as _select

    from stock_platform.ai.strategy_draft_approval.monte_carlo_entities import (
        MonteCarloSimulationReportEntity,
    )
    from stock_platform.ai.strategy_draft_approval.parameter_sensitivity_entities import (
        ParameterSensitivityReportEntity,
    )
    from stock_platform.ai.strategy_draft_approval.quality_gate_entities import (
        StrategyQualityGateReportEntity,
    )

    summary: dict[str, Any] = {}
    for sid in sorted(strategy_definition_ids):
        quality_gate = session.scalar(
            _select(StrategyQualityGateReportEntity)
            .where(StrategyQualityGateReportEntity.strategy_id == sid)
            .order_by(StrategyQualityGateReportEntity.quality_gate_report_id.desc())
            .limit(1)
        )
        sensitivity = session.scalar(
            _select(ParameterSensitivityReportEntity)
            .where(ParameterSensitivityReportEntity.strategy_id == sid)
            .order_by(ParameterSensitivityReportEntity.parameter_sensitivity_report_id.desc())
            .limit(1)
        )
        monte_carlo = session.scalar(
            _select(MonteCarloSimulationReportEntity)
            .where(MonteCarloSimulationReportEntity.strategy_id == sid)
            .order_by(MonteCarloSimulationReportEntity.monte_carlo_report_id.desc())
            .limit(1)
        )
        summary[str(sid)] = {
            "quality_gate_recommendation": quality_gate.recommendation if quality_gate else "NOT_AVAILABLE",
            "parameter_sensitivity_status": sensitivity.sensitivity_status if sensitivity else "NOT_AVAILABLE",
            "monte_carlo_status": monte_carlo.monte_carlo_status if monte_carlo else "NOT_AVAILABLE",
        }
    return summary


def _to_report_dict(report: PortfolioValidationReportEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "portfolio_validation_report_id": int(report.portfolio_validation_report_id),
        "strategy_definition_ids": report.strategy_definition_ids,
        "backtest_run_ids": report.backtest_run_ids,
        "weighting_method": report.weighting_method,
        "alignment_policy": report.alignment_policy,
        "common_start_date": report.common_start_date,
        "common_end_date": report.common_end_date,
        "observation_count": report.observation_count,
        "strategy_count": report.strategy_count,
        "robustness_score": report.robustness_score,
        "validation_status": report.validation_status,
        "weights_payload": report.weights_payload,
        "common_period_payload": report.common_period_payload,
        "portfolio_kpi_payload": report.portfolio_kpi_payload,
        "correlation_payload": report.correlation_payload,
        "concentration_payload": report.concentration_payload,
        "risk_contribution_payload": report.risk_contribution_payload,
        "diversification_payload": report.diversification_payload,
        "duplicate_exposure_payload": report.duplicate_exposure_payload,
        "portfolio_equity_payload": report.portfolio_equity_payload,
        "existing_validation_summary_payload": report.existing_validation_summary_payload,
        "robustness_breakdown_payload": report.robustness_breakdown_payload,
        "status_reason_payload": report.status_reason_payload,
        "provenance_payload": report.provenance_payload,
        "algorithm_version": report.algorithm_version,
        "report_input_hash": report.report_input_hash,
        "requested_by": report.requested_by,
        "created_at": report.created_at,
        "idempotent_replay": idempotent_replay,
        "methodology_note": METHODOLOGY_NOTE,
    }


def get_portfolio_validation_report(session: Session, report_id: int) -> dict[str, Any]:
    report = session.get(PortfolioValidationReportEntity, report_id)
    if report is None:
        raise PortfolioValidationError("NOT_FOUND", f"Portfolio Validation report not found: {report_id}")
    return _to_report_dict(report, idempotent_replay=False)


def get_portfolio_validation_summary(session: Session, report_id: int) -> dict[str, Any]:
    report = get_portfolio_validation_report(session, report_id)
    return {
        "portfolio_validation_report_id": report["portfolio_validation_report_id"],
        "validation_status": report["validation_status"],
        "robustness_score": report["robustness_score"],
        "strategy_count": report["strategy_count"],
        "portfolio_kpi": report["portfolio_kpi_payload"],
        "concentration": report["concentration_payload"],
        "diversification": report["diversification_payload"],
        "methodology_note": report["methodology_note"],
    }


def get_portfolio_validation_correlations(session: Session, report_id: int) -> dict[str, Any]:
    report = get_portfolio_validation_report(session, report_id)
    return {
        "portfolio_validation_report_id": report["portfolio_validation_report_id"],
        "correlations": report["correlation_payload"],
    }


def get_portfolio_validation_risk_contributions(session: Session, report_id: int) -> dict[str, Any]:
    report = get_portfolio_validation_report(session, report_id)
    return {
        "portfolio_validation_report_id": report["portfolio_validation_report_id"],
        "risk_contributions": report["risk_contribution_payload"],
    }


def get_portfolio_validation_exposures(session: Session, report_id: int) -> dict[str, Any]:
    report = get_portfolio_validation_report(session, report_id)
    return {
        "portfolio_validation_report_id": report["portfolio_validation_report_id"],
        "duplicate_exposures": report["duplicate_exposure_payload"],
    }
