"""STEP 12-12 — Monte Carlo Simulation.

이미 완료된 Backtest의 실제 Trade 손익(Fee/Slippage 반영 완료,
`net_profit_loss`)만 메모리에서 확률적으로 재표본화(순서 셔플/복원 추출/
Block 복원 추출)해 손익 분포/Drawdown 분포/Risk of Ruin/신뢰구간을
평가한다. 새로운 매매 신호를 생성하지 않고, 새로운 Backtest를 실행하지
않으며, Strategy Definition을 수정하지 않는다.

재사용(중복 생성 금지 확인):
- Trade 데이터: 기존 `BacktestRepository.get_run()/get_trades()`만
  재사용(신규 Repository 없음). `net_profit_loss`(Fee/Tax 이미 차감된
  실현 손익, engine.py 확인)를 그대로 사용 — 재차감하지 않는다.
- Provenance 검증: 기존 STEP12-5 `check_readiness()`/`validate_provenance()`
  재사용(새 검증기 없음).
- 저장: 기존 3개 STEP(12-7/12-10/12-11)의 저장 구조 전부가 이번 STEP의
  내용(Percentile/Confidence Interval/대표 Simulation/Risk of Ruin/
  Robustness Score)과 스키마 목적이 달라 최소 전용 불변 테이블 1개만
  추가(§ 완료보고 Migration 항목).

RNG: 전역 `random` 모듈 상태를 오염시키지 않도록 `random.Random(seed)`
전용 인스턴스만 사용한다(numpy는 이 프로젝트 src 어디에도 사용되지 않고
requirements_step34.txt에만 부수적으로 선언돼 있어, 신규 대형 의존성
추가를 피하기 위해 도입하지 않는다 — 조사 결과, § 완료보고 3번 항목).

execution_input_hash/report_input_hash 구분(STEP12-11에서 배운 교훈을
반영): `trade_pnl_hash`(원본 Trade 순서+값의 해시)와 `report_input_hash`
(전체 요청의 해시, Strategy/Backtest/Hash/Policy/Algorithm Version 전부
포함)는 서로 다른 개념으로 명확히 분리해 둘 다 저장한다.

STEP12-12 보완(STEP12-13 착수 전 인수 조건으로 지적됨, ALGORITHM_VERSION
1.0.0 -> 1.1.0):
1. Method-aware Robustness Score — TRADE_ORDER_SHUFFLE은 Trade P&L
   합계가 항상 동일해(순서만 바뀜) Final Equity/Total Return/그 신뢰구간이
   전 Simulation에서 사실상 동일하거나 정보량이 없다. 이 Method에서는
   해당 경로-비의존 컴포넌트를 제외하고 Risk of Ruin/Maximum Drawdown
   Tail/Consecutive Loss Tail/Worst-case Recovery/Valid Simulation Ratio
   5개 경로-의존 컴포넌트로 가중치를 재정규화한다(§ compute_robustness_score).
2. Representative Equity Curve — 기존에는 시작/끝/최고/최저 4개 숫자
   요약값만 저장해 "실제 Curve"가 아니었다. Worst/Median/Best 3개
   Simulation에 한해 실제 거래 순서별 Equity Curve를 결정적으로
   재현(§ _replay_equity_curve, 같은 Seed로 해당 Simulation Index까지만
   재실행 — 전체 Simulation의 재표본화 결과를 메모리에 들고 있지 않아도
   됨)하고, Trade 수가 많으면 정책이 명시된 결정적 Downsampling을 적용한다
   (§ _downsample_curve).
3. Idempotency Conflict — 동일 idempotency_key라도 실제 요청 내용
   (report_input_hash)이 다르면 과거 Report를 그대로 반환하지 않고
   IDEMPOTENCY_CONFLICT로 차단한다.
4. Backtest 상태 검증 — status_code(이 프로젝트의 실제 완료 표시값은
   'SUCCESS')/executable_hash/runtime_input_hash 존재를 실행 전 명시적으로
   검증한다.
5. Decimal 정규화 — 해시/저장 payload 전부 `str(Decimal(...))` 또는
   `_to_jsonable()`을 거치며 `float()` 변환은 이 파일 어디에도 없음을
   재확인(grep으로 검증, 수정 불필요)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.monte_carlo_entities import (
    MonteCarloSimulationReportEntity,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    check_readiness,
)
from stock_platform.backtest.persistence_models import BacktestRunEntity, BacktestTradeEntity
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.performance.backtest_analytics import _to_jsonable

ALGORITHM_VERSION = "1.1.0"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
# STEP12-12 보완 §2 — 대표 Simulation Equity Curve 결정적 Downsampling 상한.
MAX_CURVE_POINTS = 200

SUPPORTED_METHODS = frozenset(
    {"TRADE_ORDER_SHUFFLE", "BOOTSTRAP_WITH_REPLACEMENT", "BLOCK_BOOTSTRAP"}
)
ALLOWED_CONFIDENCE_LEVELS = frozenset({Decimal("0.90"), Decimal("0.95"), Decimal("0.99")})

MIN_TRADE_COUNT = 5
SIMULATION_COUNT_MIN = 100
SIMULATION_COUNT_DEFAULT = 1000
SIMULATION_COUNT_MAX = 10000
RANDOM_SEED_DEFAULT = 42
CONFIDENCE_LEVEL_DEFAULT = Decimal("0.95")
RUIN_THRESHOLD_PERCENT_DEFAULT = Decimal("50")
BLOCK_SIZE_DEFAULT = 5
MIN_VALID_SIMULATIONS_FOR_ANALYSIS = 30

_PERCENTILES: tuple[Decimal, ...] = (
    Decimal("1"), Decimal("5"), Decimal("10"), Decimal("25"), Decimal("50"),
    Decimal("75"), Decimal("90"), Decimal("95"), Decimal("99"),
)


class MonteCarloError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Input Validation — 전부 사전 검증(구조적 오류는 Simulation Loop 진입 전
# 즉시 차단, §Failure 처리).
# ---------------------------------------------------------------------------


def validate_simulation_inputs(
    *,
    simulation_method: str,
    simulation_count: int,
    confidence_level: Decimal,
    ruin_threshold_percent: Decimal,
    block_size: int,
    random_seed: int,
    trade_count: int,
) -> None:
    if simulation_method not in SUPPORTED_METHODS:
        raise MonteCarloError("UNSUPPORTED_METHOD", f"지원하지 않는 Simulation Method입니다: {simulation_method}")
    if not isinstance(random_seed, int) or isinstance(random_seed, bool):
        raise MonteCarloError("INVALID_RANDOM_SEED", "random_seed는 정수여야 합니다.")
    if not (SIMULATION_COUNT_MIN <= simulation_count <= SIMULATION_COUNT_MAX):
        raise MonteCarloError(
            "INVALID_SIMULATION_COUNT",
            f"simulation_count는 {SIMULATION_COUNT_MIN}~{SIMULATION_COUNT_MAX} 사이여야 합니다"
            f"(요청: {simulation_count}).",
        )
    if confidence_level not in ALLOWED_CONFIDENCE_LEVELS:
        raise MonteCarloError(
            "INVALID_CONFIDENCE_LEVEL",
            f"confidence_level은 {sorted(ALLOWED_CONFIDENCE_LEVELS)} 중 하나여야 합니다.",
        )
    if not (Decimal("1") <= ruin_threshold_percent <= Decimal("99")):
        raise MonteCarloError(
            "INVALID_RUIN_THRESHOLD", "ruin_threshold_percent는 1 이상 99 이하여야 합니다."
        )
    if simulation_method == "BLOCK_BOOTSTRAP":
        if block_size < 1 or block_size > trade_count:
            raise MonteCarloError(
                "INVALID_BLOCK_SIZE",
                f"block_size는 1 이상 Trade Count({trade_count}) 이하여야 합니다(요청: {block_size}).",
            )
    if trade_count < MIN_TRADE_COUNT:
        raise MonteCarloError(
            "INSUFFICIENT_TRADES", f"Trade Count가 최소 기준({MIN_TRADE_COUNT}) 미만입니다(실제: {trade_count})."
        )


# ---------------------------------------------------------------------------
# Trade P&L Extraction — 우선순위: net_profit_loss(이 프로젝트의 실제
# 필드, Fee/Tax 이미 반영됨. realized_profit_loss/pnl_after_fee는 이
# 프로젝트에 존재하지 않아 폴백 대상이 없음을 확인).
# ---------------------------------------------------------------------------


def extract_trade_pnls(trades: list[BacktestTradeEntity]) -> list[Decimal]:
    """`BacktestRepository.get_trades()`가 이미 `trade_no` 오름차순으로
    반환하므로 원본 실행 순서 그대로 사용한다(재정렬하지 않음)."""
    return [Decimal(t.net_profit_loss) for t in trades]


def compute_trade_pnl_hash(pnls: list[Decimal]) -> str:
    """원본 순서와 값을 모두 반영한다(TRADE_ORDER_SHUFFLE이어도 원본
    순서 기준 Hash를 저장 — Provenance는 항상 원본을 가리켜야 한다)."""
    canonical = {"trade_pnls": [str(p) for p in pnls]}
    return _hash(_canonical_json(canonical))


# ---------------------------------------------------------------------------
# Resampling Methods — 전용 RNG 인스턴스만 사용(전역 random 상태 미오염).
# ---------------------------------------------------------------------------


def shuffle_trades(rng: random.Random, pnls: list[Decimal]) -> list[Decimal]:
    result = list(pnls)
    rng.shuffle(result)
    return result


def bootstrap_trades(rng: random.Random, pnls: list[Decimal]) -> list[Decimal]:
    n = len(pnls)
    return [pnls[rng.randrange(n)] for _ in range(n)]


def block_bootstrap_trades(rng: random.Random, pnls: list[Decimal], block_size: int) -> list[Decimal]:
    """순환(wrap-around) Block Bootstrap — 모든 위치가 동일한 확률로
    Block 시작점이 될 수 있도록 원형으로 취급한다(끝 부분 근처 시작점이
    불리해지는 경계 편향을 피하기 위한 문서화된 설계 선택)."""
    n = len(pnls)
    result: list[Decimal] = []
    while len(result) < n:
        start = rng.randrange(n)
        result.extend(pnls[(start + i) % n] for i in range(block_size))
    return result[:n]


def resample_trades(
    rng: random.Random, pnls: list[Decimal], *, simulation_method: str, block_size: int
) -> list[Decimal]:
    if simulation_method == "TRADE_ORDER_SHUFFLE":
        return shuffle_trades(rng, pnls)
    if simulation_method == "BOOTSTRAP_WITH_REPLACEMENT":
        return bootstrap_trades(rng, pnls)
    if simulation_method == "BLOCK_BOOTSTRAP":
        return block_bootstrap_trades(rng, pnls, block_size)
    raise MonteCarloError("UNSUPPORTED_METHOD", f"지원하지 않는 Simulation Method입니다: {simulation_method}")


# ---------------------------------------------------------------------------
# 개별 Simulation의 Equity Path 계산 — 매 시점 running peak 대비 Drawdown을
# 계산한다(Look-ahead 없음 — 각 시점까지의 누적 손익만 사용).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimulationPath:
    simulation_index: int
    final_equity: Decimal
    peak_equity: Decimal
    lowest_equity: Decimal
    maximum_drawdown_amount: Decimal
    maximum_drawdown_percent: Decimal
    total_return: Decimal
    consecutive_losses: int
    ruin: bool
    recovery: bool


def simulate_path(
    simulation_index: int, initial_capital: Decimal, pnls: list[Decimal], *, ruin_equity_threshold: Decimal
) -> SimulationPath:
    equity = initial_capital
    peak = initial_capital
    lowest = initial_capital
    max_dd_amount = ZERO
    max_dd_percent = ZERO
    consecutive_losses = 0
    max_consecutive_losses = 0

    for pnl in pnls:
        equity = equity + pnl
        if equity > peak:
            peak = equity
        if equity < lowest:
            lowest = equity
        dd_amount = peak - equity
        if dd_amount > max_dd_amount:
            max_dd_amount = dd_amount
        if peak > ZERO:
            dd_percent = dd_amount / peak * HUNDRED
            if dd_percent > max_dd_percent:
                max_dd_percent = dd_percent
        if pnl < ZERO:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0

    total_return = (
        (equity - initial_capital) / initial_capital * HUNDRED if initial_capital > ZERO else ZERO
    ).quantize(Decimal("0.0001"))
    max_dd_percent = max_dd_percent.quantize(Decimal("0.0001"))
    ruin = lowest <= ruin_equity_threshold
    # Recovery 정의(문서화): 이 Simulation 경로가 끝날 때 자산이 그 경로
    # 안에서 도달했던 사상 최고점(peak_equity) 이상으로 복귀했는가.
    recovery = equity >= peak

    return SimulationPath(
        simulation_index=simulation_index, final_equity=equity, peak_equity=peak, lowest_equity=lowest,
        maximum_drawdown_amount=max_dd_amount, maximum_drawdown_percent=max_dd_percent,
        total_return=total_return, consecutive_losses=max_consecutive_losses, ruin=ruin, recovery=recovery,
    )


def run_simulations(
    *,
    rng: random.Random,
    pnls: list[Decimal],
    initial_capital: Decimal,
    simulation_method: str,
    simulation_count: int,
    block_size: int,
    ruin_equity_threshold: Decimal,
) -> tuple[list[SimulationPath], list[dict[str, Any]]]:
    """DB 조회/Audit 기록 없이 순수 메모리 연산만 수행한다(§ 성능 요구사항
    — Simulation Loop 안에서 DB 조회 금지)."""
    paths: list[SimulationPath] = []
    failures: list[dict[str, Any]] = []
    for index in range(simulation_count):
        try:
            sampled = resample_trades(rng, pnls, simulation_method=simulation_method, block_size=block_size)
            paths.append(
                simulate_path(index, initial_capital, sampled, ruin_equity_threshold=ruin_equity_threshold)
            )
        except Exception as exc:  # noqa: BLE001 — 결정적 순수 연산이라 사실상 발생하지 않지만 방어적으로 fail-soft 처리
            failures.append({"simulation_index": index, "reason": str(exc)})
    return paths, failures


# ---------------------------------------------------------------------------
# Distribution / Percentile — 선형 보간(버전 의존 없는 결정적 자체 구현).
# ---------------------------------------------------------------------------


def percentile(sorted_values: list[Decimal], p: Decimal) -> Decimal:
    """선형 보간 백분위수. index = p/100*(n-1)의 정수부/소수부로 인접한 두
    값을 보간한다(numpy 기본 'linear' 방식과 동일한 정의를 자체 구현해
    라이브러리 버전에 따라 결과가 달라지지 않도록 한다)."""
    n = len(sorted_values)
    if n == 0:
        raise MonteCarloError("INSUFFICIENT_TRADES", "분포를 계산할 유효 Simulation이 없습니다.")
    if n == 1:
        return sorted_values[0]
    rank = (p / HUNDRED) * Decimal(n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    fraction = rank - Decimal(lower_idx)
    lower_val = sorted_values[lower_idx]
    upper_val = sorted_values[upper_idx]
    return lower_val + (upper_val - lower_val) * fraction


def compute_distribution(values: list[Decimal]) -> dict[str, Decimal]:
    ordered = sorted(values)
    return {f"P{int(p):02d}": percentile(ordered, p) for p in _PERCENTILES}


def compute_confidence_interval(values: list[Decimal], confidence_level: Decimal) -> tuple[Decimal, Decimal]:
    alpha = (Decimal("1") - confidence_level) / Decimal("2") * HUNDRED
    ordered = sorted(values)
    low = percentile(ordered, alpha)
    high = percentile(ordered, HUNDRED - alpha)
    return low, high


# ---------------------------------------------------------------------------
# Risk of Ruin.
# ---------------------------------------------------------------------------


def compute_risk_of_ruin(paths: list[SimulationPath]) -> dict[str, Any]:
    valid_count = len(paths)
    if valid_count == 0:
        return {
            "risk_of_ruin_percent": None, "ruin_simulation_count": 0, "valid_simulation_count": 0,
        }
    ruin_count = sum(1 for p in paths if p.ruin)
    return {
        "risk_of_ruin_percent": (Decimal(ruin_count) / Decimal(valid_count) * HUNDRED).quantize(Decimal("0.01")),
        "ruin_simulation_count": ruin_count,
        "valid_simulation_count": valid_count,
    }


# ---------------------------------------------------------------------------
# Worst / Median / Best Representative.
# ---------------------------------------------------------------------------


def select_representatives(paths: list[SimulationPath]) -> dict[str, dict[str, Any] | None]:
    """Worst/Median/Best 요약(숫자 지표)만 선택한다. 실제 거래 순서별
    Equity Curve는 이 함수의 책임이 아니다(§ _replay_equity_curve로 별도
    재현 — 이 함수는 어떤 simulation_index가 대표인지만 결정한다)."""
    if not paths:
        return {"worst": None, "median": None, "best": None}
    ordered = sorted(paths, key=lambda p: (p.final_equity, p.simulation_index))
    worst = ordered[0]
    best = ordered[-1]
    median = ordered[(len(ordered) - 1) // 2]

    def _to_dict(p: SimulationPath) -> dict[str, Any]:
        return {
            "simulation_index": p.simulation_index,
            "final_equity": p.final_equity,
            "total_return": p.total_return,
            "maximum_drawdown_percent": p.maximum_drawdown_percent,
            "consecutive_losses": p.consecutive_losses,
            "ruin": p.ruin,
        }

    return {"worst": _to_dict(worst), "median": _to_dict(median), "best": _to_dict(best)}


# ---------------------------------------------------------------------------
# STEP12-12 보완 §2 — 대표 Simulation의 실제 거래 순서별 Equity Curve.
# ---------------------------------------------------------------------------


def _replay_equity_curve_pnls(
    *, random_seed: int, pnls: list[Decimal], simulation_method: str, block_size: int, target_index: int
) -> list[Decimal]:
    """`target_index`번째 Simulation에서 실제로 사용된 재표본화 PnL
    시퀀스를 동일 Seed로 처음부터 재현한다. 전체 1000~10000개 Simulation의
    재표본화 결과를 메모리에 들고 있지 않고, 필요한 3개(Worst/Median/Best)
    에 대해서만 그 지점까지 RNG를 다시 소비해 정확히 동일한 결과를
    재현한다(결정적 — 동일 Seed는 항상 동일한 소비 순서를 만든다)."""
    rng = random.Random(random_seed)
    sampled: list[Decimal] = []
    for _ in range(target_index + 1):
        sampled = resample_trades(rng, pnls, simulation_method=simulation_method, block_size=block_size)
    return sampled


def _build_equity_curve(initial_capital: Decimal, sampled_pnls: list[Decimal]) -> list[dict[str, Any]]:
    curve: list[dict[str, Any]] = [{"trade_index": 0, "equity": initial_capital}]
    equity = initial_capital
    for idx, pnl in enumerate(sampled_pnls, start=1):
        equity = equity + pnl
        curve.append({"trade_index": idx, "equity": equity})
    return curve


def _downsample_curve(
    curve: list[dict[str, Any]], *, max_points: int = MAX_CURVE_POINTS
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """결정적 Downsampling — 첫 지점/마지막 지점/최저 Equity 지점/최고
    Equity 지점을 항상 포함하고, 남은 예산은 균등 간격(stride) 인덱스로
    채운다(동일 입력 -> 동일 결과, RNG 미사용)."""
    n = len(curve)
    if n <= max_points:
        return curve, {
            "applied": False, "max_points": max_points,
            "original_point_count": n, "sampled_point_count": n, "policy": None,
        }

    equities = [c["equity"] for c in curve]
    min_idx = min(range(n), key=lambda i: equities[i])
    max_idx = max(range(n), key=lambda i: equities[i])
    mandatory = {0, n - 1, min_idx, max_idx}
    remaining_budget = max(0, max_points - len(mandatory))
    if remaining_budget > 0 and n > 1:
        stride = Decimal(n - 1) / Decimal(remaining_budget + 1)
        for k in range(1, remaining_budget + 1):
            idx = int((stride * Decimal(k)).to_integral_value(rounding=ROUND_HALF_UP))
            mandatory.add(min(max(idx, 0), n - 1))
    selected_indices = sorted(mandatory)
    downsampled = [curve[i] for i in selected_indices]
    return downsampled, {
        "applied": True, "max_points": max_points,
        "original_point_count": n, "sampled_point_count": len(downsampled),
        "policy": "first+last+min_equity+max_equity+evenly_spaced_stride",
    }


def build_representative_curve_payload(
    *,
    random_seed: int,
    pnls: list[Decimal],
    initial_capital: Decimal,
    simulation_method: str,
    block_size: int,
    simulation_index: int,
) -> dict[str, Any]:
    sampled = _replay_equity_curve_pnls(
        random_seed=random_seed, pnls=pnls, simulation_method=simulation_method,
        block_size=block_size, target_index=simulation_index,
    )
    full_curve = _build_equity_curve(initial_capital, sampled)
    curve, downsampling = _downsample_curve(full_curve)
    return {"equity_curve": curve, "downsampling": downsampling}


# ---------------------------------------------------------------------------
# Monte Carlo Robustness Score.
# ---------------------------------------------------------------------------


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def compute_robustness_score(
    *,
    simulation_method: str,
    risk_of_ruin_percent: Decimal | None,
    p05_total_return: Decimal | None,
    median_total_return: Decimal | None,
    p95_max_drawdown_percent: Decimal | None,
    p95_consecutive_losses: Decimal | None,
    final_equity_ci_low: Decimal | None,
    final_equity_ci_high: Decimal | None,
    median_final_equity: Decimal | None,
    worst_case_recovery: bool | None,
    valid_simulation_ratio_percent: Decimal,
) -> dict[str, Any]:
    """0~100, Method-aware(§STEP12-12 보완 §1).

    TRADE_ORDER_SHUFFLE은 Trade P&L 합계가 순서와 무관하게 항상 동일해
    Final Equity/Total Return/그 신뢰구간이 전 Simulation에서 사실상
    동일하거나 정보량이 없다 — 이 Method에서는 경로-의존(path-dependent)
    컴포넌트 5개만 사용한다: Risk of Ruin 35 / Maximum Drawdown Tail(P95)
    25 / Consecutive Loss Tail(P95) 20 / Worst-case Recovery 15 / 유효
    Simulation 비율 5(가중치 합 100).

    BOOTSTRAP_WITH_REPLACEMENT/BLOCK_BOOTSTRAP은 복원 추출로 실제 손익
    합계 자체가 매 Simulation마다 달라져 분포 기반 정보가 유효하므로
    기존 7개 컴포넌트를 그대로 사용한다: Risk of Ruin 25 / P05 Total
    Return 20 / Median Total Return 15 / P95 Maximum Drawdown 15 / Final
    Equity 신뢰구간 폭 10 / Worst-case Recovery 10 / 유효 Simulation 비율 5.

    두 정책 모두 계산 불가 항목은 0점이 아니라 제외 후 재정규화(§STEP12-8
    ~11과 동일 원칙)."""

    components: list[dict[str, Any]] = []

    risk_of_ruin_score = (
        _clamp(HUNDRED - risk_of_ruin_percent * Decimal("2"), ZERO, HUNDRED)
        if risk_of_ruin_percent is not None else None
    )
    drawdown_tail_score = (
        _clamp(HUNDRED - p95_max_drawdown_percent * Decimal("1.5"), ZERO, HUNDRED)
        if p95_max_drawdown_percent is not None else None
    )
    recovery_score = (HUNDRED if worst_case_recovery else ZERO) if worst_case_recovery is not None else None
    valid_ratio_score = _clamp(valid_simulation_ratio_percent, ZERO, HUNDRED)

    if simulation_method == "TRADE_ORDER_SHUFFLE":
        consecutive_loss_score = (
            _clamp(HUNDRED - p95_consecutive_losses * Decimal("10"), ZERO, HUNDRED)
            if p95_consecutive_losses is not None else None
        )
        components = [
            {"name": "risk_of_ruin", "weight": Decimal("35"), "score": risk_of_ruin_score},
            {"name": "maximum_drawdown_tail", "weight": Decimal("25"), "score": drawdown_tail_score},
            {"name": "consecutive_loss_tail", "weight": Decimal("20"), "score": consecutive_loss_score},
            {"name": "worst_case_recovery", "weight": Decimal("15"), "score": recovery_score},
            {"name": "valid_simulation_ratio", "weight": Decimal("5"), "score": valid_ratio_score},
        ]
    else:
        components = [
            {"name": "risk_of_ruin", "weight": Decimal("25"), "score": risk_of_ruin_score},
            {
                "name": "p05_total_return", "weight": Decimal("20"),
                "score": (
                    _clamp((p05_total_return + Decimal("20")) / Decimal("40") * HUNDRED, ZERO, HUNDRED)
                    if p05_total_return is not None else None
                ),
            },
            {
                "name": "median_total_return", "weight": Decimal("15"),
                "score": (
                    _clamp((median_total_return + Decimal("10")) / Decimal("30") * HUNDRED, ZERO, HUNDRED)
                    if median_total_return is not None else None
                ),
            },
            {"name": "p95_maximum_drawdown", "weight": Decimal("15"), "score": drawdown_tail_score},
            {
                "name": "final_equity_ci_width", "weight": Decimal("10"),
                "score": (
                    _clamp(
                        HUNDRED - (final_equity_ci_high - final_equity_ci_low) / median_final_equity * Decimal("50"),
                        ZERO, HUNDRED,
                    )
                    if (
                        final_equity_ci_low is not None and final_equity_ci_high is not None
                        and median_final_equity is not None and median_final_equity > ZERO
                    )
                    else None
                ),
            },
            {"name": "worst_case_recovery", "weight": Decimal("10"), "score": recovery_score},
            {"name": "valid_simulation_ratio", "weight": Decimal("5"), "score": valid_ratio_score},
        ]

    available = [c for c in components if c["score"] is not None]
    breakdown = [
        {"name": c["name"], "weight": c["weight"], "component_score": c["score"], "included": c["score"] is not None}
        for c in components
    ]
    total_weight = sum((c["weight"] for c in available), ZERO)
    if total_weight == ZERO:
        return {"score": None, "breakdown": breakdown, "score_policy": simulation_method}
    weighted = sum((c["score"] * c["weight"] for c in available), ZERO)
    return {
        "score": (weighted / total_weight).quantize(Decimal("0.01")),
        "breakdown": breakdown,
        "score_policy": simulation_method,
    }


# ---------------------------------------------------------------------------
# Monte Carlo Status.
# ---------------------------------------------------------------------------


def determine_monte_carlo_status(
    *,
    valid_simulation_count: int,
    robustness_score: Decimal | None,
    risk_of_ruin_percent: Decimal | None,
    p05_total_return: Decimal | None,
    p95_max_drawdown_percent: Decimal | None,
) -> tuple[str, dict[str, Any]]:
    reason: dict[str, Any] = {
        "valid_simulation_count": valid_simulation_count,
        "robustness_score": robustness_score,
        "risk_of_ruin_percent": risk_of_ruin_percent,
        "p05_total_return": p05_total_return,
        "p95_maximum_drawdown_percent": p95_max_drawdown_percent,
    }
    if valid_simulation_count < MIN_VALID_SIMULATIONS_FOR_ANALYSIS or robustness_score is None:
        reason["basis"] = (
            f"유효 Simulation 수({valid_simulation_count})가 최소 기준"
            f"({MIN_VALID_SIMULATIONS_FOR_ANALYSIS}) 미만이거나 Robustness Score 계산 불가"
        )
        return "INSUFFICIENT_DATA", reason

    if (risk_of_ruin_percent is not None and risk_of_ruin_percent >= Decimal("20")) or (
        p05_total_return is not None and p05_total_return <= Decimal("-50")
    ):
        reason["basis"] = "Risk of Ruin>=20% 또는 P05 Total Return<=-50%"
        return "HIGH_RISK", reason

    if (
        robustness_score >= Decimal("75")
        and (risk_of_ruin_percent is not None and risk_of_ruin_percent < Decimal("2"))
        and (p05_total_return is not None and p05_total_return >= ZERO)
        and (p95_max_drawdown_percent is not None and p95_max_drawdown_percent <= Decimal("30"))
    ):
        reason["basis"] = "Robustness Score>=75, Risk of Ruin<2%, P05 Total Return>=0, P95 MDD<=30%"
        return "RESILIENT", reason

    if (
        robustness_score < Decimal("40")
        or (p05_total_return is not None and p05_total_return < Decimal("-20"))
        or (p95_max_drawdown_percent is not None and p95_max_drawdown_percent > Decimal("50"))
    ):
        reason["basis"] = "Robustness Score<40 또는 P05 Total Return<-20% 또는 P95 MDD>50%"
        return "FRAGILE", reason

    reason["basis"] = "중간 수준의 Robustness Score이며 극단적인 Tail Risk는 관측되지 않았습니다."
    return "ACCEPTABLE", reason


# ---------------------------------------------------------------------------
# Provenance / Input Hash.
# ---------------------------------------------------------------------------


def compute_report_input_hash(
    *,
    strategy_definition_id: int,
    backtest_run_id: int,
    executable_hash: str | None,
    runtime_input_hash: str | None,
    trade_pnl_hash: str,
    simulation_method: str,
    simulation_count: int,
    random_seed: int,
    confidence_level: Decimal,
    ruin_threshold_percent: Decimal,
    block_size: int,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "backtest_run_id": backtest_run_id,
        "executable_hash": executable_hash,
        "runtime_input_hash": runtime_input_hash,
        "trade_pnl_hash": trade_pnl_hash,
        "simulation_method": simulation_method,
        "simulation_count": simulation_count,
        "random_seed": random_seed,
        "confidence_level": str(confidence_level),
        "ruin_threshold_percent": str(ruin_threshold_percent),
        "block_size": block_size,
        "algorithm_version": ALGORITHM_VERSION,
    }
    return _hash(_canonical_json(canonical))


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def run_monte_carlo_simulation(
    session: Session,
    strategy_definition_id: int,
    *,
    backtest_run_id: int,
    simulation_method: str,
    actor: str,
    simulation_count: int = SIMULATION_COUNT_DEFAULT,
    random_seed: int = RANDOM_SEED_DEFAULT,
    confidence_level: Decimal = CONFIDENCE_LEVEL_DEFAULT,
    ruin_threshold_percent: Decimal = RUIN_THRESHOLD_PERCENT_DEFAULT,
    block_size: int = BLOCK_SIZE_DEFAULT,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    # Definition 존재/준비 상태 확인(Provenance) — 새 Backtest는 실행하지
    # 않지만, 이 Definition이 여전히 유효한 Provenance 체인을 갖는지는
    # 확인한다(기존 STEP12-5 재사용).
    try:
        readiness = check_readiness(session, strategy_definition_id)
    except ReadinessError as exc:
        raise MonteCarloError(exc.code, exc.message) from exc
    if not readiness["ready"]:
        raise MonteCarloError(
            "PROVENANCE_MISMATCH", "; ".join(readiness["failure_reasons"]) or "Definition이 준비되지 않았습니다."
        )

    repo = BacktestRepository(session)
    run = repo.get_run(backtest_run_id)
    if run is None:
        raise MonteCarloError("BACKTEST_RUN_NOT_FOUND", f"Backtest run not found: {backtest_run_id}")
    if run.strategy_definition_id != strategy_definition_id:
        raise MonteCarloError(
            "OWNERSHIP_MISMATCH",
            f"Backtest Run #{backtest_run_id}은 Strategy Definition #{strategy_definition_id}의 결과가 아닙니다.",
        )
    # § STEP12-12 보완 4 — Backtest 상태 검증. 이 프로젝트의 실제 완료
    # 표시값은 'SUCCESS'뿐이다(status_code에 다른 값이 기록되는 경로가
    # 없음을 조사로 확인) — "COMPLETED"라는 문자열을 임의로 새로 발명하지
    # 않고 기존 값 그대로 비교한다.
    if run.status_code != "SUCCESS":
        raise MonteCarloError(
            "BACKTEST_NOT_COMPLETED", f"Backtest Run #{backtest_run_id}이 완료 상태가 아닙니다({run.status_code})."
        )

    run_parameters = run.parameters or {}
    executable_hash = run_parameters.get("executable_hash")
    runtime_input_hash = run_parameters.get("runtime_input_hash")
    if not executable_hash:
        raise MonteCarloError(
            "EXECUTABLE_HASH_MISSING", f"Backtest Run #{backtest_run_id}에 executable_hash가 없습니다."
        )
    if not runtime_input_hash:
        raise MonteCarloError(
            "RUNTIME_INPUT_HASH_MISSING", f"Backtest Run #{backtest_run_id}에 runtime_input_hash가 없습니다."
        )

    trades = repo.get_trades(backtest_run_id)
    trade_count = len(trades)

    validate_simulation_inputs(
        simulation_method=simulation_method, simulation_count=simulation_count,
        confidence_level=confidence_level, ruin_threshold_percent=ruin_threshold_percent,
        block_size=block_size, random_seed=random_seed, trade_count=trade_count,
    )

    pnls = extract_trade_pnls(trades)
    trade_pnl_hash = compute_trade_pnl_hash(pnls)
    initial_capital = Decimal(run.initial_capital)
    ruin_equity_threshold = initial_capital * (Decimal("1") - ruin_threshold_percent / HUNDRED)

    # § STEP12-12 보완 3 — Idempotency Conflict. report_input_hash는
    # Simulation을 실행하지 않고도(Trade/Run/요청 파라미터만으로) 먼저
    # 계산할 수 있으므로, 실제 재표본화를 실행하기 전에 동일
    # idempotency_key의 기존 Report와 비교해 재실행/충돌/신규를 결정한다.
    report_input_hash = compute_report_input_hash(
        strategy_definition_id=strategy_definition_id, backtest_run_id=backtest_run_id,
        executable_hash=executable_hash, runtime_input_hash=runtime_input_hash,
        trade_pnl_hash=trade_pnl_hash, simulation_method=simulation_method,
        simulation_count=simulation_count, random_seed=random_seed, confidence_level=confidence_level,
        ruin_threshold_percent=ruin_threshold_percent, block_size=block_size,
    )
    if idempotency_key:
        existing = session.scalar(
            select(MonteCarloSimulationReportEntity).where(
                MonteCarloSimulationReportEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.report_input_hash == report_input_hash:
                return _to_report_dict(existing, idempotent_replay=True)
            raise MonteCarloError(
                "IDEMPOTENCY_CONFLICT",
                f"idempotency_key '{idempotency_key}'가 이미 다른 요청 내용으로 사용되었습니다.",
            )

    rng = random.Random(random_seed)
    paths, sim_failures = run_simulations(
        rng=rng, pnls=pnls, initial_capital=initial_capital, simulation_method=simulation_method,
        simulation_count=simulation_count, block_size=block_size, ruin_equity_threshold=ruin_equity_threshold,
    )

    valid_count = len(paths)
    failed_count = len(sim_failures)

    ruin_stats = compute_risk_of_ruin(paths)

    final_equities = [p.final_equity for p in paths]
    total_returns = [p.total_return for p in paths]
    drawdown_percents = [p.maximum_drawdown_percent for p in paths]
    consecutive_losses = [Decimal(p.consecutive_losses) for p in paths]

    percentile_payload = {
        "final_equity": compute_distribution(final_equities) if paths else None,
        "total_return": compute_distribution(total_returns) if paths else None,
        "maximum_drawdown_percent": compute_distribution(drawdown_percents) if paths else None,
        "consecutive_losses": compute_distribution(consecutive_losses) if paths else None,
    }

    if paths:
        fe_low, fe_high = compute_confidence_interval(final_equities, confidence_level)
        tr_low, tr_high = compute_confidence_interval(total_returns, confidence_level)
        confidence_interval_payload = {
            "confidence_level": confidence_level,
            "final_equity_confidence_low": fe_low, "final_equity_confidence_high": fe_high,
            "total_return_confidence_low": tr_low, "total_return_confidence_high": tr_high,
        }
    else:
        confidence_interval_payload = {
            "confidence_level": confidence_level,
            "final_equity_confidence_low": None, "final_equity_confidence_high": None,
            "total_return_confidence_low": None, "total_return_confidence_high": None,
        }

    representatives = select_representatives(paths)
    # § STEP12-12 보완 2 — 대표 3개 Simulation에 한해 실제 거래 순서별
    # Equity Curve를 결정적으로 재현해 붙인다(요약값이 아닌 실제 Curve).
    for rep in representatives.values():
        if rep is not None:
            curve_payload = build_representative_curve_payload(
                random_seed=random_seed, pnls=pnls, initial_capital=initial_capital,
                simulation_method=simulation_method, block_size=block_size,
                simulation_index=rep["simulation_index"],
            )
            rep["equity_curve"] = curve_payload["equity_curve"]
            rep["downsampling"] = curve_payload["downsampling"]

    median_total_return = percentile_payload["total_return"]["P50"] if paths else None
    p05_total_return = percentile_payload["total_return"]["P05"] if paths else None
    p95_drawdown = percentile_payload["maximum_drawdown_percent"]["P95"] if paths else None
    p95_consecutive_losses = percentile_payload["consecutive_losses"]["P95"] if paths else None
    median_final_equity = percentile_payload["final_equity"]["P50"] if paths else None

    # Worst-case Recovery: 대표 Worst Simulation의 원본 SimulationPath에서
    # recovery 플래그를 그대로 가져온다(representative_payload는 dict로
    # 축약돼 있어 원본 객체에서 재조회).
    worst_path = next(
        (p for p in paths if representatives["worst"] and p.simulation_index == representatives["worst"]["simulation_index"]),
        None,
    )
    worst_case_recovery = worst_path.recovery if worst_path is not None else None

    robustness = compute_robustness_score(
        simulation_method=simulation_method,
        risk_of_ruin_percent=ruin_stats["risk_of_ruin_percent"],
        p05_total_return=p05_total_return,
        median_total_return=median_total_return,
        p95_max_drawdown_percent=p95_drawdown,
        p95_consecutive_losses=p95_consecutive_losses,
        final_equity_ci_low=confidence_interval_payload["final_equity_confidence_low"],
        final_equity_ci_high=confidence_interval_payload["final_equity_confidence_high"],
        median_final_equity=median_final_equity,
        worst_case_recovery=worst_case_recovery,
        valid_simulation_ratio_percent=(
            (Decimal(valid_count) / Decimal(simulation_count) * HUNDRED) if simulation_count else ZERO
        ),
    )

    status, status_reason = determine_monte_carlo_status(
        valid_simulation_count=valid_count, robustness_score=robustness["score"],
        risk_of_ruin_percent=ruin_stats["risk_of_ruin_percent"], p05_total_return=p05_total_return,
        p95_max_drawdown_percent=p95_drawdown,
    )

    provenance_payload = {
        "strategy_definition_id": strategy_definition_id,
        "backtest_run_id": backtest_run_id,
        "executable_hash": executable_hash,
        "runtime_input_hash": runtime_input_hash,
        "trade_pnl_hash": trade_pnl_hash,
        "definition_hash": run_parameters.get("definition_hash"),
    }
    failure_summary_payload = {
        "failed_simulation_count": failed_count,
        "failures": sim_failures[:50],  # 방어적 상한(대량 실패 시에도 payload 폭증 방지)
    }

    report = MonteCarloSimulationReportEntity(
        strategy_id=strategy_definition_id,
        backtest_run_id=backtest_run_id,
        simulation_method=simulation_method,
        simulation_count=simulation_count,
        random_seed=random_seed,
        confidence_level=confidence_level,
        ruin_threshold_percent=ruin_threshold_percent,
        block_size=block_size if simulation_method == "BLOCK_BOOTSTRAP" else None,
        trade_count=trade_count,
        valid_simulation_count=valid_count,
        failed_simulation_count=failed_count,
        risk_of_ruin_percent=ruin_stats["risk_of_ruin_percent"],
        robustness_score=robustness["score"],
        monte_carlo_status=status,
        percentile_payload=_to_jsonable(percentile_payload),
        confidence_interval_payload=_to_jsonable(confidence_interval_payload),
        representative_payload=_to_jsonable(representatives),
        failure_summary_payload=_to_jsonable(failure_summary_payload),
        provenance_payload=_to_jsonable(provenance_payload),
        algorithm_version=ALGORITHM_VERSION,
        report_input_hash=report_input_hash,
        idempotency_key=(idempotency_key or None),
        requested_by=actor,
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    result = _to_report_dict(report, idempotent_replay=False)
    result["robustness_breakdown"] = _to_jsonable(robustness["breakdown"])
    result["status_reason"] = _to_jsonable(status_reason)
    result["ruin_equity_threshold"] = ruin_equity_threshold
    return result


def _to_report_dict(
    report: MonteCarloSimulationReportEntity, *, idempotent_replay: bool
) -> dict[str, Any]:
    return {
        "monte_carlo_report_id": int(report.monte_carlo_report_id),
        "strategy_id": report.strategy_id,
        "backtest_run_id": report.backtest_run_id,
        "simulation_method": report.simulation_method,
        "simulation_count": report.simulation_count,
        "random_seed": report.random_seed,
        "confidence_level": report.confidence_level,
        "ruin_threshold_percent": report.ruin_threshold_percent,
        "block_size": report.block_size,
        "trade_count": report.trade_count,
        "valid_simulation_count": report.valid_simulation_count,
        "failed_simulation_count": report.failed_simulation_count,
        "risk_of_ruin_percent": report.risk_of_ruin_percent,
        "robustness_score": report.robustness_score,
        "monte_carlo_status": report.monte_carlo_status,
        "percentile_payload": report.percentile_payload,
        "confidence_interval_payload": report.confidence_interval_payload,
        "representative_payload": report.representative_payload,
        "failure_summary_payload": report.failure_summary_payload,
        "provenance_payload": report.provenance_payload,
        "algorithm_version": report.algorithm_version,
        "report_input_hash": report.report_input_hash,
        "requested_by": report.requested_by,
        "created_at": report.created_at,
        "idempotent_replay": idempotent_replay,
    }


def get_monte_carlo_report(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = session.get(MonteCarloSimulationReportEntity, report_id)
    if report is None:
        raise MonteCarloError("NOT_FOUND", f"Monte Carlo report not found: {report_id}")
    if strategy_definition_id is not None and report.strategy_id != strategy_definition_id:
        raise MonteCarloError("NOT_FOUND", f"Monte Carlo report not found: {report_id}")
    return _to_report_dict(report, idempotent_replay=False)


def get_monte_carlo_summary(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_monte_carlo_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "monte_carlo_report_id": report["monte_carlo_report_id"],
        "strategy_id": report["strategy_id"],
        "monte_carlo_status": report["monte_carlo_status"],
        "robustness_score": report["robustness_score"],
        "risk_of_ruin_percent": report["risk_of_ruin_percent"],
        "valid_simulation_count": report["valid_simulation_count"],
        "failed_simulation_count": report["failed_simulation_count"],
    }


def get_monte_carlo_distribution(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_monte_carlo_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "monte_carlo_report_id": report["monte_carlo_report_id"],
        "strategy_id": report["strategy_id"],
        "percentile": report["percentile_payload"],
        "confidence_interval": report["confidence_interval_payload"],
    }


def get_monte_carlo_representatives(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_monte_carlo_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "monte_carlo_report_id": report["monte_carlo_report_id"],
        "strategy_id": report["strategy_id"],
        "representatives": report["representative_payload"],
    }
