"""STEP 12-7 — 범용 Rule Evaluator.

Compiler(backtest_spec.py)가 이미 검증한(지원 Indicator/Operator만 통과한)
Specification만 소비한다 — 여기서 Compiler의 Validation을 다시 구현하지
않는다(§2.2). Indicator 계산은 기존 `stock_platform.indicators.engine`의
순수 함수(`_rolling_mean`/`_ema`/`_rsi_wilder` — Decimal 기반, Wilder's
RSI)를 그대로 재사용한다(§7 — legacy `indicators.simple`은 모듈 자체
docstring이 "단위 테스트·레거시 STEP34 호환"이라 명시해 재사용 대상에서
제외했다).

Right Operand 정책(§4, §6): DraftRule은 `threshold`(필수)와
`comparison_target`(선택)을 함께 가진다. 기본은 "Indicator vs 고정
threshold"다. `comparison_target`이 있으면 **화이트리스트 형식
`SMA:{period}` / `EMA:{period}`만** 허용해 두 Indicator 비교(예: MA5
CROSS_ABOVE MA20)를 수행한다. 그 외 문자열은 fail-closed.

Cross 정책(§6): 이전 값이 없으면(첫 유효 index, 또는 lookback 기간
미충족으로 Indicator 값이 아직 없음) `insufficient_data`로 처리하고
matched=False를 반환한다(관대하게 True로 처리하지 않음).

Decimal 비교 정책: EQ/NE는 프로젝트에 확립된 tolerance 정책이 없으므로
정확한 Decimal 동등 비교를 사용한다(임의 tolerance 추가 금지, §6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from stock_platform.indicators.engine import _ema, _rolling_mean, _rsi_wilder

# comparison_target 화이트리스트 — 임의 필드명/심볼 비교 금지.
_INDICATOR_REF_PATTERN = re.compile(r"^(SMA|EMA):([1-9][0-9]{0,2})$", re.IGNORECASE)

SUPPORTED_INDICATORS = frozenset({"SMA", "EMA", "RSI"})
_DEFAULT_RSI_PERIOD = 14


def parse_comparison_indicator_ref(raw: str | None) -> tuple[str, int] | None:
    """`SMA:20` / `EMA:20`만 해석한다. 그 외는 None(호출측 fail-closed)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    matched = _INDICATOR_REF_PATTERN.match(text)
    if matched is None:
        return None
    period = int(matched.group(2))
    if period > 500:
        return None
    return matched.group(1).upper(), period


class RuleEvaluationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RuleEvaluationResult:
    matched: bool
    left_value: Decimal | None
    right_value: Decimal | None
    previous_left_value: Decimal | None = None
    previous_right_value: Decimal | None = None
    error_code: str | None = None
    reason: str = ""


def _compute_indicator_series(
    indicator: str, closes: list[Decimal], period: int
) -> list[Decimal | None]:
    if indicator == "SMA":
        return _rolling_mean(closes, period)
    if indicator == "EMA":
        return _ema(closes, period)
    if indicator == "RSI":
        return _rsi_wilder(closes, period)
    raise RuleEvaluationError("UNSUPPORTED_INDICATOR", f"unsupported indicator: {indicator}")


class IndicatorCache:
    """단일 Backtest 실행(=단일 Adapter 인스턴스) 범위에 한정된 캐시.

    전역 mutable 상태가 아니다 — 인스턴스마다 새로 생성되고, 실행이
    끝나면 인스턴스와 함께 버려진다(§7 캐시 격리 요구사항)."""

    def __init__(self, closes: list[Decimal]) -> None:
        self._closes = closes
        self._series: dict[tuple[str, int], list[Decimal | None]] = {}

    def value_at(self, indicator: str, period: int, index: int) -> Decimal | None:
        key = (indicator, period)
        series = self._series.get(key)
        if series is None:
            series = _compute_indicator_series(indicator, self._closes, period)
            self._series[key] = series
        if index < 0 or index >= len(series):
            return None
        return series[index]


def _resolve_period(rule: Any) -> int:
    if rule.lookback is not None:
        return int(rule.lookback)
    if rule.indicator == "RSI":
        return _DEFAULT_RSI_PERIOD
    # SMA/EMA는 프로젝트 전반에 걸쳐 확립된 기본 period가 없으므로
    # 명시적으로 요구한다(임의 기본값 금지).
    raise RuleEvaluationError(
        "MISSING_INDICATOR_PERIOD",
        f"{rule.indicator} Rule은 lookback(period)이 반드시 필요합니다.",
    )


