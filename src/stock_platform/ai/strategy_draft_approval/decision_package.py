"""STEP 12-15 — Decision Package & Human Decision.

이미 생성된 Strategy Definition/Approval Snapshot/Backtest/Performance/
Walk-Forward/Quality Gate/Parameter Sensitivity/Monte Carlo/Portfolio
Validation/Explainability(STEP12-5~14) 결과를 하나의 동결된 Decision
Package로 묶고, 관리자가 APPROVE_FOR_PROMOTION/REQUEST_CHANGES/REJECT
중 하나를 불변으로 기록할 수 있게 한다. 이 STEP은 사람의 승인 검토를
위한 Package와 기록 계층이다 — 자동 승인 시스템이 아니다. 실제 Promotion
Commit/Candidate Lifecycle 변경/Runtime 등록은 전혀 수행하지 않는다
(APPROVE_FOR_PROMOTION은 "Promotion Readiness" 상태만 기록 — 다음
STEP의 명시적 Commit 입력으로만 쓰인다).

재사용(중복 생성 금지 확인):
- Source Evidence 전부는 STEP12-14 `get_explainability_report()`가 이미
  종합해 둔 값만 읽는다(재계산 없음) — Explainability가 참조한
  Quality Gate/Sensitivity/Monte Carlo/Portfolio Report ID를 그대로
  재사용하고, 명시된 ID가 다르면 차단한다(사칭 방지).
- Provenance는 STEP12-5 `resolve_strategy_provenance()`(Explainability
  경유),
  Specification은 STEP12-6 `compile_specification()`을 재사용해 Stale
  Detection의 기준선(Definition Version/Hash/Executable Hash)을
  재검증한다(재계산이 아니라 "달라졌는지"만 비교).
- Decision Checklist는 STEP12-14 Explainability의 6개 Checklist를
  그대로 재사용(복사)하고, Decision Package 전용 항목만 추가한다(새
  Checklist 엔진 없음).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    _canonical_json,
    _hash,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.decision_package_entities import (
    StrategyDecisionPackageEntity,
    StrategyHumanDecisionEntity,
)
from stock_platform.ai.strategy_draft_approval.entities import StrategyDraftApprovalEntity
from stock_platform.ai.strategy_draft_approval.explainability import (
    ExplainabilityError,
    get_explainability_report,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo_entities import (
    MonteCarloSimulationReportEntity,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity_entities import (
    ParameterSensitivityReportEntity,
)
from stock_platform.ai.strategy_draft_approval.portfolio_validation_entities import (
    PortfolioValidationReportEntity,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import (
    compute_quality_gate_provenance_hash,
)
from stock_platform.ai.strategy_draft_approval.quality_gate_entities import (
    StrategyQualityGateReportEntity,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    _require_definition,
)
from stock_platform.ai.strategy_request.entities import StrategyRequestEntity
from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

ALGORITHM_VERSION = "1.0.0"
CHECKLIST_TEMPLATE_VERSION = "1.0.0"

REQUIRED_EVIDENCE_CATEGORIES = (
    "strategy_specification", "provenance", "backtest", "performance_analytics", "quality_gate",
)
CONDITIONAL_EVIDENCE_CATEGORIES = ("walk_forward", "parameter_sensitivity", "monte_carlo")

PACKAGE_STATUSES = frozenset({"BLOCKED", "READY_FOR_REVIEW"})
EFFECTIVE_PACKAGE_STATUSES = frozenset(
    {"BLOCKED", "READY_FOR_REVIEW", "STALE", "DECIDED"}
)
DECISION_TYPES = frozenset({"APPROVE_FOR_PROMOTION", "REQUEST_CHANGES", "REJECT"})

# § STEP12-16 인수 조건(STEP12-15 필수 인수 보완 1) — `APPROVE_FOR_PROMOTION`
# 이라는 이름은 "Promotion 완료"가 아니라 "Promotion Commit을 진행할 수
# 있는 Readiness 승인"이라는 뜻이다(실제 Commit은 STEP12-16의 별도
# 명시적 관리자 작업). Enum 이름은 하위 호환을 위해 바꾸지 않고, 실제
# 의미를 이 상수로 고정해 API 응답에 항상 함께 노출한다.
DECISION_MEANING: dict[str, str] = {
    "APPROVE_FOR_PROMOTION": "PROMOTION_COMMIT_ALLOWED",
    "REQUEST_CHANGES": "CHANGES_REQUESTED_NOT_PROMOTABLE",
    "REJECT": "REJECTED_NOT_PROMOTABLE",
}

REASON_CODES_BY_DECISION_TYPE: dict[str, frozenset[str]] = {
    "APPROVE_FOR_PROMOTION": frozenset(
        {
            "EVIDENCE_REVIEW_COMPLETED", "RISK_WITHIN_ACCEPTED_LIMITS",
            "WARNINGS_ACKNOWLEDGED", "READY_FOR_PROMOTION_REVIEW",
        }
    ),
    "REQUEST_CHANGES": frozenset(
        {
            "INSUFFICIENT_EVIDENCE", "PARAMETER_FRAGILITY", "OVERFITTING_CONCERN",
            "EXCESSIVE_DRAWDOWN", "HIGH_RISK_OF_RUIN", "DUPLICATE_EXPOSURE",
            "PROVENANCE_REVIEW_REQUIRED", "STRATEGY_RULE_CLARIFICATION",
        }
    ),
    "REJECT": frozenset(
        {
            "QUALITY_GATE_REJECTED", "PROVENANCE_INVALID", "UNACCEPTABLE_RISK",
            "INSUFFICIENT_ROBUSTNESS", "POLICY_VIOLATION", "EXPIRED_OR_REVOKED",
        }
    ),
}

# Lifecycle이 이 상태로 바뀌면 Package는 Stale로 취급한다(Approval Chain
# 이 더 이상 유효하지 않을 수 있음).
_STALE_LIFECYCLE_STATUSES = frozenset(
    {"REVOKED", "EXPIRED", "SUPERSEDED", "CANCELLED", "ARCHIVED", "REVOCATION_REQUESTED", "REVOCATION_BLOCKED"}
)


class DecisionPackageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Checklist Template — Explainability의 6개 Checklist(재사용) + Package 전용
# 항목(결정적 순서로 고정).
# ---------------------------------------------------------------------------


def _build_checklist_template(
    *, has_walk_forward: bool, has_sensitivity: bool, has_monte_carlo: bool, has_portfolio: bool
) -> list[dict[str, Any]]:
    items = [
        {"checklist_code": "EXPLAINABILITY_CHECKLIST_REUSED", "required": True,
         "evidence_reference": "explainability.decision_checklist", "question": "Explainability의 Human Decision Checklist를 확인했는가"},
        {"checklist_code": "DEFINITION_VERSION_CONFIRMED", "required": True,
         "evidence_reference": "strategy_overview.definition_version", "question": "Strategy Definition Version을 확인했는가"},
        {"checklist_code": "EXECUTABLE_HASH_CONFIRMED", "required": True,
         "evidence_reference": "strategy_overview.executable_hash", "question": "Executable Hash를 확인했는가"},
        {"checklist_code": "QUALITY_GATE_RESULT_CONFIRMED", "required": True,
         "evidence_reference": "quality_gate_evidence.recommendation", "question": "Quality Gate 결과를 확인했는가"},
        {"checklist_code": "BACKTEST_PERIOD_CONFIRMED", "required": True,
         "evidence_reference": "backtest_evidence.period_start_date/period_end_date", "question": "Backtest 기간을 확인했는가"},
        {"checklist_code": "MDD_CONFIRMED", "required": True,
         "evidence_reference": "backtest_evidence.maximum_drawdown_rate", "question": "Maximum Drawdown을 확인했는가"},
        {"checklist_code": "WALK_FORWARD_OVERFITTING_CONFIRMED", "required": has_walk_forward,
         "evidence_reference": "walk_forward_evidence.overfitting_grade", "question": "Walk-Forward Overfitting 수준을 확인했는가"},
        {"checklist_code": "SENSITIVITY_STABLE_RANGE_CONFIRMED", "required": has_sensitivity,
         "evidence_reference": "sensitivity_evidence.stable_range", "question": "Parameter Sensitivity Stable Range를 확인했는가"},
        {"checklist_code": "MONTE_CARLO_RISK_OF_RUIN_CONFIRMED", "required": has_monte_carlo,
         "evidence_reference": "monte_carlo_evidence.risk_of_ruin_percent", "question": "Monte Carlo Risk of Ruin을 확인했는가"},
        {"checklist_code": "PORTFOLIO_EXPOSURE_CONFIRMED", "required": has_portfolio,
         "evidence_reference": "portfolio_evidence.duplicate_exposure", "question": "Portfolio Duplicate Exposure를 확인했는가"},
        {"checklist_code": "MISSING_EVIDENCE_CONFIRMED", "required": True,
         "evidence_reference": "missing_evidence", "question": "Missing Evidence 목록을 확인했는가"},
        {"checklist_code": "WARNING_EVIDENCE_CONFIRMED", "required": True,
         "evidence_reference": "decision_summary.warning_count", "question": "Warning Evidence를 확인했는가"},
        {"checklist_code": "STALE_CHECK_CONFIRMED", "required": True,
         "evidence_reference": "staleness", "question": "Package가 Stale하지 않음을 확인했는가"},
        {"checklist_code": "NOT_INVESTMENT_ADVICE_CONFIRMED", "required": True,
         "evidence_reference": None, "question": "이 결정이 실제 투자 권고가 아님을 확인했는가"},
    ]
    return items


# ---------------------------------------------------------------------------
# Source Evidence Validation — Explainability Report가 참조한 값을 그대로
# 재사용하고, 명시된 ID가 다르면 차단한다.
# ---------------------------------------------------------------------------


def _resolve_or_match(explicit: int | None, from_explainability: int | None, *, field_name: str) -> int | None:
    if explicit is None:
        return from_explainability
    if from_explainability is not None and explicit != from_explainability:
        raise DecisionPackageError(
            "REPORT_ID_MISMATCH",
            f"{field_name}={explicit}가 Explainability Report가 참조한 값({from_explainability})과 다릅니다.",
        )
    return explicit


def _resolve_requester_id(session: Session, definition: StrategyDefinitionEntity) -> int | None:
    if definition.strategy_request_id is None:
        return None
    request = session.get(StrategyRequestEntity, definition.strategy_request_id)
    return int(request.user_id) if request is not None else None


def _compute_approval_snapshot_hash(session: Session, definition: StrategyDefinitionEntity) -> str | None:
    if definition.approval_id is None:
        return None
    approval = session.get(StrategyDraftApprovalEntity, int(definition.approval_id))
    if approval is None:
        return None
    canonical = {
        "approval_id": int(approval.approval_id),
        "draft_id": int(approval.draft_id),
        "status": approval.status,
        "candidate_fingerprint_at_approval": approval.candidate_fingerprint_at_approval,
        "strategy_definition_id": approval.strategy_definition_id,
    }
    return _hash(_canonical_json(canonical))


def _fetch_selected_reports(
    session: Session, *, quality_gate_report_id, parameter_sensitivity_report_id, monte_carlo_report_id,
    portfolio_validation_report_id,
) -> dict[str, str | None]:
    """§ Stale Detection 기준선 — 각 Report의 "내용 지문"을 계산한다. 이미
    불변인 Report들이라(UPDATE API 없음) 재계산이 아니라 스냅샷 비교
    전용이다. Quality Gate 지문은 STEP12-16에서 신설한 공용 Helper
    `compute_quality_gate_provenance_hash()`(§ quality_gate.py)를 그대로
    재사용한다(중복 계산 금지)."""
    hashes: dict[str, str | None] = {
        "quality_gate": None, "parameter_sensitivity": None, "monte_carlo": None, "portfolio_validation": None,
    }
    if quality_gate_report_id is not None:
        report = session.get(StrategyQualityGateReportEntity, quality_gate_report_id)
        if report is None:
            raise DecisionPackageError("QUALITY_GATE_NOT_FOUND", f"Quality Gate report not found: {quality_gate_report_id}")
        hashes["quality_gate"] = compute_quality_gate_provenance_hash(session, report)
    if parameter_sensitivity_report_id is not None:
        report = session.get(ParameterSensitivityReportEntity, parameter_sensitivity_report_id)
        if report is None:
            raise DecisionPackageError("SENSITIVITY_NOT_FOUND", f"Parameter Sensitivity report not found: {parameter_sensitivity_report_id}")
        hashes["parameter_sensitivity"] = report.input_hash
    if monte_carlo_report_id is not None:
        report = session.get(MonteCarloSimulationReportEntity, monte_carlo_report_id)
        if report is None:
            raise DecisionPackageError("MONTE_CARLO_NOT_FOUND", f"Monte Carlo report not found: {monte_carlo_report_id}")
        hashes["monte_carlo"] = report.report_input_hash
    if portfolio_validation_report_id is not None:
        report = session.get(PortfolioValidationReportEntity, portfolio_validation_report_id)
        if report is None:
            raise DecisionPackageError("PORTFOLIO_NOT_FOUND", f"Portfolio Validation report not found: {portfolio_validation_report_id}")
        hashes["portfolio_validation"] = report.report_input_hash
    return hashes


# ---------------------------------------------------------------------------
# Provenance / Input Hash.
# ---------------------------------------------------------------------------


def compute_package_input_hash(
    *,
    strategy_definition_id: int,
    strategy_definition_version: int | None,
    executable_hash: str | None,
    selected_report_ids: dict[str, int | None],
    explainability_input_hash: str | None,
    package_algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "strategy_definition_version": strategy_definition_version,
        "executable_hash": executable_hash,
        "selected_report_ids": {k: selected_report_ids[k] for k in sorted(selected_report_ids)},
        "explainability_input_hash": explainability_input_hash,
        "package_algorithm_version": package_algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_decision_input_hash(
    *,
    package_id: int,
    package_input_hash: str,
    decision_type: str,
    reason_code: str,
    reason_text: str,
    checklist_payload: list[dict[str, Any]],
    acknowledged_warnings: list[str],
    decided_by: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "package_id": package_id,
        "package_input_hash": package_input_hash,
        "decision_type": decision_type,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "checklist_payload": sorted(checklist_payload, key=lambda c: c["checklist_code"]),
        "acknowledged_warnings": sorted(acknowledged_warnings),
        "decided_by": decided_by,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_promotion_readiness_hash(
    *,
    package_id: int,
    package_input_hash: str,
    decision_id: int,
    decision_type: str,
    decided_by: str,
    checklist_payload: list[dict[str, Any]],
    acknowledged_warnings: list[str],
    reason_code: str,
    reason_text: str,
    decided_at: datetime,
    algorithm_version: str,
) -> str:
    canonical = {
        "package_id": package_id,
        "package_input_hash": package_input_hash,
        "decision_id": decision_id,
        "decision_type": decision_type,
        "reviewer_id": decided_by,
        "checklist_confirmations_hash": _hash(
            _canonical_json(sorted(checklist_payload, key=lambda c: c["checklist_code"]))
        ),
        "warning_acknowledgement_hash": _hash(_canonical_json(sorted(acknowledged_warnings))),
        "decision_reason_hash": _hash(_canonical_json({"reason_code": reason_code, "reason_text": reason_text})),
        "decided_at": decided_at.isoformat(),
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


# ---------------------------------------------------------------------------
# Package Readiness.
# ---------------------------------------------------------------------------


def _compute_readiness(explainability_report: dict[str, Any]) -> dict[str, Any]:
    rule_explanation = explainability_report["rule_explanation"] or {}
    provenance = explainability_report["provenance"] or {}
    backtest_evidence = explainability_report["backtest_evidence"] or {}
    quality_gate_evidence = explainability_report["quality_gate_evidence"] or {}
    decision_summary = explainability_report["decision_summary"] or {}

    strategy_specification_ok = rule_explanation.get("status") != "NOT_AVAILABLE"
    provenance_valid = bool(provenance.get("all_provenance_matches"))
    backtest_ok = backtest_evidence.get("status") == "AVAILABLE"
    performance_ok = backtest_evidence.get("performance_status") == "AVAILABLE"
    quality_gate_ok = quality_gate_evidence.get("status") == "AVAILABLE"
    explainability_complete = explainability_report["completeness_status"] != "INSUFFICIENT"

    required_evidence_complete = all(
        [strategy_specification_ok, provenance_valid, backtest_ok, performance_ok, quality_gate_ok]
    )

    reason_codes: list[str] = []
    if not strategy_specification_ok:
        reason_codes.append("STRATEGY_SPECIFICATION_NOT_COMPILABLE")
    if not provenance_valid:
        reason_codes.append("PROVENANCE_MISMATCH")
    if not backtest_ok:
        reason_codes.append("BACKTEST_NOT_AVAILABLE")
    if not performance_ok:
        reason_codes.append("PERFORMANCE_ANALYTICS_NOT_AVAILABLE")
    if not quality_gate_ok:
        reason_codes.append("QUALITY_GATE_NOT_AVAILABLE")
    elif quality_gate_evidence.get("recommendation") == "REJECT":
        reason_codes.append("QUALITY_GATE_REJECT")
    if not explainability_complete:
        reason_codes.append("EXPLAINABILITY_INSUFFICIENT")
    # Conditional Evidence의 Blocking 신호는 Explainability의 decision_summary
    # summary_codes에 이미 반영돼 있으므로 그대로 가져온다(재계산 없음).
    for code in decision_summary.get("summary_codes", []):
        if code in {
            "WALK_FORWARD_OVERFITTING_HIGH", "SENSITIVITY_FRAGILE", "MONTE_CARLO_HIGH_RISK", "PORTFOLIO_HIGH_RISK",
        }:
            reason_codes.append(code)

    blocking_evidence_count = int(decision_summary.get("blocking_count", 0))
    warning_evidence_count = int(decision_summary.get("warning_count", 0))
    missing_evidence_count = int(decision_summary.get("missing_count", 0))

    if not required_evidence_complete or not provenance_valid or not explainability_complete or blocking_evidence_count > 0:
        package_status = "BLOCKED"
    else:
        package_status = "READY_FOR_REVIEW"

    return {
        "package_status": package_status,
        "required_evidence_complete": required_evidence_complete,
        "provenance_valid": provenance_valid,
        "explainability_complete": explainability_complete,
        "blocking_evidence_count": blocking_evidence_count,
        "warning_evidence_count": warning_evidence_count,
        "missing_evidence_count": missing_evidence_count,
        "human_review_required": bool(decision_summary.get("human_review_required", True)),
        "readiness_reason_codes": reason_codes,
    }


# ---------------------------------------------------------------------------
# Stale Detection.
# ---------------------------------------------------------------------------


def check_package_staleness(session: Session, package: StrategyDecisionPackageEntity) -> tuple[bool, list[str]]:
    """Package 생성 시점 Snapshot(Definition Version/Hash/Executable Hash/
    Approval Snapshot Hash/각 Report 지문/Lifecycle 상태)과 현재 상태를
    비교한다. 원본 Report가 "단순히 최신이 아니게 됐다"는 이유만으로는
    Stale 처리하지 않는다 — Snapshot으로 고정한 값 자체가 달라졌을
    때만(즉, 무결성이 깨졌을 때만) Stale이다."""
    reasons: list[str] = []

    definition = session.get(StrategyDefinitionEntity, package.strategy_id)
    if definition is None or definition.deleted_at is not None:
        reasons.append("DEFINITION_MISSING")
        return True, reasons

    if definition.definition_version != package.strategy_definition_version:
        reasons.append("DEFINITION_VERSION_CHANGED")
    if definition.definition_hash != package.definition_hash:
        reasons.append("DEFINITION_HASH_CHANGED")

    try:
        specification = compile_specification(session, package.strategy_id)
        if specification.get("executable_hash") != package.executable_hash:
            reasons.append("EXECUTABLE_HASH_CHANGED")
    except BacktestSpecificationError:
        reasons.append("SPECIFICATION_UNAVAILABLE")

    current_approval_hash = _compute_approval_snapshot_hash(session, definition)
    if current_approval_hash != package.approval_snapshot_hash:
        reasons.append("APPROVAL_SNAPSHOT_CHANGED")

    if definition.approval_id is not None:
        approval = session.get(StrategyDraftApprovalEntity, int(definition.approval_id))
        if approval is not None and approval.status != "APPROVED":
            reasons.append(f"APPROVAL_STATUS_{approval.status}")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            reasons.append(f"LIFECYCLE_{lifecycle.lifecycle_status}")

    # 선택된 각 Report가 여전히 존재하고 내용 지문이 동일한지 확인.
    current_hashes = _fetch_selected_reports(
        session,
        quality_gate_report_id=(package.selected_report_ids or {}).get("quality_gate"),
        parameter_sensitivity_report_id=(package.selected_report_ids or {}).get("parameter_sensitivity"),
        monte_carlo_report_id=(package.selected_report_ids or {}).get("monte_carlo"),
        portfolio_validation_report_id=(package.selected_report_ids or {}).get("portfolio_validation"),
    )
    for key, current_hash in current_hashes.items():
        stored_hash = (package.selected_report_hashes or {}).get(key)
        if stored_hash is not None and current_hash != stored_hash:
            reasons.append(f"REPORT_HASH_CHANGED:{key}")

    try:
        explainability = get_explainability_report(session, package.explainability_report_id)
        if explainability["report_input_hash"] != package.explainability_input_hash:
            reasons.append("EXPLAINABILITY_HASH_CHANGED")
    except ExplainabilityError:
        reasons.append("EXPLAINABILITY_MISSING")

    return len(reasons) > 0, reasons


# ---------------------------------------------------------------------------
# Orchestration — Decision Package 생성.
# ---------------------------------------------------------------------------


def run_create_decision_package(
    session: Session,
    strategy_definition_id: int,
    *,
    explainability_report_id: int,
    quality_gate_report_id: int | None = None,
    parameter_sensitivity_report_id: int | None = None,
    monte_carlo_report_id: int | None = None,
    portfolio_validation_report_id: int | None = None,
    package_note: str | None = None,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    try:
        definition = _require_definition(session, strategy_definition_id)
    except ReadinessError as exc:
        raise DecisionPackageError(exc.code, exc.message) from exc

    try:
        explainability = get_explainability_report(session, explainability_report_id)
    except ExplainabilityError as exc:
        raise DecisionPackageError(exc.code, exc.message) from exc
    if explainability["strategy_id"] != strategy_definition_id:
        raise DecisionPackageError(
            "OWNERSHIP_MISMATCH", f"Explainability Report #{explainability_report_id}은 이 Strategy의 결과가 아닙니다.",
        )

    resolved_quality_gate_report_id = _resolve_or_match(
        quality_gate_report_id, explainability["quality_gate_report_id"], field_name="quality_gate_report_id"
    )
    resolved_sensitivity_report_id = _resolve_or_match(
        parameter_sensitivity_report_id, explainability["parameter_sensitivity_report_id"],
        field_name="parameter_sensitivity_report_id",
    )
    resolved_monte_carlo_report_id = _resolve_or_match(
        monte_carlo_report_id, explainability["monte_carlo_report_id"], field_name="monte_carlo_report_id"
    )
    resolved_portfolio_report_id = _resolve_or_match(
        portfolio_validation_report_id, explainability["portfolio_validation_report_id"],
        field_name="portfolio_validation_report_id",
    )

    selected_report_ids = {
        "backtest": explainability["backtest_run_id"],
        "walk_forward": explainability["walk_forward_run_id"],
        "quality_gate": resolved_quality_gate_report_id,
        "parameter_sensitivity": resolved_sensitivity_report_id,
        "monte_carlo": resolved_monte_carlo_report_id,
        "portfolio_validation": resolved_portfolio_report_id,
    }
    selected_report_hashes = _fetch_selected_reports(
        session, quality_gate_report_id=resolved_quality_gate_report_id,
        parameter_sensitivity_report_id=resolved_sensitivity_report_id,
        monte_carlo_report_id=resolved_monte_carlo_report_id,
        portfolio_validation_report_id=resolved_portfolio_report_id,
    )

    executable_hash = explainability["strategy_overview"].get("executable_hash")
    approval_snapshot_hash = _compute_approval_snapshot_hash(session, definition)

    package_input_hash = compute_package_input_hash(
        strategy_definition_id=strategy_definition_id, strategy_definition_version=definition.definition_version,
        executable_hash=executable_hash, selected_report_ids=selected_report_ids,
        explainability_input_hash=explainability["report_input_hash"], package_algorithm_version=ALGORITHM_VERSION,
    )

    if idempotency_key:
        existing = session.scalar(
            select(StrategyDecisionPackageEntity).where(StrategyDecisionPackageEntity.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.package_input_hash == package_input_hash:
                return _to_package_dict(session, existing, idempotent_replay=True)
            raise DecisionPackageError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 요청 내용으로 사용되었습니다."
            )

    readiness = _compute_readiness(explainability)
    checklist_template = _build_checklist_template(
        has_walk_forward=selected_report_ids["walk_forward"] is not None,
        has_sensitivity=selected_report_ids["parameter_sensitivity"] is not None,
        has_monte_carlo=selected_report_ids["monte_carlo"] is not None,
        has_portfolio=selected_report_ids["portfolio_validation"] is not None,
    )
    evidence_snapshot_hash = _hash(_canonical_json(explainability["evidence_reference"]))
    requester_id = _resolve_requester_id(session, definition)

    package = StrategyDecisionPackageEntity(
        strategy_id=strategy_definition_id,
        explainability_report_id=explainability_report_id,
        quality_gate_report_id=resolved_quality_gate_report_id,
        parameter_sensitivity_report_id=resolved_sensitivity_report_id,
        monte_carlo_report_id=resolved_monte_carlo_report_id,
        portfolio_validation_report_id=resolved_portfolio_report_id,
        package_note=package_note,
        package_status=readiness["package_status"],
        required_evidence_complete=readiness["required_evidence_complete"],
        provenance_valid=readiness["provenance_valid"],
        explainability_complete=readiness["explainability_complete"],
        blocking_evidence_count=readiness["blocking_evidence_count"],
        warning_evidence_count=readiness["warning_evidence_count"],
        missing_evidence_count=readiness["missing_evidence_count"],
        human_review_required=readiness["human_review_required"],
        readiness_reason_codes=readiness["readiness_reason_codes"],
        strategy_definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        executable_hash=executable_hash,
        approval_snapshot_hash=approval_snapshot_hash,
        selected_report_ids=selected_report_ids,
        selected_report_hashes=selected_report_hashes,
        explainability_input_hash=explainability["report_input_hash"],
        evidence_snapshot_hash=evidence_snapshot_hash,
        checklist_template_payload=checklist_template,
        checklist_template_version=CHECKLIST_TEMPLATE_VERSION,
        package_algorithm_version=ALGORITHM_VERSION,
        package_input_hash=package_input_hash,
        idempotency_key=(idempotency_key or None),
        requester_id=requester_id,
        package_created_by=actor,
    )
    session.add(package)
    session.commit()
    session.refresh(package)

    return _to_package_dict(session, package, idempotent_replay=False)


def _to_package_dict(
    session: Session, package: StrategyDecisionPackageEntity, *, idempotent_replay: bool
) -> dict[str, Any]:
    stale, stale_reasons = check_package_staleness(session, package)
    has_decision = session.scalar(
        select(StrategyHumanDecisionEntity.decision_id).where(StrategyHumanDecisionEntity.package_id == package.package_id)
    )
    if stale:
        effective_status = "STALE"
    elif has_decision is not None:
        effective_status = "DECIDED"
    else:
        effective_status = package.package_status

    return {
        "package_id": int(package.package_id),
        "strategy_id": package.strategy_id,
        "explainability_report_id": package.explainability_report_id,
        "quality_gate_report_id": package.quality_gate_report_id,
        "parameter_sensitivity_report_id": package.parameter_sensitivity_report_id,
        "monte_carlo_report_id": package.monte_carlo_report_id,
        "portfolio_validation_report_id": package.portfolio_validation_report_id,
        "package_note": package.package_note,
        # § STEP12-16 인수 조건(STEP12-15 필수 인수 보완 3) — 두 필드의
        # 의미를 이름으로 고정한다. `package_status`/`effective_package_status`
        # 는 기존 호환을 위해 유지하되(값은 완전히 동일), 새 이름을
        # 1차 필드로 노출한다: `created_package_status`는 Package 생성
        # 시점에 저장된 불변 값이고, `current_effective_status`는 지금
        # 조회 시점의 Stale/Decided 여부를 반영한 파생 값이다. Promotion
        # Commit 허용 여부 판정은 반드시 `current_effective_status`만
        # 사용해야 한다(생성 시점 값만 보고 Commit하지 않는다).
        "created_package_status": package.package_status,
        "current_effective_status": effective_status,
        "package_status": package.package_status,
        "effective_package_status": effective_status,
        "stale": stale,
        "stale_reasons": stale_reasons,
        "required_evidence_complete": package.required_evidence_complete,
        "provenance_valid": package.provenance_valid,
        "explainability_complete": package.explainability_complete,
        "blocking_evidence_count": package.blocking_evidence_count,
        "warning_evidence_count": package.warning_evidence_count,
        "missing_evidence_count": package.missing_evidence_count,
        "human_review_required": package.human_review_required,
        "readiness_reason_codes": package.readiness_reason_codes,
        "strategy_definition_version": package.strategy_definition_version,
        "definition_hash": package.definition_hash,
        "executable_hash": package.executable_hash,
        "approval_snapshot_hash": package.approval_snapshot_hash,
        "selected_report_ids": package.selected_report_ids,
        "selected_report_hashes": package.selected_report_hashes,
        "explainability_input_hash": package.explainability_input_hash,
        "evidence_snapshot_hash": package.evidence_snapshot_hash,
        "checklist_template": package.checklist_template_payload,
        "checklist_template_version": package.checklist_template_version,
        "package_algorithm_version": package.package_algorithm_version,
        "package_input_hash": package.package_input_hash,
        "requester_id": package.requester_id,
        "package_created_by": package.package_created_by,
        "created_at": package.created_at,
        "has_decision": has_decision is not None,
        "idempotent_replay": idempotent_replay,
    }


def get_decision_package_report(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = session.get(StrategyDecisionPackageEntity, package_id)
    if package is None:
        raise DecisionPackageError("NOT_FOUND", f"Decision Package not found: {package_id}")
    if strategy_definition_id is not None and package.strategy_id != strategy_definition_id:
        raise DecisionPackageError("NOT_FOUND", f"Decision Package not found: {package_id}")
    return _to_package_dict(session, package, idempotent_replay=False)


def _determine_next_action(
    *, stale: bool, has_decision: bool, decision_type: str | None,
    required_evidence_complete: bool, blocking_evidence_count: int, warning_evidence_count: int,
) -> str:
    if stale:
        return "RECREATE_STALE_PACKAGE"
    if has_decision:
        if decision_type == "APPROVE_FOR_PROMOTION":
            return "READY_FOR_PROMOTION_COMMIT"
        if decision_type == "REQUEST_CHANGES":
            return "REQUEST_CHANGES"
        return "NO_ACTION_REJECTED"
    if not required_evidence_complete or blocking_evidence_count > 0:
        return "COMPLETE_EVIDENCE"
    if warning_evidence_count > 0:
        return "REVIEW_WARNINGS"
    return "AWAITING_DECISION"


def get_decision_package_summary(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    """§16 Decision Summary — Package와(있으면) Decision을 한 번에 조합해
    돌려준다(자동 Promotion 실행 문구를 쓰지 않는다)."""
    package = get_decision_package_report(session, package_id, strategy_definition_id=strategy_definition_id)
    decision: dict[str, Any] | None = None
    if package["has_decision"]:
        decision = get_human_decision(session, package_id, strategy_definition_id=strategy_definition_id)

    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    if decision is not None:
        confirmed = {c["checklist_code"] for c in decision["checklist_payload"] if c["confirmed"]}
        checklist_completion = f"{sum(1 for c in required_codes if c in confirmed)}/{len(required_codes)}"
    else:
        checklist_completion = f"0/{len(required_codes)}"

    next_action = _determine_next_action(
        stale=package["stale"], has_decision=package["has_decision"],
        decision_type=decision["decision_type"] if decision else None,
        required_evidence_complete=package["required_evidence_complete"],
        blocking_evidence_count=package["blocking_evidence_count"],
        warning_evidence_count=package["warning_evidence_count"],
    )

    return {
        "package_id": package["package_id"],
        "package_status": package["package_status"],
        "effective_package_status": package["effective_package_status"],
        "decision_status": "DECIDED" if decision is not None else "PENDING",
        "decision_type": decision["decision_type"] if decision else None,
        "promotion_ready": decision["promotion_ready"] if decision else False,
        "stale": package["stale"],
        "required_evidence_complete": package["required_evidence_complete"],
        "blocking_count": package["blocking_evidence_count"],
        "warning_count": package["warning_evidence_count"],
        "missing_count": package["missing_evidence_count"],
        "checklist_completion": checklist_completion,
        "reviewer": decision["decided_by"] if decision else None,
        "reason_code": decision["reason_code"] if decision else None,
        "decided_at": decision["decided_at"] if decision else None,
        "human_review_required": package["human_review_required"],
        "has_decision": package["has_decision"],
        "next_action": next_action,
    }


def get_decision_package_checklist(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = get_decision_package_report(session, package_id, strategy_definition_id=strategy_definition_id)
    return {"package_id": package["package_id"], "checklist_template": package["checklist_template"]}


def get_decision_package_staleness(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package_entity = session.get(StrategyDecisionPackageEntity, package_id)
    if package_entity is None or (
        strategy_definition_id is not None and package_entity.strategy_id != strategy_definition_id
    ):
        raise DecisionPackageError("NOT_FOUND", f"Decision Package not found: {package_id}")
    stale, reasons = check_package_staleness(session, package_entity)
    return {"package_id": package_id, "stale": stale, "stale_reasons": reasons}


# ---------------------------------------------------------------------------
# Human Decision.
# ---------------------------------------------------------------------------


def run_record_human_decision(
    session: Session,
    strategy_definition_id: int,
    package_id: int,
    *,
    decision_type: str,
    reason_code: str,
    reason_text: str,
    checklist_confirmations: dict[str, bool] | None = None,
    acknowledged_warnings: list[str] | None = None,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    checklist_confirmations = checklist_confirmations or {}
    acknowledged_warnings = acknowledged_warnings or []

    package = session.get(StrategyDecisionPackageEntity, package_id)
    if package is None or package.strategy_id != strategy_definition_id:
        raise DecisionPackageError("NOT_FOUND", f"Decision Package not found: {package_id}")

    if decision_type not in DECISION_TYPES:
        raise DecisionPackageError("UNSUPPORTED_DECISION_TYPE", f"지원하지 않는 decision_type: {decision_type}")
    allowed_reason_codes = REASON_CODES_BY_DECISION_TYPE[decision_type]
    if reason_code not in allowed_reason_codes:
        raise DecisionPackageError(
            "INVALID_REASON_CODE", f"{decision_type}에 허용되지 않는 reason_code: {reason_code}"
        )
    if not reason_text or not reason_text.strip():
        raise DecisionPackageError("REASON_TEXT_REQUIRED", "reason_text는 필수입니다.")

    checklist_payload = [
        {
            "checklist_code": item["checklist_code"], "required": item["required"],
            "confirmed": bool(checklist_confirmations.get(item["checklist_code"], False)),
        }
        for item in package.checklist_template_payload
    ]

    decision_input_hash = compute_decision_input_hash(
        package_id=package_id, package_input_hash=package.package_input_hash, decision_type=decision_type,
        reason_code=reason_code, reason_text=reason_text, checklist_payload=checklist_payload,
        acknowledged_warnings=acknowledged_warnings, decided_by=actor, algorithm_version=ALGORITHM_VERSION,
    )

    existing_decision = session.scalar(
        select(StrategyHumanDecisionEntity).where(StrategyHumanDecisionEntity.package_id == package_id)
    )
    if existing_decision is not None:
        if idempotency_key and existing_decision.idempotency_key == idempotency_key:
            if existing_decision.decision_input_hash == decision_input_hash:
                return _to_decision_dict(existing_decision, idempotent_replay=True)
            raise DecisionPackageError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 요청 내용으로 사용되었습니다."
            )
        raise DecisionPackageError(
            "DUPLICATE_DECISION", f"Decision Package #{package_id}에는 이미 최종 Decision이 존재합니다."
        )

    # § STEP12-16 인수 조건(STEP12-15 필수 인수 보완 4) — Decision Type을
    # 구분하지 않고 APPROVE/REQUEST_CHANGES/REJECT 전부 Stale이면 차단한다.
    # 모든 Human Decision은 Package 생성 시점에 고정한 동일 Snapshot의
    # 무결성을 전제로 검토된 것이라, Snapshot이 깨진 뒤에는 REQUEST_CHANGES/
    # REJECT조차도 "무엇을 보고 반려했는지"를 더 이상 보장할 수 없다.
    # Stale Snapshot을 대상으로는 어떤 Decision도 새로 기록하지 않고,
    # 새 Package를 생성해 다시 검토하도록 강제한다.
    stale, stale_reasons = check_package_staleness(session, package)
    if stale:
        raise DecisionPackageError(
            "STALE_PACKAGE", f"이 Decision Package는 Stale 상태라 Decision을 생성할 수 없습니다: {', '.join(stale_reasons)}"
        )

    if decision_type == "APPROVE_FOR_PROMOTION":
        if package.package_status != "READY_FOR_REVIEW":
            raise DecisionPackageError(
                "PACKAGE_NOT_READY", f"Package 상태가 READY_FOR_REVIEW가 아닙니다(현재: {package.package_status})."
            )
        if package.blocking_evidence_count > 0:
            raise DecisionPackageError("BLOCKING_EVIDENCE_EXISTS", "Blocking Evidence가 존재해 승인할 수 없습니다.")
        required_codes = {item["checklist_code"] for item in package.checklist_template_payload if item["required"]}
        confirmed_codes = {c["checklist_code"] for c in checklist_payload if c["confirmed"]}
        missing_required = required_codes - confirmed_codes
        if missing_required:
            raise DecisionPackageError(
                "INCOMPLETE_CHECKLIST", f"필수 Checklist가 미확인 상태입니다: {sorted(missing_required)}"
            )
        if package.warning_evidence_count > 0 and not acknowledged_warnings:
            raise DecisionPackageError("WARNINGS_NOT_ACKNOWLEDGED", "Warning Evidence가 있어 승인 전 확인이 필요합니다.")

    same_actor_warning = actor == package.package_created_by

    decision = StrategyHumanDecisionEntity(
        package_id=package_id,
        strategy_id=strategy_definition_id,
        decision_type=decision_type,
        reason_code=reason_code,
        reason_text=reason_text,
        checklist_payload=checklist_payload,
        acknowledged_warnings_payload=list(acknowledged_warnings),
        requester_id=package.requester_id,
        package_created_by=package.package_created_by,
        decided_by=actor,
        same_actor_warning=same_actor_warning,
        decision_input_hash=decision_input_hash,
        algorithm_version=ALGORITHM_VERSION,
        idempotency_key=(idempotency_key or None),
    )
    session.add(decision)
    session.flush()  # decision_id(Identity) 확보 — Promotion Readiness Hash에 필요.

    if decision_type == "APPROVE_FOR_PROMOTION":
        decided_at = decision.decided_at or datetime.now(timezone.utc)
        promotion_readiness_hash = compute_promotion_readiness_hash(
            package_id=package_id, package_input_hash=package.package_input_hash,
            decision_id=int(decision.decision_id), decision_type=decision_type, decided_by=actor,
            checklist_payload=checklist_payload, acknowledged_warnings=acknowledged_warnings,
            reason_code=reason_code, reason_text=reason_text, decided_at=decided_at,
            algorithm_version=ALGORITHM_VERSION,
        )
        decision.promotion_ready = True
        decision.promotion_ready_at = decided_at
        decision.promotion_readiness_hash = promotion_readiness_hash

    session.commit()
    session.refresh(decision)
    return _to_decision_dict(decision, idempotent_replay=False)


def _to_decision_dict(decision: StrategyHumanDecisionEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "decision_id": int(decision.decision_id),
        "package_id": decision.package_id,
        "strategy_id": decision.strategy_id,
        "decision_type": decision.decision_type,
        # § STEP12-16 인수 조건(STEP12-15 필수 인수 보완 1) — Human Decision
        # 이 남긴 순간에는 실제 Promotion Commit이 아직 생성되지 않았음을
        # 항상 명시한다(사용자가 Decision만 보고 이미 Promotion됐다고
        # 오해하지 않도록). Enum 이름(APPROVE_FOR_PROMOTION)은 하위
        # 호환을 위해 바꾸지 않되, 실제 의미는 `decision_meaning`으로
        # 별도 고정한다.
        "decision_meaning": DECISION_MEANING.get(decision.decision_type),
        "promotion_committed": False,
        "reason_code": decision.reason_code,
        "reason_text": decision.reason_text,
        "checklist_payload": decision.checklist_payload,
        "acknowledged_warnings": decision.acknowledged_warnings_payload,
        "promotion_ready": decision.promotion_ready,
        "promotion_ready_at": decision.promotion_ready_at,
        "promotion_readiness_hash": decision.promotion_readiness_hash,
        "requester_id": decision.requester_id,
        "package_created_by": decision.package_created_by,
        "decided_by": decision.decided_by,
        "same_actor_warning": decision.same_actor_warning,
        "decision_input_hash": decision.decision_input_hash,
        "algorithm_version": decision.algorithm_version,
        "decided_at": decision.decided_at,
        "idempotent_replay": idempotent_replay,
    }


def get_human_decision(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = session.get(StrategyDecisionPackageEntity, package_id)
    if package is None or (strategy_definition_id is not None and package.strategy_id != strategy_definition_id):
        raise DecisionPackageError("NOT_FOUND", f"Decision Package not found: {package_id}")
    decision = session.scalar(
        select(StrategyHumanDecisionEntity).where(StrategyHumanDecisionEntity.package_id == package_id)
    )
    if decision is None:
        raise DecisionPackageError("NOT_FOUND", f"이 Package에는 아직 Decision이 없습니다: {package_id}")
    return _to_decision_dict(decision, idempotent_replay=False)


def get_promotion_readiness(
    session: Session, strategy_definition_id: int
) -> dict[str, Any]:
    decision = session.scalar(
        select(StrategyHumanDecisionEntity)
        .where(
            StrategyHumanDecisionEntity.strategy_id == strategy_definition_id,
            StrategyHumanDecisionEntity.decision_type == "APPROVE_FOR_PROMOTION",
        )
        .order_by(StrategyHumanDecisionEntity.decision_id.desc())
        .limit(1)
    )
    if decision is None:
        return {
            "ready": False, "decision_id": None, "package_id": None, "promotion_readiness_hash": None,
            "stale_after_decision": False, "next_action": "REQUEST_CHANGES",
        }
    package = session.get(StrategyDecisionPackageEntity, decision.package_id)
    stale_after_decision = False
    if package is not None:
        stale_after_decision, _ = check_package_staleness(session, package)
    next_action = "STALE_AFTER_DECISION" if stale_after_decision else "READY_FOR_PROMOTION_COMMIT"
    return {
        "ready": decision.promotion_ready and not stale_after_decision,
        "decision_id": int(decision.decision_id),
        "package_id": decision.package_id,
        "promotion_readiness_hash": decision.promotion_readiness_hash,
        "stale_after_decision": stale_after_decision,
        "next_action": next_action,
    }
