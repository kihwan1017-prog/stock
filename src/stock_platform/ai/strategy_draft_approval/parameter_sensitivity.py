"""STEP 12-11 — Parameter Sensitivity Analysis.

승인된 Strategy Definition이 특정 파라미터 값에 과도하게 의존하는지
검증한다. 최고 수익 파라미터를 자동 탐색하지 않는다 — 기준값 주변의
성과 안정성/성과 절벽/과의존을 진단할 뿐이다.

재사용(중복 생성 금지 확인):
- Backtest 실행: STEP12-7 `run_definition_backtest()`를 그대로 재사용하되
  신규 `parameter_overrides` 인자(§backtest_execution.py)로 일회성 Rule
  override만 적용한다 — 새 BacktestEngine 없음, 원본 Definition 미수정.
- Executable Specification: STEP12-6 `compile_specification()`/신규
  `apply_parameter_overrides()`(§backtest_spec.py)를 재사용 — 새 Compiler
  없음.
- Performance Analytics: STEP12-8 `analyze_backtest_run()`을 그대로
  재사용 — 새 Analyzer 없음.
- 저장: 기존 backtest_run/strategy_performance_run/
  strategy_quality_gate_report 스키마 전부가 이번 STEP의 내용(Variation
  목록 + Robustness Score + Stable Range + Performance Cliff)과 의미적으로
  맞지 않아 최소 전용 불변 테이블 1개만 추가(§ 완료보고 Migration 항목).

Quality Gate 연계 금지(이번 STEP 범위): Quality Gate Report/Recommendation
UPDATE, Strategy 승인 상태 변경, 자동 Promotion 전부 수행하지 않는다 —
Sensitivity 결과는 독립된 조회 전용 보고서로만 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import product
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_BASE,
    EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_VARIATION,
    BacktestExecutionError,
    run_definition_backtest,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    _canonical_json,
    _hash,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity_entities import (
    ParameterSensitivityReportEntity,
)
from stock_platform.ai.strategy_draft_generation.constants import (
    MAX_POSITION_SIZE_PERCENT,
    MAX_STOP_LOSS_PERCENT,
    MAX_TAKE_PROFIT_PERCENT,
)
from stock_platform.performance.backtest_analytics import _to_jsonable, analyze_backtest_run

ALGORITHM_VERSION = "1.0.0"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
DEFAULT_VARIATION_RATIOS: tuple[Decimal, ...] = (
    Decimal("-0.20"), Decimal("-0.10"), Decimal("0"), Decimal("0.10"), Decimal("0.20"),
)
MAX_PARAMETERS = 2
MAX_COMBINATIONS = 25
MIN_SUCCESSFUL_FOR_ANALYSIS = 3

_STABLE_SCORE_DROP_TOLERANCE = Decimal("20")
_STABLE_MDD_INCREASE_TOLERANCE = Decimal("15")
_STABLE_MIN_TRADE_COUNT = 3

_CLIFF_THRESHOLDS = {
    "score": {"LOW": Decimal("15"), "MEDIUM": Decimal("30"), "HIGH": Decimal("50")},
    "return": {"LOW": Decimal("10"), "MEDIUM": Decimal("20"), "HIGH": Decimal("40")},
    "mdd": {"LOW": Decimal("8"), "MEDIUM": Decimal("15"), "HIGH": Decimal("30")},
}


class ParameterSensitivityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Parameter Extraction — Executable Specification에서 지원 가능한 수치형
# 파라미터만 추출한다(문자열/Boolean/Enum/Broker/Account/Runtime/
# Credential/Symbol/Market은 애초에 추출 대상이 아니므로 구조적으로
# Fail Closed).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParameterDescriptor:
    name: str
    path: tuple[Any, ...]
    value: Decimal
    kind: str


def extract_numeric_parameters(specification: dict[str, Any]) -> list[ParameterDescriptor]:
    if not specification.get("compilable"):
        raise ParameterSensitivityError(
            "DEFINITION_NOT_READY", "compilable=False Specification에서는 파라미터를 추출할 수 없습니다."
        )

    descriptors: list[ParameterDescriptor] = []
    for side in ("entry_rules", "exit_rules"):
        for idx, rule in enumerate(specification[side]):
            if rule.get("lookback") is not None:
                descriptors.append(
                    ParameterDescriptor(
                        name=f"{side}[{idx}].lookback", path=(side, idx, "lookback"),
                        value=Decimal(int(rule["lookback"])), kind="PERIOD",
                    )
                )
            descriptors.append(
                ParameterDescriptor(
                    name=f"{side}[{idx}].threshold", path=(side, idx, "threshold"),
                    value=Decimal(str(rule["threshold"])), kind="THRESHOLD",
                )
            )
    descriptors.append(
        ParameterDescriptor(
            name="stop_loss_rule.value", path=("stop_loss_rule", "value"),
            value=Decimal(str(specification["stop_loss_rule"]["value"])), kind="PERCENT_STOP_LOSS",
        )
    )
    descriptors.append(
        ParameterDescriptor(
            name="take_profit_rule.value", path=("take_profit_rule", "value"),
            value=Decimal(str(specification["take_profit_rule"]["value"])), kind="PERCENT_TAKE_PROFIT",
        )
    )
    descriptors.append(
        ParameterDescriptor(
            name="position_sizing_rule.value", path=("position_sizing_rule", "value"),
            value=Decimal(str(specification["position_sizing_rule"]["value"])), kind="RATIO_POSITION_SIZE",
        )
    )
    return descriptors


def _find_descriptor(descriptors: list[ParameterDescriptor], name: str) -> ParameterDescriptor:
    for d in descriptors:
        if d.name == name:
            return d
    raise ParameterSensitivityError(
        "UNSUPPORTED_PARAMETER",
        f"지원하지 않거나 존재하지 않는 파라미터입니다: {name} "
        f"(문자열/Boolean/Enum/Broker/Account/Runtime/Credential/Symbol/Market은 지원하지 않음)",
    )


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Parameter Variation — 결정적 순서, 기준값 필수 포함, 타입별 반올림/clamp.
# ---------------------------------------------------------------------------


def generate_variations(
    descriptor: ParameterDescriptor, ratios: tuple[Decimal, ...] = DEFAULT_VARIATION_RATIOS
) -> list[Decimal]:
    base = descriptor.value
    raw = [base * (Decimal("1") + r) for r in ratios]

    if descriptor.kind == "PERIOD":
        candidates = [max(Decimal("1"), v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for v in raw]
    elif descriptor.kind == "PERCENT_STOP_LOSS":
        candidates = [
            _clamp(v, Decimal("0.01"), Decimal(str(MAX_STOP_LOSS_PERCENT))).quantize(Decimal("0.01"))
            for v in raw
        ]
    elif descriptor.kind == "PERCENT_TAKE_PROFIT":
        candidates = [
            _clamp(v, Decimal("0.01"), Decimal(str(MAX_TAKE_PROFIT_PERCENT))).quantize(Decimal("0.01"))
            for v in raw
        ]
    elif descriptor.kind == "RATIO_POSITION_SIZE":
        candidates = [
            _clamp(v, Decimal("0.0001"), Decimal(str(MAX_POSITION_SIZE_PERCENT))).quantize(Decimal("0.0001"))
            for v in raw
        ]
    elif descriptor.kind == "THRESHOLD":
        candidates = [v.quantize(Decimal("0.01")) for v in raw]
    else:
        raise ParameterSensitivityError(
            "UNSUPPORTED_PARAMETER", f"지원하지 않는 파라미터 종류입니다: {descriptor.kind}"
        )

    seen: set[Decimal] = set()
    ordered: list[Decimal] = []
    for v in candidates:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    if base not in seen:
        ordered.append(base)
        ordered.sort()
    return ordered


@dataclass(frozen=True, slots=True)
class VariationCombination:
    combination_no: int
    parameter_values: dict[str, Decimal]


def build_combinations(
    parameter_variations: dict[str, list[Decimal]], *, max_combinations: int = MAX_COMBINATIONS
) -> list[VariationCombination]:
    names = list(parameter_variations.keys())
    value_lists = [parameter_variations[n] for n in names]
    total = 1
    for values in value_lists:
        total *= len(values)
    if total > max_combinations:
        raise ParameterSensitivityError(
            "COMBINATION_LIMIT_EXCEEDED",
            f"조합 수 {total}개가 상한 {max_combinations}개를 초과해 실행을 차단합니다.",
        )
    return [
        VariationCombination(combination_no=no, parameter_values=dict(zip(names, values)))
        for no, values in enumerate(product(*value_lists), start=1)
    ]


# ---------------------------------------------------------------------------
# 실행 — 기존 Backtest/Performance Analytics 경로만 재사용.
# ---------------------------------------------------------------------------


def _execution_input_hash(
    *, executable_hash: str | None, runtime_input_hash: str | None, override_payload: list[dict[str, Any]]
) -> str | None:
    """Variation별 실제 실행 입력 지문(§STEP12-11 인수 조건 확인 — 재사용
    되던 `runtime_input_hash`는 symbol/기간/자본/fee/slippage만 반영해
    모든 Variation에서 동일했고, override가 반영된 실제 executable_hash는
    Variation 결과에 전혀 노출되지 않아 "이 Variation을 재현하려면 정확히
    무엇이 필요한가"를 알 수 없었다 — execution_input_hash를 report 전체
    입력 해시(`input_hash`, 기존 명칭 유지)와 명확히 분리해 새로 추가한다."""

    if executable_hash is None or runtime_input_hash is None:
        return None
    canonical = {
        "executable_hash": executable_hash,
        "runtime_input_hash": runtime_input_hash,
        "parameter_override_payload": _to_jsonable(override_payload),
    }
    return _hash(_canonical_json(canonical))


def _variation_summary(analysis: dict[str, Any], backtest_run_id: int) -> dict[str, Any]:
    kpi = analysis["kpi"]
    score = analysis["score"]
    return {
        "backtest_run_id": backtest_run_id,
        "total_return_rate": kpi["total_return_rate"],
        "cagr": kpi["cagr"],
        "sharpe_ratio": kpi["sharpe_ratio"],
        "sortino_ratio": kpi["sortino_ratio"],
        "maximum_drawdown_rate": kpi["maximum_drawdown_rate"],
        "profit_factor": kpi["profit_factor"],
        "trade_count": kpi["trade_count"],
        "strategy_score": score["score"],
        "grade": score["grade"],
    }


def run_parameter_sensitivity(
    session: Session,
    strategy_definition_id: int,
    *,
    parameter_names: list[str],
    runtime_input: dict[str, Any],
    actor: str,
    variation_ratios: tuple[Decimal, ...] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Parameter Sensitivity Analysis를 실행하고 불변 Report로 저장한다.

    idempotency_key가 주어지고 이미 존재하면 재실행 없이 기존 Report를
    그대로 반환한다(§ Persistence 불변 원칙). idempotency_key가 없으면
    매 호출마다 항상 새 Report를 생성한다(재평가 시 UPDATE 금지)."""

    ratios = variation_ratios or DEFAULT_VARIATION_RATIOS

    if idempotency_key:
        existing = session.scalar(
            select(ParameterSensitivityReportEntity).where(
                ParameterSensitivityReportEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return _to_report_dict(existing, idempotent_replay=True)

    if not parameter_names or len(parameter_names) > MAX_PARAMETERS:
        raise ParameterSensitivityError(
            "TOO_MANY_PARAMETERS" if len(parameter_names) > MAX_PARAMETERS else "UNSUPPORTED_PARAMETER",
            f"파라미터는 1~{MAX_PARAMETERS}개까지만 지정할 수 있습니다(요청: {len(parameter_names)}개).",
        )

    try:
        specification = compile_specification(session, strategy_definition_id)
    except BacktestSpecificationError as exc:
        raise ParameterSensitivityError(exc.code, exc.message) from exc
    if not specification["compilable"]:
        raise ParameterSensitivityError(
            "DEFINITION_NOT_READY" if not specification["ready"] else "PROVENANCE_INVALID",
            "; ".join(specification["failure_reasons"]) or "컴파일 실패",
        )

    descriptors = extract_numeric_parameters(specification)
    selected = [_find_descriptor(descriptors, name) for name in parameter_names]

    parameter_variations = {d.name: generate_variations(d, ratios) for d in selected}
    combinations = build_combinations(parameter_variations)

    # 기준(Base) 실행 — override 없이 실제 Definition 그대로(비교 기준).
    try:
        base_run = run_definition_backtest(
            session, strategy_definition_id, runtime_input=runtime_input, actor=actor,
            execution_purpose=EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_BASE,
        )
    except BacktestExecutionError as exc:
        raise ParameterSensitivityError(exc.code, exc.message) from exc
    base_analysis = analyze_backtest_run(session, base_run["backtest_run_id"])
    base_summary = _variation_summary(base_analysis, base_run["backtest_run_id"])

    variation_results: list[dict[str, Any]] = []
    for combo in combinations:
        overrides = [(selected_d.path, combo.parameter_values[selected_d.name]) for selected_d in selected]
        try:
            var_run = run_definition_backtest(
                session, strategy_definition_id, runtime_input=runtime_input, actor=actor,
                parameter_overrides=overrides,
                execution_purpose=EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_VARIATION,
            )
        except BacktestExecutionError as exc:
            override_payload = [{"path": list(p), "value": v} for p, v in overrides]
            variation_results.append(
                {
                    "combination_no": combo.combination_no,
                    "parameter_values": dict(combo.parameter_values),
                    "parameter_override_payload": override_payload,
                    "runtime_input_hash": None,
                    "executable_hash": None,
                    "execution_input_hash": None,
                    "status": "FAILED",
                    "failure_reason": f"{exc.code}: {exc.message}",
                }
            )
            continue

        analysis = analyze_backtest_run(session, var_run["backtest_run_id"])
        summary = _variation_summary(analysis, var_run["backtest_run_id"])
        override_payload = [{"path": list(p), "value": v} for p, v in overrides]
        var_runtime_input_hash = var_run["parameters"]["runtime_input_hash"]
        var_executable_hash = var_run["parameters"]["executable_hash"]
        variation_results.append(
            {
                "combination_no": combo.combination_no,
                "parameter_values": dict(combo.parameter_values),
                "parameter_override_payload": override_payload,
                "runtime_input_hash": var_runtime_input_hash,
                "executable_hash": var_executable_hash,
                "execution_input_hash": _execution_input_hash(
                    executable_hash=var_executable_hash,
                    runtime_input_hash=var_runtime_input_hash,
                    override_payload=override_payload,
                ),
                "status": "SUCCESS",
                "failure_reason": "",
                **summary,
            }
        )

    successful = [v for v in variation_results if v["status"] == "SUCCESS"]
    failed = [v for v in variation_results if v["status"] == "FAILED"]

    single_param = len(selected) == 1
    ordered_variations: list[dict[str, Any]] = []
    stable_range: dict[str, Any] | None = None
    performance_cliffs: list[dict[str, Any]] = []
    adjacent_deviations: list[dict[str, Any]] = []

    if single_param:
        name = selected[0].name
        ordered_variations = sorted(
            (
                {**v, "parameter_value": v["parameter_values"][name]}
                for v in variation_results
            ),
            key=lambda v: v["parameter_value"],
        )
        stable_range = _compute_stable_range(
            parameter_name=name, base_value=selected[0].value,
            ordered_variations=ordered_variations, base_summary=base_summary,
        )
        performance_cliffs = _detect_performance_cliffs(ordered_variations)
        adjacent_deviations = _compute_adjacent_deviations(ordered_variations)

    robustness = _compute_robustness_score(
        total_variation_count=len(variation_results), successful_variations=successful,
        base_summary=base_summary, include_continuity=single_param,
        base_in_stable_range=bool(stable_range and stable_range.get("includes_base")),
    )

    sensitivity_status, status_reason = _determine_sensitivity_status(
        successful_count=len(successful), robustness_score=robustness["score"],
        stable_range=stable_range, performance_cliffs=performance_cliffs, single_param=single_param,
    )

    max_performance_degradation = max(
        (max(ZERO, base_summary["total_return_rate"] - v["total_return_rate"]) for v in successful),
        default=ZERO,
    )
    max_mdd_degradation = max(
        (max(ZERO, v["maximum_drawdown_rate"] - base_summary["maximum_drawdown_rate"]) for v in successful),
        default=ZERO,
    )
    analytics = {
        "success_ratio": (
            (Decimal(len(successful)) / Decimal(len(variation_results)) * HUNDRED).quantize(Decimal("0.01"))
            if variation_results
            else ZERO
        ),
        "max_performance_degradation": max_performance_degradation.quantize(Decimal("0.0001")),
        "max_mdd_degradation": max_mdd_degradation.quantize(Decimal("0.0001")),
        "adjacent_deviations": adjacent_deviations,
        "single_parameter_analysis": single_param,
    }

    parameter_specification = _to_jsonable(
        [
            {"name": d.name, "base_value": d.value, "kind": d.kind, "path": list(d.path)}
            for d in selected
        ]
    )
    variation_policy = _to_jsonable(
        {
            "ratios": list(ratios),
            "max_combinations": MAX_COMBINATIONS,
            "parameter_variations": {k: v for k, v in parameter_variations.items()},
        }
    )

    input_hash = _compute_input_hash(
        strategy_definition_id=strategy_definition_id,
        executable_hash=specification["executable_hash"],
        parameter_names=parameter_names,
        base_values=[d.value for d in selected],
        variation_policy=variation_policy,
        runtime_input=runtime_input,
    )

    report = ParameterSensitivityReportEntity(
        strategy_id=strategy_definition_id,
        base_backtest_run_id=base_run["backtest_run_id"],
        algorithm_version=ALGORITHM_VERSION,
        input_hash=input_hash,
        idempotency_key=(idempotency_key or None),
        robustness_score=robustness["score"],
        sensitivity_status=sensitivity_status,
        successful_variation_count=len(successful),
        failed_variation_count=len(failed),
        parameter_specification=parameter_specification,
        variation_policy=variation_policy,
        variation_results=_to_jsonable(variation_results),
        sensitivity_analytics=_to_jsonable(
            {"base_result": base_summary, **analytics, "robustness_breakdown": robustness["breakdown"]}
        ),
        stable_range=_to_jsonable(stable_range) if stable_range is not None else None,
        performance_cliffs=_to_jsonable(performance_cliffs),
        status_reason=_to_jsonable(status_reason),
        requested_by=actor,
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    return _to_report_dict(report, idempotent_replay=False)


# ---------------------------------------------------------------------------
# Sensitivity Analytics 세부 계산.
# ---------------------------------------------------------------------------


def _stdev(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return ZERO
    mean = sum(values, ZERO) / Decimal(len(values))
    variance = sum(((v - mean) ** 2 for v in values), ZERO) / Decimal(len(values))
    return variance.sqrt()


def _compute_robustness_score(
    *,
    total_variation_count: int,
    successful_variations: list[dict[str, Any]],
    base_summary: dict[str, Any],
    include_continuity: bool,
    base_in_stable_range: bool,
) -> dict[str, Any]:
    """0~100 Parameter Robustness Score. 계산 불가능한 항목은 0점 처리하지
    않고 제외 후 나머지 가중치로 재정규화한다(§ STEP12-8 Strategy Score와
    동일한 원칙 재사용). 다중 파라미터(2개)에서는 연속성(continuity)
    컴포넌트 자체를 포함하지 않는다(N/A — 단일 축 정렬이 없어 계산
    불가능한 것과는 다른, 구조적으로 적용 대상이 아닌 경우)."""

    components: list[dict[str, Any]] = []

    success_ratio = (
        Decimal(len(successful_variations)) / Decimal(total_variation_count) * HUNDRED
        if total_variation_count
        else None
    )
    components.append(
        {"name": "success_ratio", "weight": Decimal("20"), "score": _clamp(success_ratio, ZERO, HUNDRED) if success_ratio is not None else None}
    )

    scores = [v["strategy_score"] for v in successful_variations if v.get("strategy_score") is not None]
    components.append(
        {
            "name": "score_volatility", "weight": Decimal("20"),
            "score": _clamp(HUNDRED - _stdev(scores), ZERO, HUNDRED) if len(scores) >= 2 else None,
        }
    )

    sharpes = [v["sharpe_ratio"] for v in successful_variations if v.get("sharpe_ratio") is not None]
    components.append(
        {
            "name": "sharpe_volatility", "weight": Decimal("15"),
            "score": (
                _clamp(HUNDRED - _stdev(sharpes) * Decimal("20"), ZERO, HUNDRED) if len(sharpes) >= 2 else None
            ),
        }
    )

    returns = [v["total_return_rate"] for v in successful_variations]
    components.append(
        {
            "name": "return_volatility", "weight": Decimal("15"),
            "score": _clamp(HUNDRED - _stdev(returns), ZERO, HUNDRED) if len(returns) >= 2 else None,
        }
    )

    if successful_variations:
        base_mdd = base_summary["maximum_drawdown_rate"]
        max_degradation = max(
            (v["maximum_drawdown_rate"] - base_mdd for v in successful_variations), default=ZERO
        )
        max_degradation = max(max_degradation, ZERO)
        drawdown_score = _clamp(HUNDRED - max_degradation * Decimal("2"), ZERO, HUNDRED)
    else:
        drawdown_score = None
    components.append({"name": "drawdown_degradation", "weight": Decimal("15"), "score": drawdown_score})

    if include_continuity:
        components.append(
            {
                "name": "base_continuity", "weight": Decimal("15"),
                "score": HUNDRED if base_in_stable_range else ZERO,
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


def _compute_stable_range(
    *,
    parameter_name: str,
    base_value: Decimal,
    ordered_variations: list[dict[str, Any]],
    base_summary: dict[str, Any],
) -> dict[str, Any]:
    base_score = base_summary.get("strategy_score")
    base_mdd = base_summary["maximum_drawdown_rate"]

    def _is_stable(v: dict[str, Any]) -> bool:
        if v["status"] != "SUCCESS":
            return False
        if v.get("trade_count", 0) < _STABLE_MIN_TRADE_COUNT:
            return False
        if v.get("strategy_score") is None or base_score is None:
            return False
        if base_score - v["strategy_score"] > _STABLE_SCORE_DROP_TOLERANCE:
            return False
        if v["maximum_drawdown_rate"] - base_mdd > _STABLE_MDD_INCREASE_TOLERANCE:
            return False
        return True

    flags = [_is_stable(v) for v in ordered_variations]
    base_index = next(
        (i for i, v in enumerate(ordered_variations) if v["parameter_value"] == base_value), None
    )
    if base_index is None or not flags[base_index]:
        return {
            "parameter_name": parameter_name, "min_value": None, "max_value": None,
            "includes_base": False, "member_count": 0,
            "reason": "기준값이 안정 조건(Score/MDD/Trade Count 허용범위)을 만족하지 않아 불안정 상태입니다.",
        }

    lo = base_index
    while lo > 0 and flags[lo - 1]:
        lo -= 1
    hi = base_index
    while hi < len(flags) - 1 and flags[hi + 1]:
        hi += 1
    return {
        "parameter_name": parameter_name,
        "min_value": ordered_variations[lo]["parameter_value"],
        "max_value": ordered_variations[hi]["parameter_value"],
        "includes_base": True,
        "member_count": hi - lo + 1,
        "reason": None,
    }


def _severity_for(delta_abs: Decimal, thresholds: dict[str, Decimal]) -> str | None:
    if delta_abs >= thresholds["HIGH"]:
        return "HIGH"
    if delta_abs >= thresholds["MEDIUM"]:
        return "MEDIUM"
    if delta_abs >= thresholds["LOW"]:
        return "LOW"
    return None


def _detect_performance_cliffs(ordered_variations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cliffs: list[dict[str, Any]] = []
    successful = [v for v in ordered_variations if v["status"] == "SUCCESS"]
    severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    for prev, cur in zip(successful, successful[1:]):
        reasons: list[str] = []
        severities: list[str] = []

        if prev.get("strategy_score") is not None and cur.get("strategy_score") is not None:
            score_delta = prev["strategy_score"] - cur["strategy_score"]
            sev = _severity_for(score_delta, _CLIFF_THRESHOLDS["score"])
            if sev:
                severities.append(sev)
                reasons.append(f"Strategy Score {score_delta}점 하락")

        return_delta = prev["total_return_rate"] - cur["total_return_rate"]
        sev = _severity_for(return_delta, _CLIFF_THRESHOLDS["return"])
        if sev:
            severities.append(sev)
            reasons.append(f"Total Return {return_delta}%p 하락")

        mdd_delta = cur["maximum_drawdown_rate"] - prev["maximum_drawdown_rate"]
        sev = _severity_for(mdd_delta, _CLIFF_THRESHOLDS["mdd"])
        if sev:
            severities.append(sev)
            reasons.append(f"MDD {mdd_delta}%p 악화")

        if severities:
            worst = max(severities, key=lambda s: severity_order[s])
            cliffs.append(
                {
                    "cliff_detected": True,
                    "cliff_parameter_from": prev["parameter_value"],
                    "cliff_parameter_to": cur["parameter_value"],
                    "cliff_reason": "; ".join(reasons),
                    "severity": worst,
                }
            )
    return cliffs


def _compute_adjacent_deviations(ordered_variations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    successful = [v for v in ordered_variations if v["status"] == "SUCCESS"]
    deviations = []
    for prev, cur in zip(successful, successful[1:]):
        deviations.append(
            {
                "from": prev["parameter_value"],
                "to": cur["parameter_value"],
                "return_delta": cur["total_return_rate"] - prev["total_return_rate"],
                "score_delta": (
                    cur["strategy_score"] - prev["strategy_score"]
                    if cur.get("strategy_score") is not None and prev.get("strategy_score") is not None
                    else None
                ),
                "mdd_delta": cur["maximum_drawdown_rate"] - prev["maximum_drawdown_rate"],
            }
        )
    return deviations


def _determine_sensitivity_status(
    *,
    successful_count: int,
    robustness_score: Decimal | None,
    stable_range: dict[str, Any] | None,
    performance_cliffs: list[dict[str, Any]],
    single_param: bool,
) -> tuple[str, dict[str, Any]]:
    reason: dict[str, Any] = {
        "successful_count": successful_count,
        "robustness_score": robustness_score,
        "single_parameter_analysis": single_param,
    }
    if successful_count < MIN_SUCCESSFUL_FOR_ANALYSIS or robustness_score is None:
        reason["basis"] = (
            f"유효 Variation 수({successful_count})가 최소 기준({MIN_SUCCESSFUL_FOR_ANALYSIS}) 미만이거나 "
            "Robustness Score를 계산할 수 없습니다."
        )
        return "INSUFFICIENT_DATA", reason

    has_high_cliff = any(c["severity"] == "HIGH" for c in performance_cliffs)
    includes_base = bool(stable_range and stable_range.get("includes_base"))
    reason["includes_base"] = includes_base
    reason["has_high_cliff"] = has_high_cliff

    if robustness_score >= Decimal("70") and includes_base and not has_high_cliff:
        reason["basis"] = "Robustness Score>=70, Stable Range에 기준값 포함, High Cliff 없음"
        return "ROBUST", reason
    if robustness_score < Decimal("40") or not includes_base or has_high_cliff:
        reason["basis"] = "Robustness Score<40 또는 Stable Range에 기준값 미포함 또는 High Cliff 존재"
        return "FRAGILE", reason
    reason["basis"] = "중간 수준의 Robustness Score이며 기준값 주변은 안정적이나 일부 민감도가 존재합니다."
    return "ACCEPTABLE", reason


def _compute_input_hash(
    *,
    strategy_definition_id: int,
    executable_hash: str | None,
    parameter_names: list[str],
    base_values: list[Decimal],
    variation_policy: dict[str, Any],
    runtime_input: dict[str, Any],
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "executable_hash": executable_hash,
        "parameter_names": parameter_names,
        "base_values": [str(v) for v in base_values],
        "variation_policy": variation_policy,
        "symbol": runtime_input["symbol"],
        "exchange_code": runtime_input["exchange_code"],
        "start_date": runtime_input["start_date"].isoformat(),
        "end_date": runtime_input["end_date"].isoformat(),
        "initial_capital": str(runtime_input["initial_capital"]),
        "fee_ratio": str(runtime_input["fee_ratio"]),
        "sell_tax_ratio": str(runtime_input["sell_tax_ratio"]),
        "slippage_ratio": str(runtime_input["slippage_ratio"]),
        "algorithm_version": ALGORITHM_VERSION,
    }
    return _hash(_canonical_json(canonical))


def _to_report_dict(
    report: ParameterSensitivityReportEntity, *, idempotent_replay: bool = False
) -> dict[str, Any]:
    return {
        "parameter_sensitivity_report_id": int(report.parameter_sensitivity_report_id),
        "strategy_id": report.strategy_id,
        "base_backtest_run_id": report.base_backtest_run_id,
        "algorithm_version": report.algorithm_version,
        "input_hash": report.input_hash,
        "robustness_score": report.robustness_score,
        "sensitivity_status": report.sensitivity_status,
        "successful_variation_count": report.successful_variation_count,
        "failed_variation_count": report.failed_variation_count,
        "parameter_specification": report.parameter_specification,
        "variation_policy": report.variation_policy,
        "variation_results": report.variation_results,
        "sensitivity_analytics": report.sensitivity_analytics,
        "stable_range": report.stable_range,
        "performance_cliffs": report.performance_cliffs,
        "status_reason": report.status_reason,
        "requested_by": report.requested_by,
        "created_at": report.created_at,
        "idempotent_replay": idempotent_replay,
    }


def get_parameter_sensitivity_report(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = session.get(ParameterSensitivityReportEntity, report_id)
    if report is None:
        raise ParameterSensitivityError("NOT_FOUND", f"Parameter Sensitivity report not found: {report_id}")
    if strategy_definition_id is not None and report.strategy_id != strategy_definition_id:
        raise ParameterSensitivityError("NOT_FOUND", f"Parameter Sensitivity report not found: {report_id}")
    return _to_report_dict(report)


def get_parameter_sensitivity_summary(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_parameter_sensitivity_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "parameter_sensitivity_report_id": report["parameter_sensitivity_report_id"],
        "strategy_id": report["strategy_id"],
        "sensitivity_status": report["sensitivity_status"],
        "robustness_score": report["robustness_score"],
        "stable_range": report["stable_range"],
        "performance_cliffs": report["performance_cliffs"],
        "status_reason": report["status_reason"],
        "base_result": (report["sensitivity_analytics"] or {}).get("base_result"),
    }


def get_parameter_sensitivity_variations(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_parameter_sensitivity_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "parameter_sensitivity_report_id": report["parameter_sensitivity_report_id"],
        "strategy_id": report["strategy_id"],
        "variation_results": report["variation_results"],
    }
