"""STEP 12-6 — 승인된 Strategy Definition -> Backtest Executable Specification.

새 Entity/Table/Strategy 서브클래스를 만들지 않는다. Definition은 읽기만
하고(불변성 유지), STEP12-2-2의 화이트리스트(`strategy_draft_generation
.constants`)와 STEP12-5의 `check_readiness()`(Provenance/Hash/Payload
완전성)를 그대로 재사용해 결정적 Executable Specification + Hash를
생성한다.

핵심 설계 결정(§3.4 symbols 문제): 실제 `BacktestService
.run_moving_average_backtest()`가 symbol/start_date/end_date/
initial_capital/fee_ratio/sell_tax_ratio/slippage_ratio를 모두 "실행 시
런타임 인자"로 받고 있어(Strategy Definition이나 parameter_payload가
아님), 이 프로젝트의 Backtest 구조는 이미 "전략 정의는 종목 독립적
Template, 종목/기간/자본금은 실행 시 주입"(옵션 A)을 채택하고 있음을
확인했다. 따라서 Definition에 symbols 컬럼을 추가하지 않고, 이 값들을
`required_runtime_inputs`로 명시하는 것으로 처리한다.

지원 범위(Fail Closed, §2.3): STEP12-2-2 Validation의 ALLOWED_INDICATORS는
Draft 작성 시점에 "미래 확장을 고려한" 더 넓은 화이트리스트다. 하지만
실제 계산 가능한 Indicator는 `stock_platform.indicators.simple`에 있는
sma/ema/rsi 3개뿐이고, 기존 Backtest 엔진(MovingAverageCrossStrategy)이
실제로 지원하는 stop_loss/take_profit/position_sizing도 각각 PERCENT/
PERCENT/FIXED_PERCENT(비율)뿐이다. Compiler는 "Draft 작성 시 허용된 것"과
"오늘 실행 가능한 것"을 구분해, 후자만 supported로 판정한다(중간 확장
필요 시 이 상수만 넓히면 됨 — 새 Compiler를 새로 만들 필요 없음).
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    _require_definition,
    check_readiness,
)
from stock_platform.ai.strategy_draft_approval.rule_evaluator import (
    IndicatorCache,
    RuleEvaluationError,
    evaluate_group,
    parse_comparison_indicator_ref,
)
from stock_platform.ai.strategy_draft_generation.constants import ALLOWED_OPERATORS
from stock_platform.ai.strategy_draft_generation.schema import (
    DraftRule,
    PositionSizingRule,
    StopLossRule,
    TakeProfitRule,
)
from stock_platform.backtest.models import BacktestPrice
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)

COMPILER_VERSION = "1.0.0"

# 오늘 실제로 계산 가능한 Indicator(stock_platform.indicators.simple).
# ALLOWED_INDICATORS(STEP12-2-2, Draft 작성 시 화이트리스트)보다 좁다 —
# 의도적인 구분이다(위 모듈 docstring 참고).
COMPILER_SUPPORTED_INDICATORS = frozenset({"SMA", "EMA", "RSI"})
COMPILER_SUPPORTED_OPERATORS = ALLOWED_OPERATORS
# 기존 MovingAverageStrategyConfig가 실제로 받는 값의 범위만 지원한다.
COMPILER_SUPPORTED_STOP_LOSS_TYPES = frozenset({"PERCENT"})
COMPILER_SUPPORTED_TAKE_PROFIT_TYPES = frozenset({"PERCENT"})
COMPILER_SUPPORTED_POSITION_SIZING_METHODS = frozenset({"FIXED_PERCENT"})
# PriceDailyRepository/PriceDailyService(일봉) 기반이라 일봉만 지원한다.
COMPILER_SUPPORTED_TIMEFRAMES = frozenset({"1D"})
# BacktestService가 실제로 처리하는 시장(한국 주식 일봉 가격 테이블).
COMPILER_SUPPORTED_MARKET_TYPES = frozenset({"KR_STOCK", "CRYPTO"})


class BacktestSpecificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# STEP12-7 §10 Backtest Adapter 계약 — 기존 BacktestEngine이 실제로 요구하는
# duck-typed 인터페이스(`self._strategy.should_enter(prices, index)` /
# `.should_exit(prices, index, entry_price)`, backtest/engine.py 확인)를
# 그대로 반영한 Protocol. `RuleBasedBacktestAdapter`가 이를 실제로 구현한다
# (STEP12-6에서는 NotImplementedError 골격만 있었음).
# ---------------------------------------------------------------------------
class BacktestStrategyAdapter(Protocol):
    def should_enter(self, *, prices: Any, index: int) -> tuple[bool, str]: ...

    def should_exit(
        self, *, prices: Any, index: int, entry_price: Any
    ) -> tuple[bool, str]: ...


class _AdapterConfig:
    """`BacktestEngine`이 `self._strategy.config.*`로 직접 읽는 값들의
    duck-typed 컨테이너 — `MovingAverageStrategyConfig`와 동일한 속성
    이름을 제공해야 기존 엔진을 그대로 재사용할 수 있다(engine.py 확인:
    stop_loss/take_profit 실제 체결가와 position 수량 계산이
    should_exit()의 반환값이 아니라 이 config 속성을 직접 참조해
    이뤄진다)."""

    __slots__ = ("stop_loss_ratio", "take_profit_ratio", "position_ratio")

    def __init__(
        self, *, stop_loss_ratio: Decimal, take_profit_ratio: Decimal, position_ratio: Decimal
    ) -> None:
        self.stop_loss_ratio = stop_loss_ratio
        self.take_profit_ratio = take_profit_ratio
        self.position_ratio = position_ratio


class RuleBasedBacktestAdapter:
    """§12 완성 — `BacktestStrategyAdapter` 계약(§10)을 실제로 구현한다.

    단위 변환(§10/§11, 실측 확정): STEP12-2-2 Pydantic 제약상
    stop_loss_rule.value/take_profit_rule.value는 **PERCENT 단위**
    (0<value<=30, 0<value<=200 — 예: 5는 5%)인 반면, 기존
    `MovingAverageStrategyConfig.stop_loss_ratio`는 **비율**(예: 0.05)이다
    (기본값 Decimal("0.05")로 확인). 따라서 value/100으로 변환한다.
    position_sizing_rule.value는 STEP12-2-2 상수(MAX_POSITION_SIZE_PERCENT
    =1.0, "FIXED_PERCENT/KELLY_FRACTION은 0~1(비율)")에 따라 이미 비율이므로
    변환 없이 그대로 사용한다.

    Long-only(매수 후 매도) — 기존 엔진이 Short를 지원하지 않으므로
    지원하는 것처럼 구현하지 않는다(§10 명시 요구).

    전역 상태 없음: `IndicatorCache`는 인스턴스마다 새로 생성되어 실행 간
    격리된다(§12)."""

    def __init__(self, specification: dict[str, Any], prices: list[BacktestPrice]) -> None:
        if not specification.get("compilable"):
            raise BacktestSpecificationError(
                "DEFINITION_NOT_READY",
                "compilable=False인 Specification으로는 Adapter를 생성할 수 없습니다.",
            )
        if not specification.get("executable_hash"):
            raise BacktestSpecificationError(
                "EXECUTABLE_HASH_MISMATCH", "executable_hash가 없는 Specification입니다."
            )
        self.specification = specification
        self._entry_rules = [DraftRule.model_validate(r) for r in specification["entry_rules"]]
        self._exit_rules = [DraftRule.model_validate(r) for r in specification["exit_rules"]]
        stop_loss = StopLossRule.model_validate(specification["stop_loss_rule"])
        take_profit = TakeProfitRule.model_validate(specification["take_profit_rule"])
        position_sizing = PositionSizingRule.model_validate(
            specification["position_sizing_rule"]
        )
        self.config = _AdapterConfig(
            stop_loss_ratio=Decimal(str(stop_loss.value)) / Decimal(100),
            take_profit_ratio=Decimal(str(take_profit.value)) / Decimal(100),
            position_ratio=Decimal(str(position_sizing.value)),
        )
        closes = [p.close_price for p in prices]
        self._cache = IndicatorCache(closes)

    def should_enter(self, *, prices: list[BacktestPrice], index: int) -> tuple[bool, str]:
        try:
            matched = evaluate_group(
                self._entry_rules, logical_operator="AND", cache=self._cache, index=index
            )
        except RuleEvaluationError:
            return False, "INSUFFICIENT_DATA"
        return matched, "RULE_ENTRY" if matched else "NO_ENTRY"

    def should_exit(
        self, *, prices: list[BacktestPrice], index: int, entry_price: Decimal
    ) -> tuple[bool, str]:
        # §9 Exit 우선순위(기존 MovingAverageCrossStrategy와 동일한 순서로
        # 회귀 호환 유지): 1) Stop Loss  2) Take Profit  3) 명시적 Exit Rule.
        # 같은 Candle에서 Stop Loss/Take Profit이 동시에 성립할 수 있는
        # 경우도 기존 엔진과 동일하게 Stop Loss를 먼저 반환한다(임의로
        # 유리한 쪽을 선택하지 않고 기존 동작을 그대로 승계).
        current = prices[index]
        if current.low_price <= entry_price * (Decimal("1") - self.config.stop_loss_ratio):
            return True, "STOP_LOSS"
        if current.high_price >= entry_price * (Decimal("1") + self.config.take_profit_ratio):
            return True, "TAKE_PROFIT"
        try:
            matched = evaluate_group(
                self._exit_rules, logical_operator="OR", cache=self._cache, index=index
            )
        except RuleEvaluationError:
            return False, "HOLD"
        return (matched, "RULE_EXIT") if matched else (False, "HOLD")


def _canonical_json(value: Any) -> str:
    """결정적 Hash를 위한 Canonical JSON — Key 정렬, NaN/Infinity 거부."""

    def _default(obj: Any) -> Any:
        raise TypeError(f"not JSON-canonicalizable: {type(obj)!r}")

    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
        separators=(",", ":"),
    )


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_indicator_requirements(
    rules: list[DraftRule],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Indicator 요구사항을 추출·중복 제거·결정적으로 정렬한다.
    미지원 Indicator는 (빈 목록, 오류 목록)으로 반환한다."""

    unsupported: list[str] = []
    seen: set[tuple[str, int | None]] = set()
    requirements: list[dict[str, Any]] = []
    for rule in rules:
        comparison_ref = parse_comparison_indicator_ref(getattr(rule, "comparison_target", None))
        if rule.comparison_target is not None and comparison_ref is None:
            unsupported.append(
                f"UNSUPPORTED_RULE_FIELD: comparison_target={rule.comparison_target}"
                "(허용 형식은 SMA:{period} 또는 EMA:{period} 뿐입니다)"
            )
            continue
        if rule.indicator not in COMPILER_SUPPORTED_INDICATORS:
            unsupported.append(
                f"UNSUPPORTED_INDICATOR: {rule.indicator}(compiler가 계산 가능한 "
                f"Indicator는 {sorted(COMPILER_SUPPORTED_INDICATORS)}뿐입니다)"
            )
            continue
        if rule.operator not in COMPILER_SUPPORTED_OPERATORS:
            unsupported.append(f"UNSUPPORTED_OPERATOR: {rule.operator}")
            continue
        if rule.indicator in {"SMA", "EMA"} and rule.lookback is None:
            unsupported.append(
                f"MISSING_INDICATOR_PERIOD: {rule.indicator} Rule에 lookback이 없습니다."
            )
            continue
        for indicator_name, indicator_period in (
            (rule.indicator, rule.lookback),
            *((comparison_ref,) if comparison_ref is not None else ()),
        ):
            key = (indicator_name, indicator_period)
            if key in seen:
                continue
            seen.add(key)
            requirements.append({"indicator": indicator_name, "period": indicator_period})
    # 결정적 정렬 — dict 삽입 순서에 의존하지 않는다.
    requirements.sort(key=lambda r: (r["indicator"], r["period"] or 0))
    return requirements, unsupported