def evaluate_rule(
    rule: Any, *, cache: IndicatorCache, index: int
) -> RuleEvaluationResult:
    """단일 DraftRule을 index 시점에서 평가한다. index 이후 데이터는
    절대 사용하지 않는다(§2.4 — IndicatorCache가 캐시하는 시계열 자체가
    이미 각 위치까지의 데이터만으로 계산되어 있어 구조적으로 보장된다)."""

    comparison_ref = parse_comparison_indicator_ref(getattr(rule, "comparison_target", None))
    if rule.comparison_target is not None and comparison_ref is None:
        return RuleEvaluationResult(
            matched=False,
            left_value=None,
            right_value=None,
            error_code="UNSUPPORTED_RULE_FIELD",
            reason=f"comparison_target 비교는 지원하지 않습니다: {rule.comparison_target}",
        )
    if rule.indicator not in SUPPORTED_INDICATORS:
        return RuleEvaluationResult(
            matched=False,
            left_value=None,
            right_value=None,
            error_code="UNSUPPORTED_INDICATOR",
            reason=f"unsupported indicator: {rule.indicator}",
        )

    period = _resolve_period(rule)
    left_value = cache.value_at(rule.indicator, period, index)
    if comparison_ref is None:
        right_value = Decimal(str(rule.threshold))
        previous_right = right_value
    else:
        right_indicator, right_period = comparison_ref
        right_value = cache.value_at(right_indicator, right_period, index)
        previous_right = (
            cache.value_at(right_indicator, right_period, index - 1) if index > 0 else None
        )

    if left_value is None or right_value is None:
        return RuleEvaluationResult(
            matched=False,
            left_value=left_value,
            right_value=right_value,
            error_code="INSUFFICIENT_DATA",
            reason="indicator 값이 아직 없습니다(lookback 기간 미충족).",
        )

    operator = rule.operator
    if operator in {"GT", "GTE", "LT", "LTE", "EQ", "NE"}:
        matched = {
            "GT": left_value > right_value,
            "GTE": left_value >= right_value,
            "LT": left_value < right_value,
            "LTE": left_value <= right_value,
            "EQ": left_value == right_value,
            "NE": left_value != right_value,
        }[operator]
        return RuleEvaluationResult(
            matched=matched, left_value=left_value, right_value=right_value
        )

    if operator in {"CROSS_ABOVE", "CROSS_BELOW"}:
        previous_left = cache.value_at(rule.indicator, period, index - 1) if index > 0 else None
        if previous_left is None or previous_right is None:
            return RuleEvaluationResult(
                matched=False,
                left_value=left_value,
                right_value=right_value,
                previous_left_value=previous_left,
                previous_right_value=previous_right,
                error_code="INSUFFICIENT_DATA",
                reason="이전 index 값이 없어 Cross를 판정할 수 없습니다(첫 유효 시점).",
            )
        if operator == "CROSS_ABOVE":
            matched = previous_left <= previous_right and left_value > right_value
        else:
            matched = previous_left >= previous_right and left_value < right_value
        return RuleEvaluationResult(
            matched=matched,
            left_value=left_value,
            right_value=right_value,
            previous_left_value=previous_left,
            previous_right_value=previous_right,
        )

    return RuleEvaluationResult(
        matched=False,
        left_value=left_value,
        right_value=right_value,
        error_code="UNSUPPORTED_OPERATOR",
        reason=f"unsupported operator: {operator}",
    )


def evaluate_group(
    rules: list[Any], *, logical_operator: str, cache: IndicatorCache, index: int
) -> bool:
    """Rule 목록을 AND/OR로 결합해 평가한다.

    §8/§9 정책(완료보고에 근거 기록): DraftRule 스키마 자체에 그룹/논리
    연산자 필드가 없다(단순 목록) — Draft 작성 관례(예: "RSI 과매도 AND
    가격이 지지선 위") 및 기존 STEP12-3 Validation이 "entry_rules 전체가
    승인 대상 조건 집합"으로 취급하는 것과 일관되게, entry_rules는 AND로
    결합한다(전부 충족해야 진입). exit_rules는 기존
    MovingAverageCrossStrategy의 실제 동작(Stop Loss OR Take Profit OR
    Dead Cross 중 하나라도 성립하면 즉시 청산)과 동일하게 OR로 결합한다.

    빈 Rule 목록은 항상 False(§8 — 빈 Entry Rule을 자동 진입으로 처리하지
    않음; Compiler가 이미 빈 Rule을 컴파일 실패로 막으므로 정상 경로에서는
    도달하지 않지만, 방어적으로 여기서도 안전한 기본값을 유지한다)."""

    if not rules:
        return False
    results = [evaluate_rule(r, cache=cache, index=index) for r in rules]
    if logical_operator == "AND":
        return all(r.matched for r in results)
    if logical_operator == "OR":
        return any(r.matched for r in results)
    raise RuleEvaluationError("INVALID_RULE_COMBINATION", f"unknown logical_operator: {logical_operator}")
