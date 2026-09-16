"""STEP 12-14 — Strategy Explainability & Decision Evidence Layer.

이미 생성된 Strategy Definition과 이미 완료된 검증 Report(Backtest/
Performance Analytics/Walk-Forward/Quality Gate/Parameter Sensitivity/
Monte Carlo/Portfolio Validation)만 읽어 사람이 이해할 수 있는 설명 +
Evidence Reference로 재구성한다. 새 Backtest나 검증 계산을 수행하지
않는다 — Performance Analytics도 `analyze_backtest_run()`을 재실행하지
않고 `backtest_run.parameters.performance_analytics`에 이미 저장된
값만 읽는다(STEP12-15 인수 조건 §2, STEP12-14에서는 재실행했던 것을
수정 — Explainability 요청 자체가 검증 결과를 변경/재저장하면 안
된다). 저장된 값이 없으면 계산하지 않고 NOT_AVAILABLE로 처리한다.
자동 승인·반려·Promotion도 수행하지 않는다.

핵심 원칙 — SOURCE_FACT와 INTERPRETATION을 하나의 필드에 섞지 않는다:
SOURCE_FACT는 기존 Report에서 그대로 읽은 값(Evidence Reference의
`source_value`)이고, INTERPRETATION은 결정적 Rule Template으로 생성한
설명 문장이다. 모든 핵심 설명 문장은 Evidence Reference를 갖는다.

재사용(중복 생성 금지 확인):
- Strategy Overview/Provenance: STEP12-5 `check_readiness()`/
  STEP12-5 `resolve_strategy_provenance()`를 재사용(derived clone 포함).
- Entry/Exit/Stop Loss/Take Profit/Position Sizing 규칙: STEP12-6
  `compile_specification()`이 반환하는 정규화된 Rule Payload를 그대로
  읽는다(새 Rule Evaluator/Compiler를 만들지 않음).
- Backtest: `BacktestRunEntity` 자체 컬럼만 읽음(실행 시 이미 저장된
  사실). Performance: STEP12-8이 과거에 계산해 `parameters
  .performance_analytics`에 저장해 둔 값이 있으면 그것만 읽음(새
  Performance Analyzer 없음, 재계산 없음).
- Walk-Forward: STEP12-9 `get_walk_forward_detail()`/
  `get_overfitting_report()`를 그대로 재사용.
- Quality Gate/Parameter Sensitivity/Monte Carlo/Portfolio Validation:
  각 STEP의 `get_*_report()`를 그대로 재사용(재계산 없음, Entity를 직접
  session.get()으로만 조회).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    get_latest_primary_backtest_run_id,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    _canonical_json,
    _hash,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.explainability_entities import (
    StrategyExplainabilityReportEntity,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo import MonteCarloError
from stock_platform.ai.strategy_draft_approval.monte_carlo_entities import (
    MonteCarloSimulationReportEntity,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    ParameterSensitivityError,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity_entities import (
    ParameterSensitivityReportEntity,
)
from stock_platform.ai.strategy_draft_approval.portfolio_validation import (
    PortfolioValidationError,
)
from stock_platform.ai.strategy_draft_approval.portfolio_validation_entities import (
    PortfolioValidationReportEntity,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import QualityGateError
from stock_platform.ai.strategy_draft_approval.quality_gate_entities import (
    StrategyQualityGateReportEntity,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    _require_definition,
    check_readiness,
    resolve_strategy_provenance,
)
from stock_platform.ai.strategy_draft_approval.walk_forward import WalkForwardError
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.performance.backtest_analytics import _to_jsonable
from stock_platform.performance.entities import StrategyPerformanceRunEntity
from stock_platform.performance.models import PerformanceRunType

ZERO = Decimal("0")
HUNDRED = Decimal("100")

ALGORITHM_VERSION = "1.0.0"
TEMPLATE_VERSION = "1.0.0"

# RULE_BASED_WITH_LLM_ASSIST는 이번 STEP에서 구현하지 않는다(요구사항
# 문서가 명시적으로 허용한 범위 축소 — "RULE_BASED만 구현해도 된다").
# Unsupported Explanation Mode는 Fail Closed로 차단한다(임의로 RULE_BASED
# 로 강등하지 않음).
SUPPORTED_EXPLANATION_MODES = frozenset({"RULE_BASED"})
DEFAULT_EXPLANATION_MODE = "RULE_BASED"
SUPPORTED_LANGUAGES = frozenset({"ko"})
DEFAULT_LANGUAGE = "ko"

# 완전성 점수 가중치(합계 100) — 요구사항 문서의 예시 가중치를 그대로
# 채택한다. Portfolio는 별도 선택 항목이라 기본 100에는 포함하지 않고,
# Portfolio Report가 실제로 선택된 경우에만 분모에 加산한다(§ 정책 구분).
BASE_EVIDENCE_WEIGHTS: dict[str, Decimal] = {
    "strategy_specification": Decimal("15"),
    "backtest": Decimal("20"),
    "performance_analytics": Decimal("15"),
    "walk_forward": Decimal("10"),
    "quality_gate": Decimal("15"),
    "parameter_sensitivity": Decimal("10"),
    "monte_carlo": Decimal("10"),
    "provenance": Decimal("5"),
}
PORTFOLIO_EVIDENCE_WEIGHT = Decimal("10")

# Completeness Status 경계값(문서화된 값) — score는 0~100.
_COMPLETENESS_THRESHOLDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("90"), "COMPLETE"),
    (Decimal("70"), "SUBSTANTIAL"),
    (Decimal("40"), "PARTIAL"),
)

# Decision Checklist §6 — Monte Carlo Risk of Ruin 허용 상한(문서화된 값).
MONTE_CARLO_RISK_OF_RUIN_THRESHOLD_PERCENT = Decimal("20")

_OPERATOR_KOREAN: dict[str, str] = {
    "GT": "초과일",
    "GTE": "이상일",
    "LT": "미만일",
    "LTE": "이하일",
    "EQ": "같을",
    "CROSS_ABOVE": "상향 돌파할",
    "CROSS_BELOW": "하향 돌파할",
}

_QUALITY_GATE_RULE_LABEL: dict[str, str] = {
    "MINIMUM_TRADE_COUNT": "최소 거래 수",
    "MINIMUM_SHARPE_RATIO": "Sharpe Ratio",
    "MAXIMUM_DRAWDOWN": "최대 낙폭(MDD)",
    "MINIMUM_PROFIT_FACTOR": "Profit Factor",
    "MINIMUM_STABILITY_SCORE": "Stability Score",
    "MAXIMUM_OVERFITTING_SCORE": "Overfitting Score",
}


class ExplainabilityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Evidence Reference 수집 — 결정적 순서(카테고리 고정 순서 + 호출 순서),
# 매 Report마다 새로 채번(EV-0001부터)한다.
# ---------------------------------------------------------------------------


@dataclass
class _EvidenceCollector:
    items: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        *,
        evidence_type: str,
        source_report_type: str,
        source_report_id: int | None,
        source_field: str,
        source_value: Any,
        source_status: str,
        threshold: Any = None,
        comparison_operator: str | None = None,
        interpretation_code: str | None = None,
    ) -> str:
        evidence_id = f"EV-{len(self.items) + 1:04d}"
        self.items.append(
            {
                "evidence_id": evidence_id,
                "evidence_type": evidence_type,
                "source_report_type": source_report_type,
                "source_report_id": source_report_id,
                "source_field": source_field,
                "source_value": _to_jsonable(source_value),
                "source_status": source_status,
                "threshold": _to_jsonable(threshold),
                "comparison_operator": comparison_operator,
                "interpretation_code": interpretation_code,
            }
        )
        return evidence_id


@dataclass
class _CategoryOutcome:
    name: str
    status: str  # AVAILABLE | NOT_AVAILABLE | NOT_REQUESTED | INCOMPATIBLE | PROVENANCE_MISMATCH
    weight: Decimal
    achieved: Decimal
    summary_bucket: str | None = None  # POSITIVE | WARNING | BLOCKING | None
    summary_code: str | None = None


# ---------------------------------------------------------------------------
# Source Report Selection — 명시 ID 우선, 없으면 결정적 최신 선택(PK DESC).
# 선택된 모든 Report는 대상 Strategy와 소유 관계가 일치해야 한다(다른
# Strategy의 Report를 끼워 넣는 행위 차단).
# ---------------------------------------------------------------------------


def _latest_backtest_run_id(session: Session, strategy_definition_id: int) -> int | None:
    """§ STEP12-15 인수 조건(STEP12-14 필수 인수 보완 1) — Walk-Forward
    Window/Parameter Sensitivity Base·Variation Run이 "대표 Backtest"로
    잘못 선택되지 않도록 공용 Helper를 재사용한다(quality_gate.py의
    `_latest_backtest_run()`과 동일한 Helper — 중복 구현 금지)."""
    return get_latest_primary_backtest_run_id(session, strategy_definition_id)


def _latest_walk_forward_run_id(session: Session, strategy_definition_id: int) -> int | None:
    row = session.scalar(
        select(StrategyPerformanceRunEntity.strategy_performance_run_id)
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
    return int(row) if row is not None else None


def _latest_quality_gate_report_id(session: Session, strategy_definition_id: int) -> int | None:
    row = session.scalar(
        select(StrategyQualityGateReportEntity.quality_gate_report_id)
        .where(StrategyQualityGateReportEntity.strategy_id == strategy_definition_id)
        .order_by(StrategyQualityGateReportEntity.quality_gate_report_id.desc())
        .limit(1)
    )
    return int(row) if row is not None else None


def _latest_parameter_sensitivity_report_id(session: Session, strategy_definition_id: int) -> int | None:
    row = session.scalar(
        select(ParameterSensitivityReportEntity.parameter_sensitivity_report_id)
        .where(ParameterSensitivityReportEntity.strategy_id == strategy_definition_id)
        .order_by(ParameterSensitivityReportEntity.parameter_sensitivity_report_id.desc())
        .limit(1)
    )
    return int(row) if row is not None else None


def _latest_monte_carlo_report_id(session: Session, strategy_definition_id: int) -> int | None:
    row = session.scalar(
        select(MonteCarloSimulationReportEntity.monte_carlo_report_id)
        .where(MonteCarloSimulationReportEntity.strategy_id == strategy_definition_id)
        .order_by(MonteCarloSimulationReportEntity.monte_carlo_report_id.desc())
        .limit(1)
    )
    return int(row) if row is not None else None


def _latest_portfolio_validation_report_id(session: Session, strategy_definition_id: int) -> int | None:
    """Portfolio Validation Report는 strategy_definition_ids가 JSONB
    배열이라(다대다) 인덱스 조회가 아니라 포함 여부(`@>`)로 찾는다."""
    from sqlalchemy import cast, text
    from sqlalchemy.dialects.postgresql import JSONB

    row = session.scalar(
        select(PortfolioValidationReportEntity.portfolio_validation_report_id)
        .where(
            PortfolioValidationReportEntity.strategy_definition_ids.op("@>")(
                cast(text(f"'[{strategy_definition_id}]'"), JSONB)
            )
        )
        .order_by(PortfolioValidationReportEntity.portfolio_validation_report_id.desc())
        .limit(1)
    )
    return int(row) if row is not None else None


# ---------------------------------------------------------------------------
# Strategy Overview + Rule Explanation.
# ---------------------------------------------------------------------------


def _build_strategy_overview(
    session: Session, strategy_definition_id: int, evidence: _EvidenceCollector
) -> dict[str, Any]:
    from stock_platform.ai.strategy_draft_approval.entities import StrategyDraftApprovalEntity

    definition = _require_definition(session, strategy_definition_id)
    payload = definition.parameter_payload or {}

    approval_status = "UNKNOWN"
    if definition.approval_id is not None:
        approval = session.get(StrategyDraftApprovalEntity, int(definition.approval_id))
        if approval is not None:
            approval_status = approval.status
    elif definition.approved_at is not None:
        approval_status = "APPROVED"

    overview = {
        "strategy_definition_id": int(definition.strategy_id),
        "strategy_name": definition.name,
        "strategy_code": definition.strategy_code,
        "definition_version": definition.definition_version,
        "owner_type": definition.owner_type,
        "market_type": payload.get("source_market_type"),
        # Exchange/Symbol은 Definition 자체에 없다(§ backtest_spec.py 모듈
        # docstring — 전략 정의는 종목 독립적 Template, 종목/기간/자본금은
        # 실행 시 주입). 선택된 Backtest Run이 있으면 그 Run의 실제 실행
        # 종목으로 채운다(orchestration에서 보강).
        "exchange": None,
        "symbol": None,
        "symbol_note": "Strategy Definition은 종목 독립적 Template입니다 — Symbol/Exchange는 선택된 Backtest Run의 실행 조건입니다.",
        "timeframe": payload.get("timeframe"),
        "approval_status": approval_status,
        "is_active": bool(definition.is_active),
        "executable_hash": None,
        "definition_hash": definition.definition_hash,
    }
    evidence.add(
        evidence_type="STRATEGY_RULE",
        source_report_type="STRATEGY_DEFINITION",
        source_report_id=int(definition.strategy_id),
        source_field="name/market_type/owner_type/approval_status",
        source_value={
            "strategy_name": overview["strategy_name"],
            "market_type": overview["market_type"],
            "owner_type": overview["owner_type"],
            "approval_status": overview["approval_status"],
        },
        source_status="AVAILABLE",
    )
    return overview


def _rule_sentence(rule: dict[str, Any], *, action: str) -> str:
    indicator = rule.get("indicator")
    lookback = rule.get("lookback")
    operator_kor = _OPERATOR_KOREAN.get(rule.get("operator"))
    threshold = rule.get("threshold")
    if operator_kor is None:
        return f"{indicator} 규칙은 현재 자연어 설명 Template이 지원하지 않아 자동 설명을 생성할 수 없습니다."
    indicator_label = f"{indicator}({lookback})" if lookback is not None else str(indicator)
    return f"{indicator_label}가 {threshold} {operator_kor} 때 {action} 신호를 생성합니다."


def _build_rule_explanation(
    specification: dict[str, Any], evidence: _EvidenceCollector
) -> dict[str, Any]:
    entry_rules = specification.get("entry_rules") or []
    exit_rules = specification.get("exit_rules") or []
    stop_loss = specification.get("stop_loss_rule") or {}
    take_profit = specification.get("take_profit_rule") or {}
    position_sizing = specification.get("position_sizing_rule") or {}

    entry_sentences = [_rule_sentence(r, action="매수") for r in entry_rules]
    exit_sentences = [_rule_sentence(r, action="청산") for r in exit_rules]

    entry_combination = (
        "다음 조건을 모두(AND) 만족하면 매수 신호를 생성합니다." if len(entry_rules) > 1 else None
    )
    exit_combination = (
        "다음 조건 중 하나라도(OR) 만족하면 청산 신호를 생성합니다." if len(exit_rules) > 1 else None
    )

    stop_loss_value = stop_loss.get("value")
    take_profit_value = take_profit.get("value")
    position_value = position_sizing.get("value")

    stop_loss_sentence = (
        f"진입가 대비 {stop_loss_value}% 하락 시 손절합니다." if stop_loss_value is not None else None
    )
    take_profit_sentence = (
        f"진입가 대비 {take_profit_value}% 상승 시 익절합니다." if take_profit_value is not None else None
    )
    position_sizing_sentence = (
        f"자본의 {(Decimal(str(position_value)) * HUNDRED).normalize()}%를 진입 규모로 사용합니다."
        if position_value is not None
        else None
    )

    exit_priority = [
        "1) Stop Loss(손절)",
        "2) Take Profit(익절)",
        "3) 명시적 Exit Rule",
    ]
    exit_priority_note = (
        "같은 시점에 Stop Loss와 Take Profit 조건이 동시에 성립하면 Stop Loss가 우선 적용됩니다."
    )

    evidence.add(
        evidence_type="STRATEGY_RULE",
        source_report_type="EXECUTABLE_SPECIFICATION",
        source_report_id=None,
        source_field="entry_rules",
        source_value=entry_rules,
        source_status="AVAILABLE",
        interpretation_code="ENTRY_RULE_EXPLANATION",
    )
    evidence.add(
        evidence_type="STRATEGY_RULE",
        source_report_type="EXECUTABLE_SPECIFICATION",
        source_report_id=None,
        source_field="exit_rules/stop_loss_rule/take_profit_rule",
        source_value={"exit_rules": exit_rules, "stop_loss_rule": stop_loss, "take_profit_rule": take_profit},
        source_status="AVAILABLE",
        interpretation_code="EXIT_RULE_EXPLANATION",
    )
    evidence.add(
        evidence_type="STRATEGY_RULE",
        source_report_type="EXECUTABLE_SPECIFICATION",
        source_report_id=None,
        source_field="position_sizing_rule",
        source_value=position_sizing,
        source_status="AVAILABLE",
        interpretation_code="POSITION_SIZING_EXPLANATION",
    )

    return {
        "entry": {"rules": entry_rules, "sentences": entry_sentences, "combination_note": entry_combination},
        "exit": {"rules": exit_rules, "sentences": exit_sentences, "combination_note": exit_combination},
        "stop_loss": {"rule": stop_loss, "sentence": stop_loss_sentence},
        "take_profit": {"rule": take_profit, "sentence": take_profit_sentence},
        "position_sizing": {"rule": position_sizing, "sentence": position_sizing_sentence},
        "exit_priority": exit_priority,
        "exit_priority_note": exit_priority_note,
    }


# ---------------------------------------------------------------------------
# Backtest / Performance Evidence.
# ---------------------------------------------------------------------------


def _build_backtest_evidence(
    session: Session, backtest_run_id: int | None, evidence: _EvidenceCollector
) -> tuple[dict[str, Any], _CategoryOutcome, _CategoryOutcome]:
    """§ STEP12-15 인수 조건(STEP12-14 필수 인수 보완 2) — Explainability는
    `analyze_backtest_run()`을 재실행하지 않는다(재계산·재저장 금지, 이
    요청으로 인해 검증 결과가 바뀌면 안 됨). Backtest Evidence는
    `BacktestRunEntity` 자체 컬럼(실행 시점에 이미 저장된 사실)만 읽고,
    Performance Analytics Evidence는 STEP12-8이 과거에 이미 계산해
    `parameters.performance_analytics`에 저장해 둔 값이 있으면 그것만
    읽는다(없으면 계산하지 않고 NOT_AVAILABLE)."""
    backtest_weight = BASE_EVIDENCE_WEIGHTS["backtest"]
    performance_weight = BASE_EVIDENCE_WEIGHTS["performance_analytics"]

    if backtest_run_id is None:
        return (
            {"status": "NOT_AVAILABLE", "performance_status": "NOT_AVAILABLE"},
            _CategoryOutcome("backtest", "NOT_AVAILABLE", backtest_weight, ZERO, "MISSING", "BACKTEST_NOT_AVAILABLE"),
            _CategoryOutcome("performance_analytics", "NOT_AVAILABLE", performance_weight, ZERO, "MISSING", "PERFORMANCE_ANALYTICS_NOT_AVAILABLE"),
        )

    repository = BacktestRepository(session)
    run = repository.get_run(backtest_run_id)
    if run is None:
        return (
            {"status": "NOT_AVAILABLE", "performance_status": "NOT_AVAILABLE"},
            _CategoryOutcome("backtest", "NOT_AVAILABLE", backtest_weight, ZERO, "MISSING", "BACKTEST_NOT_AVAILABLE"),
            _CategoryOutcome("performance_analytics", "NOT_AVAILABLE", performance_weight, ZERO, "MISSING", "PERFORMANCE_ANALYTICS_NOT_AVAILABLE"),
        )

    if run.status_code != "SUCCESS":
        payload = {
            "status": "INCOMPLETE", "performance_status": "NOT_AVAILABLE",
            "backtest_run_id": backtest_run_id, "status_code": run.status_code,
        }
        evidence.add(
            evidence_type="BACKTEST_METRIC", source_report_type="BACKTEST_RUN", source_report_id=backtest_run_id,
            source_field="status_code", source_value=run.status_code, source_status="INCOMPLETE",
        )
        return (
            payload,
            _CategoryOutcome("backtest", "NOT_AVAILABLE", backtest_weight, ZERO, "BLOCKING", "BACKTEST_INCOMPLETE"),
            _CategoryOutcome("performance_analytics", "NOT_AVAILABLE", performance_weight, ZERO, "MISSING", "PERFORMANCE_ANALYTICS_NOT_AVAILABLE"),
        )

    backtest_fields = [
        ("start_date", run.start_date.isoformat()),
        ("end_date", run.end_date.isoformat()),
        ("initial_capital", run.initial_capital),
        ("final_equity", run.final_equity),
        ("total_return_rate", run.total_return_rate),
        ("maximum_drawdown_rate", run.maximum_drawdown_rate),
        ("trade_count", run.trade_count),
        ("win_count", run.win_count),
        ("loss_count", run.loss_count),
        ("win_rate", run.win_rate),
    ]
    for name, value in backtest_fields:
        evidence.add(
            evidence_type="BACKTEST_METRIC", source_report_type="BACKTEST_RUN", source_report_id=backtest_run_id,
            source_field=name, source_value=value, source_status="AVAILABLE",
        )

    backtest_payload = {
        "status": "AVAILABLE",
        "backtest_run_id": backtest_run_id,
        "period_start_date": run.start_date.isoformat(),
        "period_end_date": run.end_date.isoformat(),
        "initial_capital": run.initial_capital,
        "final_equity": run.final_equity,
        "total_return_rate": run.total_return_rate,
        "maximum_drawdown_rate": run.maximum_drawdown_rate,
        "trade_count": run.trade_count,
        "win_count": run.win_count,
        "loss_count": run.loss_count,
        "win_rate": run.win_rate,
        "executable_hash": (run.parameters or {}).get("executable_hash"),
    }
    backtest_outcome = _CategoryOutcome(
        "backtest", "AVAILABLE", backtest_weight, backtest_weight, "POSITIVE", "BACKTEST_AVAILABLE"
    )

    # Performance Analytics — 이미 저장된 값만 읽는다(재계산 없음). 별도
    # `performance_status` 필드를 둬 저장된 Report만으로도(재조회 없이)
    # Performance 가용 여부를 판별할 수 있게 한다(§ STEP12-15 Decision
    # Package의 필수 Evidence 판정이 이 값을 그대로 재사용).
    stored_analytics = (run.parameters or {}).get("performance_analytics")
    if not stored_analytics:
        backtest_payload["performance_status"] = "NOT_AVAILABLE"
        return (
            _to_jsonable(backtest_payload),
            backtest_outcome,
            _CategoryOutcome("performance_analytics", "NOT_AVAILABLE", performance_weight, ZERO, "MISSING", "PERFORMANCE_ANALYTICS_NOT_AVAILABLE"),
        )

    kpi = stored_analytics.get("kpi") or {}
    score = stored_analytics.get("score") or {}
    performance_fields = [
        ("cagr", kpi.get("cagr")),
        ("sharpe_ratio", kpi.get("sharpe_ratio")),
        ("sortino_ratio", kpi.get("sortino_ratio")),
        ("profit_factor", kpi.get("profit_factor")),
        ("ulcer_index", kpi.get("ulcer_index")),
        ("strategy_score", score.get("score")),
        ("strategy_grade", score.get("grade")),
    ]
    for name, value in performance_fields:
        evidence.add(
            evidence_type="BACKTEST_METRIC", source_report_type="PERFORMANCE_ANALYTICS(backtest_run.parameters)",
            source_report_id=backtest_run_id, source_field=name, source_value=value, source_status="AVAILABLE",
        )

    performance_payload = {
        "status": "AVAILABLE",
        "cagr": kpi.get("cagr"),
        "sharpe_ratio": kpi.get("sharpe_ratio"),
        "sortino_ratio": kpi.get("sortino_ratio"),
        "profit_factor": kpi.get("profit_factor"),
        "ulcer_index": kpi.get("ulcer_index"),
        "strategy_score": score.get("score"),
        "strategy_grade": score.get("grade"),
    }
    backtest_payload.update(performance_payload)
    backtest_payload["status"] = "AVAILABLE"
    backtest_payload["performance_status"] = "AVAILABLE"
    return (
        _to_jsonable(backtest_payload),
        backtest_outcome,
        _CategoryOutcome("performance_analytics", "AVAILABLE", performance_weight, performance_weight, None, None),
    )


# ---------------------------------------------------------------------------
# Walk-Forward Evidence.
# ---------------------------------------------------------------------------


def _build_walk_forward_evidence(
    session: Session, walk_forward_run_id: int | None, evidence: _EvidenceCollector
) -> tuple[dict[str, Any], _CategoryOutcome]:
    weight = BASE_EVIDENCE_WEIGHTS["walk_forward"]
    if walk_forward_run_id is None:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("walk_forward", "NOT_AVAILABLE", weight, ZERO, "MISSING", "WALK_FORWARD_NOT_AVAILABLE"),
        )

    from stock_platform.ai.strategy_draft_approval.walk_forward import get_overfitting_report

    try:
        report = get_overfitting_report(session, walk_forward_run_id)
    except WalkForwardError:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("walk_forward", "NOT_AVAILABLE", weight, ZERO, "MISSING", "WALK_FORWARD_NOT_AVAILABLE"),
        )

    stability = report.get("stability") or {}
    overfitting_grade = report.get("overfitting_grade")
    fields = [
        ("stability_score", stability.get("stability_score")),
        ("consistency_score", report.get("consistency_score")),
        ("success_ratio", report.get("success_ratio")),
        ("overfitting_score", report.get("overfitting_score")),
        ("overfitting_grade", overfitting_grade),
        ("forward_performance", report.get("forward_performance")),
    ]
    for name, value in fields:
        evidence.add(
            evidence_type="WALK_FORWARD_METRIC", source_report_type="WALK_FORWARD_RUN",
            source_report_id=walk_forward_run_id, source_field=name, source_value=value, source_status="AVAILABLE",
        )

    window_failures = [
        {"window_no": w["window_no"], "window_overfitting_score": w.get("window_overfitting_score")}
        for w in report.get("per_window", [])
        if w.get("in_sample") is None or w.get("out_of_sample") is None
    ]

    bucket = {"HIGH": "BLOCKING", "MEDIUM": "WARNING", "LOW": "POSITIVE"}.get(overfitting_grade, "MISSING")
    code = f"WALK_FORWARD_OVERFITTING_{overfitting_grade}" if overfitting_grade else "WALK_FORWARD_UNKNOWN"

    payload = {
        "status": "AVAILABLE",
        "walk_forward_run_id": walk_forward_run_id,
        "stability_score": stability.get("stability_score"),
        "consistency_score": report.get("consistency_score"),
        "success_ratio": report.get("success_ratio"),
        "overfitting_score": report.get("overfitting_score"),
        "overfitting_grade": overfitting_grade,
        "forward_performance": report.get("forward_performance"),
        "window_failures": window_failures,
    }
    return (
        _to_jsonable(payload),
        _CategoryOutcome("walk_forward", "AVAILABLE", weight, weight, bucket, code),
    )


# ---------------------------------------------------------------------------
# Quality Gate Evidence.
# ---------------------------------------------------------------------------


def _build_quality_gate_evidence(
    session: Session, quality_gate_report_id: int | None, strategy_definition_id: int, evidence: _EvidenceCollector
) -> tuple[dict[str, Any], _CategoryOutcome]:
    weight = BASE_EVIDENCE_WEIGHTS["quality_gate"]
    if quality_gate_report_id is None:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("quality_gate", "NOT_AVAILABLE", weight, ZERO, "MISSING", "QUALITY_GATE_NOT_AVAILABLE"),
        )

    from stock_platform.ai.strategy_draft_approval.quality_gate import get_quality_report

    try:
        report = get_quality_report(session, quality_gate_report_id, strategy_definition_id=strategy_definition_id)
    except QualityGateError:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("quality_gate", "NOT_AVAILABLE", weight, ZERO, "MISSING", "QUALITY_GATE_NOT_AVAILABLE"),
        )

    rule_sentences = []
    for rule in report["rules"]:
        label = _QUALITY_GATE_RULE_LABEL.get(rule["rule_name"], rule["rule_name"])
        threshold = rule["threshold"]
        threshold_desc = "/".join(f"{k}={v}" for k, v in threshold.items())
        sentence = f"{label}은 기준({threshold_desc}) 대비 실제 {rule['actual_value']}로 {rule['status']}입니다."
        rule_sentences.append({"rule_name": rule["rule_name"], "sentence": sentence, "status": rule["status"]})
        evidence.add(
            evidence_type="QUALITY_GATE_RULE", source_report_type="QUALITY_GATE_REPORT",
            source_report_id=quality_gate_report_id, source_field=rule["rule_name"],
            source_value=rule["actual_value"], source_status=rule["status"], threshold=threshold,
        )

    recommendation = report["recommendation"]
    bucket = {"APPROVE": "POSITIVE", "MANUAL_REVIEW": "WARNING", "REJECT": "BLOCKING"}[recommendation]
    code = f"QUALITY_GATE_{recommendation}"

    payload = {
        "status": "AVAILABLE",
        "quality_gate_report_id": quality_gate_report_id,
        "recommendation": recommendation,
        "risk_grade": report["risk_grade"],
        "risk_grade_reason": report["risk_grade_reason"],
        "rules": rule_sentences,
    }
    return (_to_jsonable(payload), _CategoryOutcome("quality_gate", "AVAILABLE", weight, weight, bucket, code))


# ---------------------------------------------------------------------------
# Parameter Sensitivity Evidence.
# ---------------------------------------------------------------------------


def _build_sensitivity_evidence(
    session: Session, report_id: int | None, strategy_definition_id: int, evidence: _EvidenceCollector
) -> tuple[dict[str, Any], _CategoryOutcome]:
    weight = BASE_EVIDENCE_WEIGHTS["parameter_sensitivity"]
    if report_id is None:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("parameter_sensitivity", "NOT_AVAILABLE", weight, ZERO, "MISSING", "SENSITIVITY_NOT_AVAILABLE"),
        )

    from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
        get_parameter_sensitivity_report,
    )

    try:
        report = get_parameter_sensitivity_report(session, report_id, strategy_definition_id=strategy_definition_id)
    except ParameterSensitivityError:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("parameter_sensitivity", "NOT_AVAILABLE", weight, ZERO, "MISSING", "SENSITIVITY_NOT_AVAILABLE"),
        )

    status = report["sensitivity_status"]
    stable_range = report["stable_range"] or {}
    cliffs = report["performance_cliffs"] or []

    if status == "INSUFFICIENT_DATA":
        interpretation = "유효 Variation 수가 부족하거나 Robustness Score를 계산할 수 없어 민감도를 판단할 수 없습니다."
    elif stable_range.get("includes_base") and not cliffs:
        interpretation = "기준값은 안정 구간에 포함되며 뚜렷한 성과 절벽은 발견되지 않았습니다."
    elif stable_range.get("includes_base") and cliffs:
        worst = max(cliffs, key=lambda c: {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[c["severity"]])
        interpretation = f"기준값은 안정 구간에 포함되지만 인접 값에서 {worst['severity']} 성과 절벽이 존재합니다."
    else:
        interpretation = "기준값이 안정 구간에 포함되지 않아 파라미터 변화에 취약합니다(과의존 가능성)."

    for name, value in [
        ("robustness_score", report["robustness_score"]),
        ("sensitivity_status", status),
        ("stable_range", stable_range),
        ("performance_cliffs", cliffs),
    ]:
        evidence.add(
            evidence_type="SENSITIVITY_METRIC", source_report_type="PARAMETER_SENSITIVITY_REPORT",
            source_report_id=report_id, source_field=name, source_value=value, source_status="AVAILABLE",
            interpretation_code="SENSITIVITY_INTERPRETATION" if name == "sensitivity_status" else None,
        )

    bucket = {"ROBUST": "POSITIVE", "ACCEPTABLE": "WARNING", "FRAGILE": "BLOCKING", "INSUFFICIENT_DATA": "MISSING"}.get(status, "MISSING")
    code = f"SENSITIVITY_{status}"

    payload = {
        "status": "AVAILABLE",
        "parameter_sensitivity_report_id": report_id,
        "robustness_score": report["robustness_score"],
        "sensitivity_status": status,
        "stable_range": stable_range,
        "performance_cliffs": cliffs,
        "parameter_specification": report["parameter_specification"],
        "interpretation": interpretation,
    }
    return (_to_jsonable(payload), _CategoryOutcome("parameter_sensitivity", "AVAILABLE", weight, weight, bucket, code))


# ---------------------------------------------------------------------------
# Monte Carlo Evidence.
# ---------------------------------------------------------------------------


def _build_monte_carlo_evidence(
    session: Session, report_id: int | None, strategy_definition_id: int, evidence: _EvidenceCollector
) -> tuple[dict[str, Any], _CategoryOutcome]:
    weight = BASE_EVIDENCE_WEIGHTS["monte_carlo"]
    if report_id is None:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("monte_carlo", "NOT_AVAILABLE", weight, ZERO, "MISSING", "MONTE_CARLO_NOT_AVAILABLE"),
        )

    from stock_platform.ai.strategy_draft_approval.monte_carlo import get_monte_carlo_report

    try:
        report = get_monte_carlo_report(session, report_id, strategy_definition_id=strategy_definition_id)
    except MonteCarloError:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("monte_carlo", "NOT_AVAILABLE", weight, ZERO, "MISSING", "MONTE_CARLO_NOT_AVAILABLE"),
        )

    status = report["monte_carlo_status"]
    percentiles = report["percentile_payload"] or {}
    total_return_pctl = percentiles.get("total_return") or {}
    drawdown_pctl = percentiles.get("maximum_drawdown_percent") or {}
    ci = report["confidence_interval_payload"] or {}
    representatives = report["representative_payload"] or {}

    interpretation = (
        f"{report['simulation_count']}회 {report['simulation_method']} Simulation에서 "
        f"Risk of Ruin은 {report['risk_of_ruin_percent']}%였습니다."
    )

    for name, value in [
        ("simulation_method", report["simulation_method"]),
        ("simulation_count", report["simulation_count"]),
        ("random_seed", report["random_seed"]),
        ("risk_of_ruin_percent", report["risk_of_ruin_percent"]),
        ("p05_total_return", total_return_pctl.get("P05")),
        ("p50_total_return", total_return_pctl.get("P50")),
        ("p95_total_return", total_return_pctl.get("P95")),
        ("p50_maximum_drawdown_percent", drawdown_pctl.get("P50")),
        ("p95_maximum_drawdown_percent", drawdown_pctl.get("P95")),
        ("confidence_interval", ci),
        ("monte_carlo_status", status),
        ("score_policy", report["simulation_method"]),
    ]:
        evidence.add(
            evidence_type="MONTE_CARLO_METRIC", source_report_type="MONTE_CARLO_REPORT",
            source_report_id=report_id, source_field=name, source_value=value, source_status="AVAILABLE",
        )

    bucket = {"RESILIENT": "POSITIVE", "ACCEPTABLE": "POSITIVE", "FRAGILE": "WARNING", "HIGH_RISK": "BLOCKING", "INSUFFICIENT_DATA": "MISSING"}.get(status, "MISSING")
    code = f"MONTE_CARLO_{status}"

    payload = {
        "status": "AVAILABLE",
        "monte_carlo_report_id": report_id,
        "simulation_method": report["simulation_method"],
        "simulation_count": report["simulation_count"],
        "random_seed": report["random_seed"],
        "risk_of_ruin_percent": report["risk_of_ruin_percent"],
        "percentiles": {"total_return": total_return_pctl, "maximum_drawdown_percent": drawdown_pctl},
        "confidence_interval": ci,
        "representatives": representatives,
        "monte_carlo_status": status,
        "score_policy": report["simulation_method"],
        "interpretation": interpretation,
    }
    return (_to_jsonable(payload), _CategoryOutcome("monte_carlo", "AVAILABLE", weight, weight, bucket, code))


# ---------------------------------------------------------------------------
# Portfolio Evidence(선택 항목 — 선택된 경우에만 완전성 분모에 포함).
# ---------------------------------------------------------------------------


def _build_portfolio_evidence(
    session: Session, report_id: int | None, strategy_definition_id: int, evidence: _EvidenceCollector
) -> tuple[dict[str, Any], _CategoryOutcome]:
    if report_id is None:
        return (
            {"status": "NOT_REQUESTED"},
            _CategoryOutcome("portfolio", "NOT_REQUESTED", ZERO, ZERO, None, None),
        )

    from stock_platform.ai.strategy_draft_approval.portfolio_validation import (
        get_portfolio_validation_report,
    )

    try:
        report = get_portfolio_validation_report(session, report_id)
    except PortfolioValidationError:
        return (
            {"status": "NOT_AVAILABLE"},
            _CategoryOutcome("portfolio", "NOT_AVAILABLE", PORTFOLIO_EVIDENCE_WEIGHT, ZERO, "MISSING", "PORTFOLIO_NOT_AVAILABLE"),
        )

    included_ids = [int(s) for s in (report["strategy_definition_ids"] or [])]
    if strategy_definition_id not in included_ids:
        return (
            {"status": "INCOMPATIBLE", "reason": "선택된 Portfolio Validation Report에 이 Strategy가 포함되어 있지 않습니다."},
            _CategoryOutcome("portfolio", "INCOMPATIBLE", PORTFOLIO_EVIDENCE_WEIGHT, ZERO, "MISSING", "PORTFOLIO_INCOMPATIBLE"),
        )

    status = report["validation_status"]
    duplicate_exposures = report["duplicate_exposure_payload"] or []
    high_exposures = [e for e in duplicate_exposures if e["severity"] == "HIGH"]

    for name, value in [
        ("validation_status", status),
        ("robustness_score", report["robustness_score"]),
        ("weights", report["weights_payload"]),
        ("correlation", report["correlation_payload"]),
        ("concentration", report["concentration_payload"]),
        ("risk_contribution", report["risk_contribution_payload"]),
        ("diversification", report["diversification_payload"]),
        ("duplicate_exposure", duplicate_exposures),
        ("methodology_note", report["methodology_note"]),
    ]:
        evidence.add(
            evidence_type="PORTFOLIO_METRIC", source_report_type="PORTFOLIO_VALIDATION_REPORT",
            source_report_id=report_id, source_field=name, source_value=value, source_status="AVAILABLE",
        )

    bucket = {"DIVERSIFIED": "POSITIVE", "ACCEPTABLE": "POSITIVE", "CONCENTRATED": "WARNING", "HIGHLY_CORRELATED": "WARNING", "HIGH_RISK": "BLOCKING", "INSUFFICIENT_DATA": "MISSING"}.get(status, "MISSING")
    if high_exposures and bucket != "BLOCKING":
        bucket = "WARNING"
    code = f"PORTFOLIO_{status}"

    payload = {
        "status": "AVAILABLE",
        "portfolio_validation_report_id": report_id,
        "validation_status": status,
        "robustness_score": report["robustness_score"],
        "weights": report["weights_payload"],
        "correlation": report["correlation_payload"],
        "concentration": report["concentration_payload"],
        "risk_contribution": report["risk_contribution_payload"],
        "diversification": report["diversification_payload"],
        "duplicate_exposure": duplicate_exposures,
        "high_duplicate_exposure_count": len(high_exposures),
        "methodology_note": report["methodology_note"],
    }
    return (
        _to_jsonable(payload),
        _CategoryOutcome("portfolio", "AVAILABLE", PORTFOLIO_EVIDENCE_WEIGHT, PORTFOLIO_EVIDENCE_WEIGHT, bucket, code),
    )


# ---------------------------------------------------------------------------
# Provenance Check.
# ---------------------------------------------------------------------------


def _build_provenance_evidence(
    session: Session,
    strategy_definition_id: int,
    *,
    current_executable_hash: str | None,
    selected_executable_hashes: dict[str, str | None],
    evidence: _EvidenceCollector,
) -> tuple[dict[str, Any], _CategoryOutcome]:
    weight = BASE_EVIDENCE_WEIGHTS["provenance"]
    # derived clone은 source_draft_id 없이 source equivalence로 provenance를 본다.
    provenance = resolve_strategy_provenance(session, strategy_definition_id)

    mismatches = [
        {"source": source, "stored_executable_hash": h, "current_executable_hash": current_executable_hash}
        for source, h in selected_executable_hashes.items()
        if h is not None and current_executable_hash is not None and h != current_executable_hash
    ]

    evidence.add(
        evidence_type="PROVENANCE_CHECK", source_report_type="PROVENANCE_CHAIN", source_report_id=None,
        source_field="chain", source_value=provenance["chain"], source_status="AVAILABLE" if provenance["valid"] else "PROVENANCE_MISMATCH",
    )
    for m in mismatches:
        evidence.add(
            evidence_type="PROVENANCE_CHECK", source_report_type=m["source"], source_report_id=None,
            source_field="executable_hash", source_value=m["stored_executable_hash"],
            source_status="PROVENANCE_MISMATCH", threshold=current_executable_hash,
        )

    all_match = provenance["valid"] and not mismatches
    payload = {
        "status": "AVAILABLE" if provenance["valid"] else "PROVENANCE_MISMATCH",
        "chain": provenance["chain"],
        "chain_valid": provenance["valid"],
        "chain_failures": provenance["failures"],
        "executable_hash_mismatches": mismatches,
        "all_provenance_matches": all_match,
    }
    if not provenance["valid"]:
        outcome = _CategoryOutcome("provenance", "PROVENANCE_MISMATCH", weight, ZERO, "BLOCKING", "PROVENANCE_MISMATCH")
    elif mismatches:
        outcome = _CategoryOutcome("provenance", "PROVENANCE_MISMATCH", weight, ZERO, "BLOCKING", "PROVENANCE_MISMATCH")
    else:
        outcome = _CategoryOutcome("provenance", "AVAILABLE", weight, weight, "POSITIVE", "PROVENANCE_MATCH")
    return _to_jsonable(payload), outcome


# ---------------------------------------------------------------------------
# Completeness Score / Decision Checklist / Decision Summary.
# ---------------------------------------------------------------------------


def _completeness_status(score: Decimal) -> str:
    for threshold, status_name in _COMPLETENESS_THRESHOLDS:
        if score >= threshold:
            return status_name
    return "INSUFFICIENT"


def _compute_completeness(outcomes: list[_CategoryOutcome]) -> dict[str, Any]:
    applicable = [o for o in outcomes if o.status != "NOT_REQUESTED"]
    total_weight = sum((o.weight for o in applicable), ZERO)
    achieved_weight = sum((o.achieved for o in applicable), ZERO)
    score = (achieved_weight / total_weight * HUNDRED).quantize(Decimal("0.01")) if total_weight > ZERO else ZERO
    return {
        "score": score,
        "status": _completeness_status(score),
        "breakdown": [
            {"category": o.name, "status": o.status, "weight": o.weight, "achieved": o.achieved}
            for o in outcomes
        ],
    }


def _build_decision_checklist(
    *,
    quality_gate_payload: dict[str, Any],
    sensitivity_payload: dict[str, Any],
    monte_carlo_payload: dict[str, Any],
    walk_forward_payload: dict[str, Any],
    portfolio_payload: dict[str, Any],
    provenance_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    def _item(code: str, question: str, answer: bool | None, basis: str) -> dict[str, Any]:
        return {"code": code, "question": question, "answer": answer, "basis": basis}

    qg_rules = quality_gate_payload.get("rules") or []
    qg_has_fail = any(r["status"] == "FAIL" for r in qg_rules) if quality_gate_payload.get("status") == "AVAILABLE" else None

    sensitivity_status = sensitivity_payload.get("status")
    if sensitivity_status == "AVAILABLE":
        stable_range = sensitivity_payload.get("stable_range") or {}
        base_outside = not bool(stable_range.get("includes_base"))
    else:
        base_outside = None

    mc_risk = monte_carlo_payload.get("risk_of_ruin_percent")
    mc_exceeds = (
        Decimal(str(mc_risk)) > MONTE_CARLO_RISK_OF_RUIN_THRESHOLD_PERCENT
        if monte_carlo_payload.get("status") == "AVAILABLE" and mc_risk is not None
        else None
    )

    wf_grade = walk_forward_payload.get("overfitting_grade")
    wf_high = (wf_grade == "HIGH") if walk_forward_payload.get("status") == "AVAILABLE" else None

    portfolio_high = (
        portfolio_payload.get("high_duplicate_exposure_count", 0) > 0
        if portfolio_payload.get("status") == "AVAILABLE"
        else None
    )

    provenance_ok = provenance_payload.get("all_provenance_matches")

    return [
        _item(
            "QUALITY_GATE_FAIL_EXISTS", "Quality Gate FAIL이 존재하는가", qg_has_fail,
            "Quality Gate Report의 Rule 평가 결과 중 FAIL 존재 여부" if qg_has_fail is not None else "Quality Gate 근거 없음",
        ),
        _item(
            "SENSITIVITY_BASE_OUTSIDE_STABLE_RANGE", "Sensitivity Stable Range에 Base가 포함되지 않는가", base_outside,
            "Parameter Sensitivity Report의 stable_range.includes_base" if base_outside is not None else "Sensitivity 근거 없음",
        ),
        _item(
            "MONTE_CARLO_RISK_OF_RUIN_HIGH",
            f"Monte Carlo Risk of Ruin이 허용 범위({MONTE_CARLO_RISK_OF_RUIN_THRESHOLD_PERCENT}%)를 초과하는가",
            mc_exceeds,
            "Monte Carlo Report의 risk_of_ruin_percent" if mc_exceeds is not None else "Monte Carlo 근거 없음",
        ),
        _item(
            "WALK_FORWARD_OVERFITTING_HIGH", "Walk-Forward Overfitting Level이 HIGH인가", wf_high,
            "Walk-Forward Report의 overfitting_grade" if wf_high is not None else "Walk-Forward 근거 없음",
        ),
        _item(
            "PORTFOLIO_DUPLICATE_EXPOSURE_HIGH", "Portfolio Duplicate Exposure HIGH가 존재하는가", portfolio_high,
            "Portfolio Validation Report의 duplicate_exposure severity" if portfolio_high is not None else "Portfolio 근거 없음(선택 안 됨)",
        ),
        _item(
            "PROVENANCE_ALL_MATCH", "Provenance가 모두 일치하는가", provenance_ok,
            "Provenance Chain 검증 + 선택된 각 Report의 executable_hash 비교",
        ),
    ]


def _build_decision_summary(outcomes: list[_CategoryOutcome], *, completeness_status: str) -> dict[str, Any]:
    """§ STEP12-15 인수 조건(STEP12-14 필수 인수 보완 5) — 이전에는
    `human_review_required`가 Blocking에만 반응해, Warning/Missing만
    있고 Completeness가 낮은 Report도 "검토 불필요"로 보일 수 있었다.
    Blocking/Warning/Missing 중 하나라도 있거나 Completeness가
    COMPLETE 미만이면 사람이 검토해야 한다(자동 승인 판단과는 무관 —
    이 필드는 "검토가 필요한가"만 나타낸다)."""
    positive = [o for o in outcomes if o.summary_bucket == "POSITIVE"]
    warning = [o for o in outcomes if o.summary_bucket == "WARNING"]
    blocking = [o for o in outcomes if o.summary_bucket == "BLOCKING"]
    missing = [o for o in outcomes if o.summary_bucket == "MISSING"]
    human_review_required = (
        len(blocking) > 0 or len(warning) > 0 or len(missing) > 0 or completeness_status != "COMPLETE"
    )
    return {
        "positive_count": len(positive),
        "warning_count": len(warning),
        "blocking_count": len(blocking),
        "missing_count": len(missing),
        "human_review_required": human_review_required,
        "summary_codes": [o.summary_code for o in outcomes if o.summary_code is not None],
    }


# ---------------------------------------------------------------------------
# Provenance / Input Hash.
# ---------------------------------------------------------------------------


def compute_report_input_hash(
    *,
    strategy_definition_id: int,
    definition_version: int | None,
    executable_hash: str | None,
    backtest_run_id: int | None,
    walk_forward_run_id: int | None,
    quality_gate_report_id: int | None,
    parameter_sensitivity_report_id: int | None,
    monte_carlo_report_id: int | None,
    portfolio_validation_report_id: int | None,
    explanation_mode: str,
    explanation_language: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "definition_version": definition_version,
        "executable_hash": executable_hash,
        "backtest_run_id": backtest_run_id,
        "walk_forward_run_id": walk_forward_run_id,
        "quality_gate_report_id": quality_gate_report_id,
        "parameter_sensitivity_report_id": parameter_sensitivity_report_id,
        "monte_carlo_report_id": monte_carlo_report_id,
        "portfolio_validation_report_id": portfolio_validation_report_id,
        "explanation_mode": explanation_mode,
        "explanation_language": explanation_language,
        "template_version": TEMPLATE_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
    }
    return _hash(_canonical_json(canonical))


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def run_generate_explainability(
    session: Session,
    strategy_definition_id: int,
    *,
    backtest_run_id: int | None = None,
    walk_forward_run_id: int | None = None,
    quality_gate_report_id: int | None = None,
    parameter_sensitivity_report_id: int | None = None,
    monte_carlo_report_id: int | None = None,
    portfolio_validation_report_id: int | None = None,
    explanation_language: str = DEFAULT_LANGUAGE,
    explanation_mode: str = DEFAULT_EXPLANATION_MODE,
    use_latest_when_missing: bool = True,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """§ STEP12-15 인수 조건(STEP12-14 필수 인수 보완 3) — `performance_run_id`
    필드는 제거했다(조사 결과, `trading.strategy_performance_run`에
    `run_type=BACKTEST`가 이론상 존재하지만 STEP12-7 `run_definition_backtest()`
    는 그 테이블에 전혀 쓰지 않는 완전히 다른 레거시 경로 전용이라, 이
    STEP12-x 계열에서 "Backtest의 Performance"를 가리키는 실제 PK는
    `backtest_run_id` 하나뿐이다 — 이름과 실제 의미가 다른 필드를
    alias로 유지하지 않고 Option B(필드 제거)를 택함)."""
    if explanation_language not in SUPPORTED_LANGUAGES:
        raise ExplainabilityError("UNSUPPORTED_LANGUAGE", f"지원하지 않는 explanation_language: {explanation_language}")
    if explanation_mode not in SUPPORTED_EXPLANATION_MODES:
        raise ExplainabilityError(
            "UNSUPPORTED_EXPLANATION_MODE",
            f"이번 STEP에서는 RULE_BASED만 지원합니다(요청: {explanation_mode}).",
        )

    try:
        _require_definition(session, strategy_definition_id)
    except ReadinessError as exc:
        raise ExplainabilityError(exc.code, exc.message) from exc

    # 다른 Strategy의 Report ID를 끼워 넣는 행위 차단 — 명시된 ID는 전부
    # 소유 관계를 검증한다(STEP12-13과 동일한 원칙).
    def _resolve(explicit: int | None, latest_fn) -> int | None:
        if explicit is not None:
            return explicit
        if use_latest_when_missing:
            return latest_fn(session, strategy_definition_id)
        return None

    resolved_backtest_run_id = _resolve(backtest_run_id, _latest_backtest_run_id)
    resolved_walk_forward_run_id = _resolve(walk_forward_run_id, _latest_walk_forward_run_id)
    resolved_quality_gate_report_id = _resolve(quality_gate_report_id, _latest_quality_gate_report_id)
    resolved_sensitivity_report_id = _resolve(parameter_sensitivity_report_id, _latest_parameter_sensitivity_report_id)
    resolved_monte_carlo_report_id = _resolve(monte_carlo_report_id, _latest_monte_carlo_report_id)
    resolved_portfolio_report_id = _resolve(portfolio_validation_report_id, _latest_portfolio_validation_report_id)

    # 명시적으로 준 ID의 소유 관계 검증(하드 블록) — 최신 자동 선택 결과는
    # 이미 strategy_definition_id로 필터링되어 있어 재검증이 불필요하다.
    if backtest_run_id is not None:
        repo = BacktestRepository(session)
        run = repo.get_run(backtest_run_id)
        if run is None:
            raise ExplainabilityError("BACKTEST_RUN_NOT_FOUND", f"Backtest run not found: {backtest_run_id}")
        if run.strategy_definition_id != strategy_definition_id:
            raise ExplainabilityError("OWNERSHIP_MISMATCH", f"Backtest Run #{backtest_run_id}은 이 Strategy의 결과가 아닙니다.")
    if walk_forward_run_id is not None:
        run = session.get(StrategyPerformanceRunEntity, walk_forward_run_id)
        if run is None or run.strategy_id != strategy_definition_id:
            raise ExplainabilityError("OWNERSHIP_MISMATCH", f"Walk-Forward Run #{walk_forward_run_id}은 이 Strategy의 결과가 아닙니다.")
    if quality_gate_report_id is not None:
        report = session.get(StrategyQualityGateReportEntity, quality_gate_report_id)
        if report is None or report.strategy_id != strategy_definition_id:
            raise ExplainabilityError("OWNERSHIP_MISMATCH", f"Quality Gate Report #{quality_gate_report_id}은 이 Strategy의 결과가 아닙니다.")
    if parameter_sensitivity_report_id is not None:
        report = session.get(ParameterSensitivityReportEntity, parameter_sensitivity_report_id)
        if report is None or report.strategy_id != strategy_definition_id:
            raise ExplainabilityError("OWNERSHIP_MISMATCH", f"Parameter Sensitivity Report #{parameter_sensitivity_report_id}은 이 Strategy의 결과가 아닙니다.")
    if monte_carlo_report_id is not None:
        report = session.get(MonteCarloSimulationReportEntity, monte_carlo_report_id)
        if report is None or report.strategy_id != strategy_definition_id:
            raise ExplainabilityError("OWNERSHIP_MISMATCH", f"Monte Carlo Report #{monte_carlo_report_id}은 이 Strategy의 결과가 아닙니다.")
    if portfolio_validation_report_id is not None:
        report = session.get(PortfolioValidationReportEntity, portfolio_validation_report_id)
        if report is None:
            raise ExplainabilityError("NOT_FOUND", f"Portfolio Validation report not found: {portfolio_validation_report_id}")
        included_ids = [int(s) for s in (report.strategy_definition_ids or [])]
        if strategy_definition_id not in included_ids:
            raise ExplainabilityError(
                "OWNERSHIP_MISMATCH", f"Portfolio Validation Report #{portfolio_validation_report_id}에 이 Strategy가 포함되어 있지 않습니다.",
            )

    evidence = _EvidenceCollector()

    overview = _build_strategy_overview(session, strategy_definition_id, evidence)

    try:
        specification = compile_specification(session, strategy_definition_id)
    except BacktestSpecificationError as exc:
        raise ExplainabilityError(exc.code, exc.message) from exc

    current_executable_hash = specification.get("executable_hash")
    overview["executable_hash"] = current_executable_hash

    if specification["compilable"]:
        rule_explanation = _build_rule_explanation(specification, evidence)
        spec_outcome = _CategoryOutcome(
            "strategy_specification", "AVAILABLE", BASE_EVIDENCE_WEIGHTS["strategy_specification"],
            BASE_EVIDENCE_WEIGHTS["strategy_specification"], "POSITIVE", "STRATEGY_SPECIFICATION_COMPILABLE",
        )
    else:
        rule_explanation = {"status": "NOT_AVAILABLE", "errors": specification["errors"]}
        spec_outcome = _CategoryOutcome(
            "strategy_specification", "NOT_AVAILABLE", BASE_EVIDENCE_WEIGHTS["strategy_specification"],
            ZERO, "BLOCKING", "STRATEGY_SPECIFICATION_NOT_COMPILABLE",
        )

    backtest_payload, backtest_outcome, performance_outcome = _build_backtest_evidence(
        session, resolved_backtest_run_id, evidence
    )
    if resolved_backtest_run_id is not None:
        selected_run = BacktestRepository(session).get_run(resolved_backtest_run_id)
        if selected_run is not None:
            overview["symbol"] = selected_run.symbol
            overview["exchange"] = selected_run.exchange_code
    walk_forward_payload, walk_forward_outcome = _build_walk_forward_evidence(
        session, resolved_walk_forward_run_id, evidence
    )
    quality_gate_payload, quality_gate_outcome = _build_quality_gate_evidence(
        session, resolved_quality_gate_report_id, strategy_definition_id, evidence
    )
    sensitivity_payload, sensitivity_outcome = _build_sensitivity_evidence(
        session, resolved_sensitivity_report_id, strategy_definition_id, evidence
    )
    monte_carlo_payload, monte_carlo_outcome = _build_monte_carlo_evidence(
        session, resolved_monte_carlo_report_id, strategy_definition_id, evidence
    )
    portfolio_payload, portfolio_outcome = _build_portfolio_evidence(
        session, resolved_portfolio_report_id, strategy_definition_id, evidence
    )

    selected_executable_hashes = {
        "BACKTEST_RUN": backtest_payload.get("executable_hash"),
        "QUALITY_GATE_REPORT": None,
        "PARAMETER_SENSITIVITY_REPORT": None,
        "MONTE_CARLO_REPORT": None,
    }
    provenance_payload_evidence, provenance_outcome = _build_provenance_evidence(
        session, strategy_definition_id, current_executable_hash=current_executable_hash,
        selected_executable_hashes=selected_executable_hashes, evidence=evidence,
    )

    outcomes = [
        spec_outcome, backtest_outcome, performance_outcome, walk_forward_outcome,
        quality_gate_outcome, sensitivity_outcome, monte_carlo_outcome, provenance_outcome,
        portfolio_outcome,
    ]
    completeness = _compute_completeness(outcomes)

    decision_checklist = _build_decision_checklist(
        quality_gate_payload=quality_gate_payload, sensitivity_payload=sensitivity_payload,
        monte_carlo_payload=monte_carlo_payload, walk_forward_payload=walk_forward_payload,
        portfolio_payload=portfolio_payload, provenance_payload=provenance_payload_evidence,
    )
    decision_summary = _build_decision_summary(outcomes, completeness_status=completeness["status"])

    missing_evidence = [
        {"category": o.name, "status": o.status, "message": f"{o.name} 검증 결과가 없어 해당 근거는 확인되지 않았습니다."}
        for o in outcomes
        if o.status in {"NOT_AVAILABLE", "INCOMPATIBLE", "PROVENANCE_MISMATCH"}
    ]

    report_input_hash = compute_report_input_hash(
        strategy_definition_id=strategy_definition_id,
        definition_version=overview["definition_version"],
        executable_hash=current_executable_hash,
        backtest_run_id=resolved_backtest_run_id,
        walk_forward_run_id=resolved_walk_forward_run_id,
        quality_gate_report_id=resolved_quality_gate_report_id,
        parameter_sensitivity_report_id=resolved_sensitivity_report_id,
        monte_carlo_report_id=resolved_monte_carlo_report_id,
        portfolio_validation_report_id=resolved_portfolio_report_id,
        explanation_mode=explanation_mode,
        explanation_language=explanation_language,
    )

    if idempotency_key:
        existing = session.scalar(
            select(StrategyExplainabilityReportEntity).where(
                StrategyExplainabilityReportEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.report_input_hash == report_input_hash:
                return _to_report_dict(existing, idempotent_replay=True)
            raise ExplainabilityError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 요청 내용으로 사용되었습니다."
            )

    evidence_reference_payload = evidence.items

    report = StrategyExplainabilityReportEntity(
        strategy_id=strategy_definition_id,
        backtest_run_id=resolved_backtest_run_id,
        walk_forward_run_id=resolved_walk_forward_run_id,
        quality_gate_report_id=resolved_quality_gate_report_id,
        parameter_sensitivity_report_id=resolved_sensitivity_report_id,
        monte_carlo_report_id=resolved_monte_carlo_report_id,
        portfolio_validation_report_id=resolved_portfolio_report_id,
        explanation_mode=explanation_mode,
        explanation_language=explanation_language,
        strategy_overview_payload=_to_jsonable(overview),
        rule_explanation_payload=_to_jsonable(rule_explanation),
        backtest_evidence_payload=backtest_payload,
        walk_forward_evidence_payload=walk_forward_payload,
        quality_gate_evidence_payload=quality_gate_payload,
        sensitivity_evidence_payload=sensitivity_payload,
        monte_carlo_evidence_payload=monte_carlo_payload,
        portfolio_evidence_payload=portfolio_payload,
        decision_checklist_payload=_to_jsonable(decision_checklist),
        evidence_reference_payload=evidence_reference_payload,
        missing_evidence_payload=_to_jsonable(missing_evidence),
        decision_summary_payload=_to_jsonable(decision_summary),
        completeness_score=completeness["score"],
        completeness_status=completeness["status"],
        assisted_interpretation_payload=None,
        provenance_payload=provenance_payload_evidence,
        template_version=TEMPLATE_VERSION,
        algorithm_version=ALGORITHM_VERSION,
        report_input_hash=report_input_hash,
        idempotency_key=(idempotency_key or None),
        requested_by=actor,
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    return _to_report_dict(report, idempotent_replay=False)


def _to_report_dict(report: StrategyExplainabilityReportEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "explainability_report_id": int(report.explainability_report_id),
        "strategy_id": report.strategy_id,
        "backtest_run_id": report.backtest_run_id,
        "walk_forward_run_id": report.walk_forward_run_id,
        "quality_gate_report_id": report.quality_gate_report_id,
        "parameter_sensitivity_report_id": report.parameter_sensitivity_report_id,
        "monte_carlo_report_id": report.monte_carlo_report_id,
        "portfolio_validation_report_id": report.portfolio_validation_report_id,
        "explanation_mode": report.explanation_mode,
        "explanation_language": report.explanation_language,
        "strategy_overview": report.strategy_overview_payload,
        "rule_explanation": report.rule_explanation_payload,
        "backtest_evidence": report.backtest_evidence_payload,
        "walk_forward_evidence": report.walk_forward_evidence_payload,
        "quality_gate_evidence": report.quality_gate_evidence_payload,
        "sensitivity_evidence": report.sensitivity_evidence_payload,
        "monte_carlo_evidence": report.monte_carlo_evidence_payload,
        "portfolio_evidence": report.portfolio_evidence_payload,
        "decision_checklist": report.decision_checklist_payload,
        "evidence_reference": report.evidence_reference_payload,
        "missing_evidence": report.missing_evidence_payload,
        "decision_summary": report.decision_summary_payload,
        "completeness_score": report.completeness_score,
        "completeness_status": report.completeness_status,
        "assisted_interpretation": report.assisted_interpretation_payload,
        "provenance": report.provenance_payload,
        "template_version": report.template_version,
        "algorithm_version": report.algorithm_version,
        "report_input_hash": report.report_input_hash,
        "requested_by": report.requested_by,
        "created_at": report.created_at,
        "idempotent_replay": idempotent_replay,
    }


def get_explainability_report(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = session.get(StrategyExplainabilityReportEntity, report_id)
    if report is None:
        raise ExplainabilityError("NOT_FOUND", f"Explainability report not found: {report_id}")
    if strategy_definition_id is not None and report.strategy_id != strategy_definition_id:
        raise ExplainabilityError("NOT_FOUND", f"Explainability report not found: {report_id}")
    return _to_report_dict(report, idempotent_replay=False)


def get_explainability_summary(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_explainability_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "explainability_report_id": report["explainability_report_id"],
        "strategy_overview": report["strategy_overview"],
        "completeness_score": report["completeness_score"],
        "completeness_status": report["completeness_status"],
        "decision_summary": report["decision_summary"],
    }


def get_explainability_evidence(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_explainability_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "explainability_report_id": report["explainability_report_id"],
        "evidence_reference": report["evidence_reference"],
    }


def get_explainability_checklist(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_explainability_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "explainability_report_id": report["explainability_report_id"],
        "decision_checklist": report["decision_checklist"],
    }


def get_explainability_missing(
    session: Session, report_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    report = get_explainability_report(session, report_id, strategy_definition_id=strategy_definition_id)
    return {
        "explainability_report_id": report["explainability_report_id"],
        "missing_evidence": report["missing_evidence"],
    }