def compile_specification(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    """Executable Specification을 컴파일한다(DB WRITE 없음, Definition
    미수정). 항상 dict를 반환하며(NOT_FOUND만 예외), `compilable`로 성공
    여부를 판정한다 — 지원하지 않는 항목을 임의로 무시하지 않고 전부
    `errors`에 기록한다(Fail Closed)."""

    try:
        definition = _require_definition(session, strategy_definition_id)
    except ReadinessError as exc:
        raise BacktestSpecificationError(exc.code, exc.message) from exc

    readiness = check_readiness(session, strategy_definition_id)
    errors: list[str] = []
    warnings: list[str] = []

    if not readiness["ready"]:
        errors.append("DEFINITION_NOT_READY")
        errors.extend(readiness["failure_reasons"])
        return _result(
            definition=definition,
            compilable=False,
            executable_hash=None,
            indicator_requirements=[],
            required_runtime_inputs=_required_runtime_inputs(),
            supported_features={},
            warnings=warnings,
            errors=errors,
            readiness=readiness,
        )

    payload = definition.parameter_payload or {}

    source_market_type = payload.get("source_market_type")
    if source_market_type not in COMPILER_SUPPORTED_MARKET_TYPES:
        errors.append(f"UNSUPPORTED_MARKET_TYPE: {source_market_type}")

    timeframe = payload.get("timeframe")
    if timeframe not in COMPILER_SUPPORTED_TIMEFRAMES:
        errors.append(f"UNSUPPORTED_TIMEFRAME: {timeframe}")

    try:
        # parameter_payload는 이미 역직렬화된 JSONB이므로 그대로 사용한다
        # (문자열 재파싱 불필요).
        entry_raw = payload.get("entry_rule")
        exit_raw = payload.get("exit_rule")
        entry_rules = [DraftRule.model_validate(item) for item in (entry_raw or [])]
        exit_rules = [DraftRule.model_validate(item) for item in (exit_raw or [])]
    except Exception as exc:  # noqa: BLE001 — 구조 자체가 깨진 경우
        errors.append(f"INVALID_RULE_COMBINATION: entry/exit rule 파싱 실패({exc})")
        entry_rules, exit_rules = [], []

    entry_reqs, entry_unsupported = _extract_indicator_requirements(entry_rules)
    exit_reqs, exit_unsupported = _extract_indicator_requirements(exit_rules)
    errors.extend(entry_unsupported)
    errors.extend(exit_unsupported)

    merged_requirements: dict[tuple[str, int | None], dict[str, Any]] = {}
    for req in entry_reqs + exit_reqs:
        merged_requirements[(req["indicator"], req["period"])] = req
    indicator_requirements = sorted(
        merged_requirements.values(), key=lambda r: (r["indicator"], r["period"] or 0)
    )

    stop_loss = payload.get("stop_loss_rule") or {}
    take_profit = payload.get("take_profit_rule") or {}
    position_sizing = payload.get("position_sizing_rule") or {}
    try:
        stop_loss_model = StopLossRule.model_validate(stop_loss)
        if stop_loss_model.type not in COMPILER_SUPPORTED_STOP_LOSS_TYPES:
            errors.append(f"UNSUPPORTED_RULE_FIELD: stop_loss_rule.type={stop_loss_model.type}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"INVALID_RULE_COMBINATION: stop_loss_rule 검증 실패({exc})")
    try:
        take_profit_model = TakeProfitRule.model_validate(take_profit)
        if take_profit_model.type not in COMPILER_SUPPORTED_TAKE_PROFIT_TYPES:
            errors.append(
                f"UNSUPPORTED_RULE_FIELD: take_profit_rule.type={take_profit_model.type}"
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"INVALID_RULE_COMBINATION: take_profit_rule 검증 실패({exc})")
    try:
        position_sizing_model = PositionSizingRule.model_validate(position_sizing)
        if position_sizing_model.method not in COMPILER_SUPPORTED_POSITION_SIZING_METHODS:
            errors.append(
                "UNSUPPORTED_RULE_FIELD: "
                f"position_sizing_rule.method={position_sizing_model.method}"
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"INVALID_RULE_COMBINATION: position_sizing_rule 검증 실패({exc})")

    if not entry_rules:
        errors.append("INVALID_RULE_COMBINATION: entry_rule이 비어 있습니다.")
    if not exit_rules:
        errors.append("INVALID_RULE_COMBINATION: exit_rule이 비어 있습니다.")

    supported_features = {
        "indicators": sorted(COMPILER_SUPPORTED_INDICATORS),
        "operators": sorted(COMPILER_SUPPORTED_OPERATORS),
        "stop_loss_types": sorted(COMPILER_SUPPORTED_STOP_LOSS_TYPES),
        "take_profit_types": sorted(COMPILER_SUPPORTED_TAKE_PROFIT_TYPES),
        "position_sizing_methods": sorted(COMPILER_SUPPORTED_POSITION_SIZING_METHODS),
        "timeframes": sorted(COMPILER_SUPPORTED_TIMEFRAMES),
        "market_types": sorted(COMPILER_SUPPORTED_MARKET_TYPES),
    }
    required_runtime_inputs = _required_runtime_inputs()

    compilable = len(errors) == 0
    executable_hash = None
    rule_payload: dict[str, Any] = {}
    if compilable:
        rule_payload = {
            "entry_rules": [r.model_dump() for r in entry_rules],
            "exit_rules": [r.model_dump() for r in exit_rules],
            "stop_loss_rule": stop_loss_model.model_dump(),
            "take_profit_rule": take_profit_model.model_dump(),
            "position_sizing_rule": position_sizing_model.model_dump(),
        }
        canonical = {
            "compiler_version": COMPILER_VERSION,
            "definition_hash": definition.definition_hash,
            **rule_payload,
            "indicator_requirements": indicator_requirements,
            "timeframe": timeframe,
            "market_type": source_market_type,
            "required_runtime_inputs": required_runtime_inputs,
        }
        executable_hash = _hash(_canonical_json(canonical))

    return _result(
        definition=definition,
        compilable=compilable,
        executable_hash=executable_hash,
        indicator_requirements=indicator_requirements,
        required_runtime_inputs=required_runtime_inputs,
        supported_features=supported_features,
        warnings=warnings,
        errors=errors,
        readiness=readiness,
        rule_payload=rule_payload,
    )


def _required_runtime_inputs() -> list[dict[str, Any]]:
    """Definition에는 없지만 실제 `BacktestService
    .run_moving_average_backtest()` 실행에 필요한 값(§3.4 옵션 A) —
    기존 실행 함수의 실제 파라미터 목록과 정확히 일치시킨다(임의 발명 금지)."""
    return [
        {"name": "symbol", "type": "string", "required": True, "default": None},
        {"name": "exchange_code", "type": "string", "required": True, "default": None},
        {"name": "start_date", "type": "date", "required": True, "default": None},
        {"name": "end_date", "type": "date", "required": True, "default": None},
        {"name": "initial_capital", "type": "decimal", "required": True, "default": None},
        {"name": "fee_ratio", "type": "decimal", "required": True, "default": None},
        {"name": "sell_tax_ratio", "type": "decimal", "required": True, "default": None},
        {"name": "slippage_ratio", "type": "decimal", "required": True, "default": None},
    ]


def _result(
    *,
    definition: StrategyDefinitionEntity,
    compilable: bool,
    executable_hash: str | None,
    indicator_requirements: list[dict[str, Any]],
    required_runtime_inputs: list[dict[str, Any]],
    supported_features: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    readiness: dict[str, Any],
    rule_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = definition.parameter_payload or {}
    result = {
        "strategy_definition_id": int(definition.strategy_id),
        "definition_version": definition.definition_version,
        "definition_hash": definition.definition_hash,
        "timeframe": payload.get("timeframe"),
        "market_type": payload.get("source_market_type"),
        "ready": readiness["ready"],
        "compilable": compilable,
        "compiler_version": COMPILER_VERSION,
        "executable_hash": executable_hash,
        "indicator_requirements": indicator_requirements,
        "required_runtime_inputs": required_runtime_inputs,
        "supported_features": supported_features,
        "warnings": warnings,
        "errors": errors,
        "failure_reasons": errors,
    }
    result.update(rule_payload or {})
    return result


# ---------------------------------------------------------------------------
# STEP12-11 — Parameter Sensitivity Analysis용 일회성 Parameter Override.
# 원본 Definition/저장된 executable_hash는 전혀 건드리지 않는다 — 이미
# compile된(compilable=True) Specification을 입력으로 받아, 그 dict의
# 복사본에만 override를 적용한 새 Specification을 반환한다(Definition
# DB WRITE 없음). 기존 DraftRule/StopLossRule/TakeProfitRule/
# PositionSizingRule Pydantic 검증과 _extract_indicator_requirements/
# _canonical_json/_hash를 그대로 재사용해 override된 값도 동일한 Fail
# Closed 규칙(허용 범위, 지원 Indicator/Operator)을 통과해야 한다.
# ---------------------------------------------------------------------------


def _set_override_path(
    rule_groups: dict[str, Any], path: tuple[Any, ...], value: Any
) -> None:
    root_name = path[0]
    if root_name not in rule_groups:
        raise BacktestSpecificationError(
            "UNSUPPORTED_PARAMETER", f"알 수 없는 파라미터 경로입니다: {path}"
        )
    root = rule_groups[root_name]
    if root_name in {"stop_loss_rule", "take_profit_rule", "position_sizing_rule"} and len(path) == 2:
        root[path[1]] = value
        return
    if root_name in {"entry_rules", "exit_rules"} and len(path) == 3:
        index, field = path[1], path[2]
        if not isinstance(root, list) or index >= len(root):
            raise BacktestSpecificationError(
                "UNSUPPORTED_PARAMETER", f"존재하지 않는 Rule 인덱스입니다: {path}"
            )
        root[index][field] = value
        return
    raise BacktestSpecificationError("UNSUPPORTED_PARAMETER", f"지원하지 않는 파라미터 경로입니다: {path}")


def apply_parameter_overrides(
    specification: dict[str, Any], overrides: list[tuple[tuple[Any, ...], Any]]
) -> dict[str, Any]:
    """compile_specification()의 compilable=True 결과에 대해 파라미터
    경로별 override를 적용한, 실행 전용(비영속) 새 Specification을
    만든다. indicator_requirements/executable_hash는 override 반영
    결과로 재계산한다(Provenance 정직성 — override된 Rule로 실제 실행된
    Signal이 원본 Definition의 executable_hash를 사칭하지 않도록)."""

    if not specification.get("compilable"):
        raise BacktestSpecificationError(
            "DEFINITION_NOT_READY", "compilable=False Specification은 override할 수 없습니다."
        )

    rule_groups: dict[str, Any] = {
        "entry_rules": copy.deepcopy(specification["entry_rules"]),
        "exit_rules": copy.deepcopy(specification["exit_rules"]),
        "stop_loss_rule": copy.deepcopy(specification["stop_loss_rule"]),
        "take_profit_rule": copy.deepcopy(specification["take_profit_rule"]),
        "position_sizing_rule": copy.deepcopy(specification["position_sizing_rule"]),
    }
    for path, value in overrides:
        _set_override_path(rule_groups, path, value)

    try:
        entry_rule_models = [DraftRule.model_validate(r) for r in rule_groups["entry_rules"]]
        exit_rule_models = [DraftRule.model_validate(r) for r in rule_groups["exit_rules"]]
        stop_loss_model = StopLossRule.model_validate(rule_groups["stop_loss_rule"])
        take_profit_model = TakeProfitRule.model_validate(rule_groups["take_profit_rule"])
        position_sizing_model = PositionSizingRule.model_validate(rule_groups["position_sizing_rule"])
    except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError 등
        raise BacktestSpecificationError(
            "INVALID_PARAMETER_RANGE", f"Override된 값이 유효 범위를 벗어났습니다: {exc}"
        ) from exc

    entry_reqs, entry_unsupported = _extract_indicator_requirements(entry_rule_models)
    exit_reqs, exit_unsupported = _extract_indicator_requirements(exit_rule_models)
    unsupported = entry_unsupported + exit_unsupported
    if unsupported:
        raise BacktestSpecificationError("UNSUPPORTED_PARAMETER", "; ".join(unsupported))

    merged_requirements: dict[tuple[str, int | None], dict[str, Any]] = {}
    for req in entry_reqs + exit_reqs:
        merged_requirements[(req["indicator"], req["period"])] = req
    indicator_requirements = sorted(
        merged_requirements.values(), key=lambda r: (r["indicator"], r["period"] or 0)
    )

    rule_payload = {
        "entry_rules": [r.model_dump() for r in entry_rule_models],
        "exit_rules": [r.model_dump() for r in exit_rule_models],
        "stop_loss_rule": stop_loss_model.model_dump(),
        "take_profit_rule": take_profit_model.model_dump(),
        "position_sizing_rule": position_sizing_model.model_dump(),
    }
    canonical = {
        "compiler_version": specification["compiler_version"],
        "definition_hash": specification["definition_hash"],
        **rule_payload,
        "indicator_requirements": indicator_requirements,
        "timeframe": specification.get("timeframe"),
        "market_type": specification.get("market_type"),
        "required_runtime_inputs": specification["required_runtime_inputs"],
    }
    executable_hash = _hash(_canonical_json(canonical))

    overridden = dict(specification)
    overridden.update(rule_payload)
    overridden["indicator_requirements"] = indicator_requirements
    overridden["executable_hash"] = executable_hash
    return overridden
