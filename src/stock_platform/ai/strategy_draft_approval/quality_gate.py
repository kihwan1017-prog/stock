"""STEP 12-10 — Strategy Quality Gate.

승인된 Strategy Definition의 기존 Backtest 결과(STEP12-7)와 Performance
Analytics(STEP12-8)/Walk-Forward 결과(STEP12-9)를 그대로 재사용해 Rule
기반 자동 품질 심사(PASS/WARNING/FAIL)를 수행하고 Recommendation(APPROVE/
MANUAL_REVIEW/REJECT)과 Risk Grade(SAFE/NORMAL/CAUTION/DANGER)를
산출한다. 새 Backtest를 실행하지 않는다 — 가장 최근의 기존 Backtest Run/
Walk-Forward Run을 조회만 한다.

기존 `strategy_deployment/policy_service.py`(StrategyApprovalPolicyService)
는 실시간 Runtime/Kill-Switch/AI Candidate Selection 기반의 별개
시스템(이진 APPROVED/REJECTED만 지원)이라 중복 확장하지 않았다 — 이
STEP은 STEP12-6~9로 이어진 Definition/Backtest/Walk-Forward 파이프라인
전용의, 3단계(PASS/WARNING/FAIL) Rule + Risk Grade를 갖는 새로운
분석·리포팅 계층이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    get_latest_primary_backtest_run_id,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.quality_gate_entities import (
    StrategyQualityGateReportEntity,
)
from stock_platform.backtest.persistence_models import BacktestRunEntity
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.performance.backtest_analytics import (
    _to_jsonable,
    analyze_backtest_run,
)
from stock_platform.performance.entities import StrategyPerformanceRunEntity
from stock_platform.performance.models import PerformanceRunType

ZERO = Decimal("0")

# § STEP12-16 인수 조건(STEP12-15 필수 인수 보완 2) — Quality Gate
# Report 자체에는 STEP12-10 당시 input_hash 개념이 없었다(조사 결과).
# Rule 평가 로직 자체의 버전을 나타내는 값으로, 이 Report의 저장 스키마를
# 바꾸지 않고 Provenance Hash 계산에만 쓰인다.
QUALITY_GATE_ALGORITHM_VERSION = "1.0.0"


class QualityGateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QualityGateThresholds:
    """각 Rule의 FAIL/WARNING 경계값(문서화된 기본값 — API로 재정의 가능).

    minimum_stability_score는 기존 WalkForwardStabilityAnalyzer(STEP12-9,
    재구현하지 않고 그대로 재사용)의 원본 스케일(양의 Window 비율 -
    수익률 표준편차 - MDD, 전부 퍼센트 단위 혼합)을 그대로 사용한다 —
    표준편차/MDD가 보통 수십 단위라 실제로는 0에 자주 clamp되는 경향이
    있음을 알고 있으나(기존 분석기의 공식이므로 이번 STEP에서 재설계하지
    않음), 임계값을 그 특성에 맞게 낮게 설정했다."""

    min_trade_count_fail: int = 5
    min_trade_count_warn: int = 15
    min_sharpe_ratio_fail: Decimal = Decimal("0")
    min_sharpe_ratio_warn: Decimal = Decimal("0.5")
    max_drawdown_rate_fail: Decimal = Decimal("40")
    max_drawdown_rate_warn: Decimal = Decimal("25")
    min_profit_factor_fail: Decimal = Decimal("1.0")
    min_profit_factor_warn: Decimal = Decimal("1.3")
    min_stability_score_fail: Decimal = Decimal("0")
    min_stability_score_warn: Decimal = Decimal("0.05")
    max_overfitting_score_fail: Decimal = Decimal("70")
    max_overfitting_score_warn: Decimal = Decimal("50")


@dataclass(frozen=True, slots=True)
class QualityRuleResult:
    rule_name: str
    actual_value: Decimal | int | None
    threshold: dict[str, Any]
    status: str  # PASS | WARNING | FAIL
    failure_reason: str


def _evaluate_min_rule(
    *, rule_name: str, actual: Decimal | int | None, fail_below: Any, warn_below: Any, unit: str = "",
) -> QualityRuleResult:
    threshold = {"fail_below": fail_below, "warn_below": warn_below}
    if actual is None:
        return QualityRuleResult(rule_name, None, threshold, "WARNING", f"{rule_name}: 평가할 데이터가 없습니다.")
    if actual < fail_below:
        return QualityRuleResult(
            rule_name, actual, threshold, "FAIL",
            f"{rule_name}: 실제값 {actual}{unit}이 최소 기준 {fail_below}{unit} 미만입니다.",
        )
    if actual < warn_below:
        return QualityRuleResult(
            rule_name, actual, threshold, "WARNING",
            f"{rule_name}: 실제값 {actual}{unit}이 권장 기준 {warn_below}{unit} 미만입니다.",
        )
    return QualityRuleResult(rule_name, actual, threshold, "PASS", "")


def _evaluate_max_rule(
    *, rule_name: str, actual: Decimal | None, fail_above: Any, warn_above: Any, unit: str = "",
) -> QualityRuleResult:
    threshold = {"fail_above": fail_above, "warn_above": warn_above}
    if actual is None:
        return QualityRuleResult(rule_name, None, threshold, "WARNING", f"{rule_name}: 평가할 데이터가 없습니다.")
    if actual > fail_above:
        return QualityRuleResult(
            rule_name, actual, threshold, "FAIL",
            f"{rule_name}: 실제값 {actual}{unit}이 최대 허용 기준 {fail_above}{unit}를 초과했습니다.",
        )
    if actual > warn_above:
        return QualityRuleResult(
            rule_name, actual, threshold, "WARNING",
            f"{rule_name}: 실제값 {actual}{unit}이 권장 기준 {warn_above}{unit}를 초과했습니다.",
        )
    return QualityRuleResult(rule_name, actual, threshold, "PASS", "")


def evaluate_rules(
    *,
    trade_count: int,
    sharpe_ratio: Decimal | None,
    maximum_drawdown_rate: Decimal,
    profit_factor: Decimal | None,
    stability_score: Decimal | None,
    overfitting_score: Decimal | None,
    thresholds: QualityGateThresholds,
) -> list[QualityRuleResult]:
    return [
        _evaluate_min_rule(
            rule_name="MINIMUM_TRADE_COUNT", actual=trade_count,
            fail_below=thresholds.min_trade_count_fail, warn_below=thresholds.min_trade_count_warn,
        ),
        _evaluate_min_rule(
            rule_name="MINIMUM_SHARPE_RATIO", actual=sharpe_ratio,
            fail_below=thresholds.min_sharpe_ratio_fail, warn_below=thresholds.min_sharpe_ratio_warn,
        ),
        _evaluate_max_rule(
            rule_name="MAXIMUM_DRAWDOWN", actual=maximum_drawdown_rate,
            fail_above=thresholds.max_drawdown_rate_fail, warn_above=thresholds.max_drawdown_rate_warn, unit="%",
        ),
        _evaluate_min_rule(
            rule_name="MINIMUM_PROFIT_FACTOR", actual=profit_factor,
            fail_below=thresholds.min_profit_factor_fail, warn_below=thresholds.min_profit_factor_warn,
        ),
        _evaluate_min_rule(
            rule_name="MINIMUM_STABILITY_SCORE", actual=stability_score,
            fail_below=thresholds.min_stability_score_fail, warn_below=thresholds.min_stability_score_warn,
        ),
        _evaluate_max_rule(
            rule_name="MAXIMUM_OVERFITTING_SCORE", actual=overfitting_score,
            fail_above=thresholds.max_overfitting_score_fail, warn_above=thresholds.max_overfitting_score_warn,
        ),
    ]


def determine_recommendation(rules: list[QualityRuleResult]) -> str:
    """하나라도 FAIL이면 REJECT, WARNING만 있으면 MANUAL_REVIEW, 전부
    PASS면 APPROVE(Fail Closed — WARNING을 임의로 무시하고 APPROVE로
    격상하지 않는다)."""

    if any(r.status == "FAIL" for r in rules):
        return "REJECT"
    if any(r.status == "WARNING" for r in rules):
        return "MANUAL_REVIEW"
    return "APPROVE"


def determine_risk_grade(rules: list[QualityRuleResult]) -> tuple[str, dict[str, Any]]:
    """FAIL/WARNING 개수 기반 4단계 등급. 근거(각 상태 개수와 판정 규칙)를
    함께 반환해 저장한다(§ 점수 산출 근거)."""

    fail_count = sum(1 for r in rules if r.status == "FAIL")
    warning_count = sum(1 for r in rules if r.status == "WARNING")
    reason = {
        "fail_count": fail_count,
        "warning_count": warning_count,
        "pass_count": sum(1 for r in rules if r.status == "PASS"),
        "rule_count": len(rules),
    }
    if fail_count >= 1:
        grade = "DANGER"
        reason["basis"] = "1개 이상 FAIL"
    elif warning_count >= 3:
        grade = "DANGER"
        reason["basis"] = "WARNING 3개 이상"
    elif warning_count >= 1:
        grade = "CAUTION"
        reason["basis"] = "WARNING 1~2개"
    else:
        # 전부 PASS — 여유(margin)까지 확인해 SAFE/NORMAL을 구분한다.
        overfitting_rule = next(r for r in rules if r.rule_name == "MAXIMUM_OVERFITTING_SCORE")
        drawdown_rule = next(r for r in rules if r.rule_name == "MAXIMUM_DRAWDOWN")
        comfortable = (
            overfitting_rule.actual_value is not None
            and overfitting_rule.actual_value <= Decimal("25")
            and drawdown_rule.actual_value is not None
            and drawdown_rule.actual_value <= Decimal("15")
        )
        if comfortable:
            grade = "SAFE"
            reason["basis"] = "전 항목 PASS이며 MDD<=15%, Overfitting<=25로 여유 있음"
        else:
            grade = "NORMAL"
            reason["basis"] = "전 항목 PASS이나 일부 지표가 경고 기준에 근접"
    return grade, reason


def _latest_backtest_run(session: Session, strategy_definition_id: int) -> BacktestRunEntity | None:
    """§ STEP12-15 인수 조건(STEP12-14 필수 인수 보완 1) — Walk-Forward
    Window/Parameter Sensitivity Base·Variation Run을 "대표 Backtest"로
    잘못 선택하지 않도록 공용 Helper(`get_latest_primary_backtest_run_id`)
    를 재사용한다(중복 구현 금지, 단순 PK DESC만 쓰지 않음)."""
    run_id = get_latest_primary_backtest_run_id(session, strategy_definition_id)
    if run_id is None:
        return None
    return BacktestRepository(session).get_run(run_id)


def _latest_walk_forward_run(session: Session, strategy_definition_id: int) -> StrategyPerformanceRunEntity | None:
    # completed_at만으로는 동시 완료 시 정렬이 비결정적일 수 있어(STEP12-11
    # 인수 조건 §3) PK를 2차 정렬 기준으로 추가해 완전히 결정적으로 만든다.
    return session.scalar(
        select(StrategyPerformanceRunEntity)
        .where(
            StrategyPerformanceRunEntity.strategy_id == strategy_definition_id,
            StrategyPerformanceRunEntity.run_type == PerformanceRunType.WALK_FORWARD.value,
            StrategyPerformanceRunEntity.status_code == "COMPLETED",
        )
        .order_by(
            StrategyPerformanceRunEntity.completed_at.desc(),
            StrategyPerformanceRunEntity.strategy_performance_run_id.desc(),
        )
        .limit(1)
    )


def run_quality_gate(
    session: Session,
    strategy_definition_id: int,
    *,
    actor: str,
    thresholds: QualityGateThresholds | None = None,
) -> dict[str, Any]:
    """가장 최근의 기존 Backtest Run(필수)과 Walk-Forward Run(선택)을
    조회해 Quality Gate를 평가하고 저장한다. Backtest Run이 하나도 없으면
    평가할 데이터 자체가 없으므로 Fail Closed로 차단한다(새 Backtest를
    실행하지 않는다는 이번 STEP의 명시적 제약)."""

    thresholds = thresholds or QualityGateThresholds()

    backtest_run = _latest_backtest_run(session, strategy_definition_id)
    if backtest_run is None:
        raise QualityGateError(
            "NO_BACKTEST_AVAILABLE",
            "이 Strategy Definition에 대해 실행된 Backtest가 없어 품질 심사를 수행할 수 없습니다.",
        )

    analysis = analyze_backtest_run(session, int(backtest_run.backtest_run_id))
    kpi = analysis["kpi"]

    walk_forward_run = _latest_walk_forward_run(session, strategy_definition_id)
    stability_score: Decimal | None = None
    overfitting_score: Decimal | None = None
    if walk_forward_run is not None:
        wf_payload = walk_forward_run.result_payload or {}
        stability = wf_payload.get("stability") or {}
        if stability.get("stability_score") is not None:
            stability_score = Decimal(str(stability["stability_score"]))
        if wf_payload.get("overfitting_score") is not None:
            overfitting_score = Decimal(str(wf_payload["overfitting_score"]))

    rules = evaluate_rules(
        trade_count=kpi["trade_count"],
        sharpe_ratio=kpi["sharpe_ratio"],
        maximum_drawdown_rate=kpi["maximum_drawdown_rate"],
        profit_factor=kpi["profit_factor"],
        stability_score=stability_score,
        overfitting_score=overfitting_score,
        thresholds=thresholds,
    )
    recommendation = determine_recommendation(rules)
    risk_grade, risk_grade_reason = determine_risk_grade(rules)

    rules_payload = _to_jsonable(
        [
            {
                "rule_name": r.rule_name,
                "actual_value": r.actual_value,
                "threshold": r.threshold,
                "status": r.status,
                "failure_reason": r.failure_reason,
            }
            for r in rules
        ]
    )
    threshold_payload = _to_jsonable(
        {
            "min_trade_count_fail": thresholds.min_trade_count_fail,
            "min_trade_count_warn": thresholds.min_trade_count_warn,
            "min_sharpe_ratio_fail": thresholds.min_sharpe_ratio_fail,
            "min_sharpe_ratio_warn": thresholds.min_sharpe_ratio_warn,
            "max_drawdown_rate_fail": thresholds.max_drawdown_rate_fail,
            "max_drawdown_rate_warn": thresholds.max_drawdown_rate_warn,
            "min_profit_factor_fail": thresholds.min_profit_factor_fail,
            "min_profit_factor_warn": thresholds.min_profit_factor_warn,
            "min_stability_score_fail": thresholds.min_stability_score_fail,
            "min_stability_score_warn": thresholds.min_stability_score_warn,
            "max_overfitting_score_fail": thresholds.max_overfitting_score_fail,
            "max_overfitting_score_warn": thresholds.max_overfitting_score_warn,
        }
    )

    report = StrategyQualityGateReportEntity(
        strategy_id=strategy_definition_id,
        backtest_run_id=int(backtest_run.backtest_run_id),
        walk_forward_run_id=(
            int(walk_forward_run.strategy_performance_run_id) if walk_forward_run is not None else None
        ),
        recommendation=recommendation,
        risk_grade=risk_grade,
        rules_payload=rules_payload,
        threshold_payload=threshold_payload,
        risk_grade_reason=_to_jsonable(risk_grade_reason),
        requested_by=actor,
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    return _to_report_dict(report)


def _to_report_dict(report: StrategyQualityGateReportEntity) -> dict[str, Any]:
    return {
        "quality_gate_report_id": int(report.quality_gate_report_id),
        "strategy_id": report.strategy_id,
        "backtest_run_id": report.backtest_run_id,
        "walk_forward_run_id": report.walk_forward_run_id,
        "recommendation": report.recommendation,
        "risk_grade": report.risk_grade,
        "rules": report.rules_payload,
        "thresholds": report.threshold_payload,
        "risk_grade_reason": report.risk_grade_reason,
        "requested_by": report.requested_by,
        "created_at": report.created_at,
    }


def get_quality_report(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    """report_id로 조회하되, `strategy_definition_id`가 함께 주어지면
    보고서의 실제 소유 Strategy와 일치하는지 검증한다(STEP12-11 인수
    조건 §4에서 발견 — API가 URL의 strategy_id를 무시하고 report_id만으로
    조회해 다른 Strategy의 보고서를 열람할 수 있었던 문제 수정). 불일치는
    존재 여부를 노출하지 않도록 NOT_FOUND와 동일하게 처리한다."""

    report = session.get(StrategyQualityGateReportEntity, report_id)
    if report is None:
        raise QualityGateError("NOT_FOUND", f"Quality Gate report not found: {report_id}")
    if strategy_definition_id is not None and report.strategy_id != strategy_definition_id:
        raise QualityGateError("NOT_FOUND", f"Quality Gate report not found: {report_id}")
    return _to_report_dict(report)


def get_recommendation(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_quality_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "quality_gate_report_id": report["quality_gate_report_id"],
        "strategy_id": report["strategy_id"],
        "recommendation": report["recommendation"],
        "risk_grade": report["risk_grade"],
        "risk_grade_reason": report["risk_grade_reason"],
    }


def compute_quality_gate_provenance_hash(
    session: Session, report: StrategyQualityGateReportEntity
) -> str:
    """§ STEP12-16 인수 조건(STEP12-15 필수 인수 보완 2) — Quality Gate
    Report 자체에는 input_hash가 없어(조사 결과) Promotion Commit이
    검증할 수 있는 canonical 지문을 이 Helper 하나로 계산한다(Quality
    Gate 원본 테이블/스키마는 변경하지 않음). 참조하는 Backtest Run의
    executable_hash/runtime_input_hash까지 포함해, Source 중 하나라도
    달라지면 다른 Hash가 되도록 한다. Decision Package(STEP12-15)도 이
    Helper 하나만 재사용한다(중복 계산 금지)."""
    executable_hash = None
    runtime_input_hash = None
    if report.backtest_run_id is not None:
        run = BacktestRepository(session).get_run(report.backtest_run_id)
        if run is not None:
            params = run.parameters or {}
            executable_hash = params.get("executable_hash")
            runtime_input_hash = params.get("runtime_input_hash")
    canonical = {
        "quality_gate_report_id": int(report.quality_gate_report_id),
        "strategy_definition_id": report.strategy_id,
        "backtest_run_id": report.backtest_run_id,
        "walk_forward_run_id": report.walk_forward_run_id,
        "executable_hash": executable_hash,
        "runtime_input_hash": runtime_input_hash,
        "recommendation": report.recommendation,
        "risk_grade": report.risk_grade,
        "rules": report.rules_payload,
        "algorithm_version": QUALITY_GATE_ALGORITHM_VERSION,
    }
    return _hash(_canonical_json(canonical))
