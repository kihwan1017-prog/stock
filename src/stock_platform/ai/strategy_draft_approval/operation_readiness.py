"""STEP 12-20 — Operation Readiness Certification (Package / Decision / Commit).

READY_TO_START(§ STEP12-19) Deployment를 대상으로 Strategy/Promotion/
Activation/Runtime Registration/Deployment/Scheduler Plan/Credential/
Risk/Trading Flag/Kill Switch/Recovery/Account/Runtime Scope/Deployment
Scope/History/Audit — 15개 영역을 하나의 Certification으로 재검증하고,
관리자의 명시적 Operation Commit으로 같은 `StrategyDeployment` 행을
`status_code=READY_TO_OPERATE`로 한 단계 더 전진시킨다.

Runtime 시작, Scheduler 실제 등록, Broker 연결/로그인, 실시간 시세 구독,
Signal 계산, 주문 생성/전송은 이 STEP 어디에서도 수행하지 않는다.

재사용(중복 생성 금지 확인):
- 계좌/Credential/Risk/운영/시장·브로커 검증은 STEP12-17 `activation.py`
  의 기존 헬퍼(`_resolve_account`, `_account_snapshot_payload`,
  `_broker_snapshot_payload`, `_risk_snapshot_payload`,
  `_operational_snapshot_payload`, `_validate_market_broker`)를 그대로
  가져와 쓴다.
- Promotion State 재검증은 `promotion_commit.py`의 기존
  `get_promotion_state()`를 재사용한다(이 STEP은 Promotion State를
  잠그거나 변경하지 않는다 — 읽기 전용 재확인일 뿐이다).
- 신규 Deployment 행이나 신규 Scheduler Plan 행을 만들지 않는다 — 이미
  STEP12-19에서 만든 바로 그 행을 재사용하며 `status_code`만 전진한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft_approval.activation import (
    _account_snapshot_payload,
    _broker_snapshot_payload,
    _operational_snapshot_payload,
    _resolve_account,
    _risk_snapshot_payload,
    _validate_market_broker,
)
from stock_platform.ai.strategy_draft_approval.activation_entities import (
    EXECUTION_MODE_LIVE,
    StrategyActivationCommitEntity,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.decision_package import _STALE_LIFECYCLE_STATUSES
from stock_platform.ai.strategy_draft_approval.deployment_readiness_entities import (
    StrategyDeploymentReadinessCommitEntity,
    StrategyDeploymentReadinessPackageEntity,
    StrategyRuntimeSchedulerPlanEntity,
)
from stock_platform.ai.strategy_draft_approval.operation_readiness_entities import (
    OPERATION_DECISION_APPROVE,
    OPERATION_DECISION_TYPES,
    READINESS_STATUS_BLOCKED,
    READINESS_STATUS_READY,
    StrategyOperationReadinessCommitEntity,
    StrategyOperationReadinessDecisionEntity,
    StrategyOperationReadinessHistoryEntity,
    StrategyOperationReadinessPackageEntity,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit import get_promotion_state
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import PROMOTION_STATE_ACTIVATED
from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
    StrategyRuntimeRegistrationCommitEntity,
    StrategyRuntimeRegistrationHistoryEntity,
    StrategyRuntimeRegistryEntity,
)
from stock_platform.api.deps_admin import AuditLogService
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity
from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity
from stock_platform.strategy_deployment.models import StrategyDeploymentStatus

ALGORITHM_VERSION = "1.0.0"
CONFIRMATION_TEXT_REQUIRED = "OPERATE"

_HISTORY_EVENT_BY_DECISION_TYPE: dict[str, str] = {
    "APPROVE_OPERATION": "APPROVED",
    "REQUEST_OPERATION_CHANGES": "REQUEST_CHANGES",
    "REJECT_OPERATION": "REJECTED",
}

REASON_CODES_BY_OPERATION_DECISION_TYPE: dict[str, frozenset[str]] = {
    "APPROVE_OPERATION": frozenset(
        {"CERTIFICATION_REVIEW_COMPLETED", "ALL_AREAS_PASSED", "READY_FOR_OPERATION_COMMIT"}
    ),
    "REQUEST_OPERATION_CHANGES": frozenset(
        {"CONFIGURATION_REVIEW_REQUIRED", "RISK_LIMIT_ADJUSTMENT_REQUIRED", "CREDENTIAL_REVIEW_REQUIRED"}
    ),
    "REJECT_OPERATION": frozenset(
        {"ACCOUNT_NOT_ELIGIBLE", "UNACCEPTABLE_RISK", "POLICY_VIOLATION", "CERTIFICATION_FAILED"}
    ),
}

# § 15개 Certification 영역 — Blocking Code를 영역별로 묶어 Certification
# Summary/Checklist UI에서 "영역 단위 PASS/FAIL"을 바로 보여줄 수 있게
# 한다. 여기 없는 코드는 area="OTHER"로 분류된다(방어적 처리).
_AREA_BY_BLOCKING_CODE: dict[str, str] = {
    "STRATEGY_NOT_ACTIVATED": "STRATEGY",
    "STRATEGY_NOT_FOUND": "STRATEGY",
    "STRATEGY_VERSION_MISMATCH": "STRATEGY",
    "PROMOTION_STATE_NOT_ACTIVATED": "PROMOTION",
    "ACTIVATION_COMMIT_NOT_FOUND": "ACTIVATION",
    "RUNTIME_REGISTRATION_COMMIT_NOT_FOUND": "RUNTIME_REGISTRATION",
    "RUNTIME_REGISTRY_NOT_FOUND": "RUNTIME_REGISTRATION",
    "DEPLOYMENT_READINESS_COMMIT_NOT_FOUND": "DEPLOYMENT",
    "DEPLOYMENT_NOT_READY": "DEPLOYMENT",
    "SCHEDULER_PLAN_NOT_FOUND": "SCHEDULER_PLAN",
    "SCHEDULER_PLAN_INVALID": "SCHEDULER_PLAN",
    "CREDENTIAL_NOT_FOUND": "CREDENTIAL",
    "CREDENTIAL_REVOKED": "CREDENTIAL",
    "CREDENTIAL_CONFIGURATION_INVALID": "CREDENTIAL",
    "EXPLICIT_LIVE_RISK_REQUIRED": "RISK",
    "RISK_SETTING_NOT_FOUND": "RISK",
    "RISK_CONFIGURATION_INVALID": "RISK",
    "TRADING_DISABLED": "TRADING_FLAG",
    "LIVE_ORDER_DISABLED": "TRADING_FLAG",
    "KILL_SWITCH_ACTIVE": "KILL_SWITCH",
    "RECOVERY_CONFLICT": "RECOVERY",
    "ACCOUNT_NOT_FOUND": "ACCOUNT",
    "ACCOUNT_INACTIVE": "ACCOUNT",
    "ACCOUNT_PAUSED": "ACCOUNT",
    "ACCOUNT_CONFIGURATION_INVALID": "ACCOUNT",
    "ACCOUNT_OWNERSHIP_MISMATCH": "ACCOUNT",
    "UNSUPPORTED_MARKET": "BROKER",
    "UNSUPPORTED_BROKER": "BROKER",
    "MARKET_BROKER_MISMATCH": "BROKER",
    "BROKER_CONFIGURATION_INVALID": "BROKER",
    "RUNTIME_CONFIGURATION_INVALID": "RUNTIME_SCOPE",
    "RUNTIME_SCOPE_MISMATCH": "RUNTIME_SCOPE",
    "DEPLOYMENT_SCOPE_MISMATCH": "DEPLOYMENT_SCOPE",
    "HISTORY_NOT_FOUND": "HISTORY",
    "AUDIT_NOT_FOUND": "AUDIT",
}

_CERTIFICATION_AREAS: tuple[str, ...] = (
    "STRATEGY", "PROMOTION", "ACTIVATION", "RUNTIME_REGISTRATION", "DEPLOYMENT", "SCHEDULER_PLAN",
    "CREDENTIAL", "RISK", "TRADING_FLAG", "KILL_SWITCH", "RECOVERY", "ACCOUNT", "RUNTIME_SCOPE",
    "DEPLOYMENT_SCOPE", "HISTORY", "AUDIT",
)


class OperationReadinessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _normalize_confirmation_text(value: str) -> str:
    return (value or "").strip().upper()


def _build_certification_areas(blocking_codes: list[str]) -> dict[str, Any]:
    failed_areas: dict[str, list[str]] = {}
    for code in blocking_codes:
        area = _AREA_BY_BLOCKING_CODE.get(code, "OTHER")
        failed_areas.setdefault(area, []).append(code)
    return {
        area: {"passed": area not in failed_areas, "blocking_reason_codes": failed_areas.get(area, [])}
        for area in _CERTIFICATION_AREAS
    }


def build_operation_readiness_checklist_template(execution_mode: str) -> list[dict[str, Any]]:
    items = [
        {"checklist_code": "STRATEGY_CONFIRMED", "required": True, "question": "Strategy(ACTIVATED/Version)를 확인했는가"},
        {"checklist_code": "PROMOTION_CONFIRMED", "required": True, "question": "Promotion 상태를 확인했는가"},
        {"checklist_code": "ACTIVATION_CONFIRMED", "required": True, "question": "Activation Commit을 확인했는가"},
        {"checklist_code": "RUNTIME_REGISTRATION_CONFIRMED", "required": True, "question": "Runtime Registration Commit을 확인했는가"},
        {"checklist_code": "DEPLOYMENT_CONFIRMED", "required": True, "question": "Deployment(READY_TO_START)를 확인했는가"},
        {"checklist_code": "SCHEDULER_PLAN_CONFIRMED", "required": True, "question": "Scheduler Plan(비활성)을 확인했는가"},
        {"checklist_code": "RUNTIME_ENABLED_FALSE_CONFIRMED", "required": True, "question": "Runtime enabled=false를 확인했는가"},
        {"checklist_code": "RUNTIME_RUNNING_FALSE_CONFIRMED", "required": True, "question": "Runtime running=false를 확인했는가"},
        {"checklist_code": "SCHEDULER_DISABLED_CONFIRMED", "required": True, "question": "Scheduler가 비활성 상태임을 확인했는가"},
        {"checklist_code": "SCHEDULER_JOB_NONE_CONFIRMED", "required": True, "question": "실제 Scheduler Job이 없음을 확인했는가"},
        {"checklist_code": "BROKER_DISCONNECTED_CONFIRMED", "required": True, "question": "Broker 미연결을 확인했는가"},
        {"checklist_code": "MARKET_DATA_NONE_CONFIRMED", "required": True, "question": "실시간 시세 미구독을 확인했는가"},
        {"checklist_code": "ORDER_NONE_CONFIRMED", "required": True, "question": "주문 불가 상태를 확인했는가"},
        {"checklist_code": "TRADING_ENABLED_CONFIRMED", "required": True, "question": "Trading Flag가 활성 상태임을 확인했는가"},
        {"checklist_code": "KILL_SWITCH_OFF_CONFIRMED", "required": True, "question": "Kill Switch 비활성을 확인했는가"},
        {"checklist_code": "RECOVERY_CONFLICT_NONE_CONFIRMED", "required": True, "question": "Recovery Conflict 없음을 확인했는가"},
        {"checklist_code": "ACCOUNT_ACTIVE_CONFIRMED", "required": True, "question": "Account 활성 상태를 확인했는가"},
        {"checklist_code": "OWNERSHIP_CONFIRMED", "required": True, "question": "Ownership을 확인했는가"},
        {"checklist_code": "RUNTIME_SCOPE_CONFIRMED", "required": True, "question": "Runtime Scope 일관성을 확인했는가"},
        {"checklist_code": "DEPLOYMENT_SCOPE_CONFIRMED", "required": True, "question": "Deployment Scope 일관성을 확인했는가"},
        {"checklist_code": "HISTORY_CONFIRMED", "required": True, "question": "History가 정상 기록됐음을 확인했는가"},
        {"checklist_code": "AUDIT_CONFIRMED", "required": True, "question": "Audit이 정상 기록됐음을 확인했는가"},
        {"checklist_code": "NOT_AUTO_TRADING_START_CONFIRMED", "required": True, "question": "이 Commit이 자동매매 시작이 아님을 확인했는가"},
    ]
    if execution_mode == EXECUTION_MODE_LIVE:
        items.append({"checklist_code": "CREDENTIAL_VERIFIED_CONFIRMED", "required": True, "question": "Credential Verified를 확인했는가"})
        items.append({"checklist_code": "RISK_EXPLICIT_CONFIRMED", "required": True, "question": "Explicit Risk 설정을 확인했는가"})
        items.append({"checklist_code": "LIVE_ORDER_ENABLED_CONFIRMED", "required": True, "question": "Live Order Flag를 확인했는가"})
    return items


def compute_operation_input_hash(
    *,
    strategy_definition_id: int,
    deployment_readiness_commit_id: int,
    runtime_scope_hash: str,
    strategy_snapshot_payload: dict[str, Any],
    promotion_snapshot_payload: dict[str, Any],
    activation_snapshot_payload: dict[str, Any],
    runtime_registration_snapshot_payload: dict[str, Any],
    deployment_snapshot_payload: dict[str, Any],
    scheduler_plan_snapshot_payload: dict[str, Any],
    credential_snapshot_payload: dict[str, Any],
    risk_snapshot_payload: dict[str, Any],
    trading_flag_snapshot_payload: dict[str, Any],
    kill_switch_snapshot_payload: dict[str, Any],
    recovery_snapshot_payload: dict[str, Any],
    runtime_scope_snapshot_payload: dict[str, Any],
    deployment_scope_snapshot_payload: dict[str, Any],
    history_snapshot_payload: dict[str, Any],
    audit_snapshot_payload: dict[str, Any],
    blocking_reason_codes: list[str],
    warning_reason_codes: list[str],
    missing_requirement_codes: list[str],
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "deployment_readiness_commit_id": deployment_readiness_commit_id,
        "runtime_scope_hash": runtime_scope_hash,
        "strategy_snapshot_payload": strategy_snapshot_payload,
        "promotion_snapshot_payload": promotion_snapshot_payload,
        "activation_snapshot_payload": activation_snapshot_payload,
        "runtime_registration_snapshot_payload": runtime_registration_snapshot_payload,
        "deployment_snapshot_payload": deployment_snapshot_payload,
        "scheduler_plan_snapshot_payload": scheduler_plan_snapshot_payload,
        "credential_snapshot_payload": credential_snapshot_payload,
        "risk_snapshot_payload": risk_snapshot_payload,
        "trading_flag_snapshot_payload": trading_flag_snapshot_payload,
        "kill_switch_snapshot_payload": kill_switch_snapshot_payload,
        "recovery_snapshot_payload": recovery_snapshot_payload,
        "runtime_scope_snapshot_payload": runtime_scope_snapshot_payload,
        "deployment_scope_snapshot_payload": deployment_scope_snapshot_payload,
        "history_snapshot_payload": history_snapshot_payload,
        "audit_snapshot_payload": audit_snapshot_payload,
        "blocking_reason_codes": sorted(blocking_reason_codes),
        "warning_reason_codes": sorted(warning_reason_codes),
        "missing_requirement_codes": sorted(missing_requirement_codes),
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_operation_decision_input_hash(
    *,
    operation_readiness_package_id: int,
    decision_type: str,
    reason_code: str,
    reason_text: str,
    checklist_payload: dict[str, Any],
    acknowledged_warnings_payload: list[str],
    decided_by: str,
    decided_at: datetime,
    algorithm_version: str,
) -> str:
    canonical = {
        "operation_readiness_package_id": operation_readiness_package_id, "decision_type": decision_type,
        "reason_code": reason_code, "reason_text": reason_text, "checklist_payload": checklist_payload,
        "acknowledged_warnings_payload": sorted(acknowledged_warnings_payload), "decided_by": decided_by,
        "decided_at": decided_at.isoformat(), "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_operation_commit_hash(
    *,
    strategy_definition_id: int,
    deployment_readiness_commit_id: int,
    operation_readiness_package_id: int,
    operation_readiness_decision_id: int,
    runtime_scope_hash: str,
    operation_input_hash: str,
    decision_input_hash: str,
    committed_by: str,
    committed_at: datetime,
    confirmation_hash: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "deployment_readiness_commit_id": deployment_readiness_commit_id,
        "operation_readiness_package_id": operation_readiness_package_id,
        "operation_readiness_decision_id": operation_readiness_decision_id,
        "runtime_scope_hash": runtime_scope_hash,
        "operation_input_hash": operation_input_hash,
        "decision_input_hash": decision_input_hash,
        "committed_by": committed_by,
        "committed_at": committed_at.isoformat(),
        "confirmation_hash": confirmation_hash,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def _write_operation_history(
    session: Session,
    *,
    strategy_definition_id: int,
    runtime_scope_hash: str | None,
    deployment_id: int | None,
    event_type: str,
    previous_status: str | None,
    current_status: str,
    source_type: str,
    source_id: int,
    actor: str,
    occurred_at: datetime,
    metadata_payload: dict[str, Any],
) -> StrategyOperationReadinessHistoryEntity:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "runtime_scope_hash": runtime_scope_hash,
        "event_type": event_type, "previous_status": previous_status, "current_status": current_status,
        "source_type": source_type, "source_id": source_id, "actor_id": actor, "occurred_at": occurred_at.isoformat(),
        "algorithm_version": ALGORITHM_VERSION,
    }
    event_hash = _hash(_canonical_json(canonical))
    history = StrategyOperationReadinessHistoryEntity(
        strategy_definition_id=strategy_definition_id, runtime_scope_hash=runtime_scope_hash,
        deployment_id=deployment_id, event_type=event_type, previous_status=previous_status,
        current_status=current_status, source_type=source_type, source_id=source_id, actor_id=actor,
        metadata_payload=metadata_payload, event_hash=event_hash, occurred_at=occurred_at,
    )
    session.add(history)
    session.flush()
    return history


def _to_history_dict(history: StrategyOperationReadinessHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(history.history_id), "strategy_definition_id": history.strategy_definition_id,
        "runtime_scope_hash": history.runtime_scope_hash, "deployment_id": history.deployment_id,
        "event_type": history.event_type, "previous_status": history.previous_status,
        "current_status": history.current_status, "source_type": history.source_type, "source_id": history.source_id,
        "actor_id": history.actor_id, "metadata_payload": history.metadata_payload, "event_hash": history.event_hash,
        "occurred_at": history.occurred_at,
    }


def _gather_operation_context(
    session: Session, *, strategy_definition_id: int, deployment_readiness_commit_id: int,
) -> dict[str, Any]:
    """§ 15개 영역 재검증의 핵심 — 이미 확정된 Deployment Readiness Commit
    체인을 따라 관련 행을 전부 읽어와 검증하고 15개 Snapshot을 만든다.
    어떤 행도 새로 만들거나 수정하지 않는다(순수 읽기 전용)."""
    blocking: list[str] = []
    warning: list[str] = []
    missing: list[str] = []

    definition = session.get(StrategyDefinitionEntity, strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        raise OperationReadinessError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    deploy_commit = session.get(StrategyDeploymentReadinessCommitEntity, deployment_readiness_commit_id)
    if deploy_commit is None or deploy_commit.strategy_definition_id != strategy_definition_id:
        raise OperationReadinessError(
            "DEPLOYMENT_READINESS_COMMIT_NOT_FOUND",
            f"Deployment Readiness Commit not found: {deployment_readiness_commit_id}",
        )
    deploy_package = session.get(StrategyDeploymentReadinessPackageEntity, deploy_commit.deployment_readiness_package_id)
    if deploy_package is None:
        raise OperationReadinessError(
            "DEPLOYMENT_READINESS_COMMIT_NOT_FOUND",
            f"Deployment Readiness Package not found for commit {deployment_readiness_commit_id}",
        )

    reg_commit = session.get(StrategyRuntimeRegistrationCommitEntity, deploy_commit.runtime_registration_commit_id)
    if reg_commit is None:
        blocking.append("RUNTIME_REGISTRATION_COMMIT_NOT_FOUND")

    registry = session.get(StrategyRuntimeRegistryEntity, deploy_commit.runtime_registry_id)
    if registry is None:
        blocking.append("RUNTIME_REGISTRY_NOT_FOUND")
    else:
        if registry.enabled or registry.running:
            blocking.append("RUNTIME_CONFIGURATION_INVALID")
        if registry.runtime_scope_hash != deploy_commit.runtime_scope_hash:
            blocking.append("RUNTIME_SCOPE_MISMATCH")

    deployment = session.get(StrategyDeploymentEntity, deploy_commit.strategy_deployment_id)
    if deployment is None:
        blocking.append("DEPLOYMENT_NOT_READY")
    elif deployment.status_code != StrategyDeploymentStatus.READY_TO_START.value:
        blocking.append("DEPLOYMENT_NOT_READY")

    scheduler_plan = session.get(StrategyRuntimeSchedulerPlanEntity, deploy_commit.scheduler_plan_id)
    if scheduler_plan is None:
        blocking.append("SCHEDULER_PLAN_NOT_FOUND")
    else:
        if scheduler_plan.enabled or scheduler_plan.registered_to_scheduler or scheduler_plan.scheduler_job_id is not None:
            blocking.append("SCHEDULER_PLAN_INVALID")
        if scheduler_plan.runtime_scope_hash != deploy_commit.runtime_scope_hash:
            blocking.append("DEPLOYMENT_SCOPE_MISMATCH")

    activation_commit = None
    if reg_commit is not None:
        activation_commit = session.get(StrategyActivationCommitEntity, reg_commit.activation_commit_id)
        if activation_commit is None:
            blocking.append("ACTIVATION_COMMIT_NOT_FOUND")

    state = get_promotion_state(session, strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        blocking.append("STRATEGY_NOT_ACTIVATED")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            blocking.append("STRATEGY_NOT_ACTIVATED")
    if definition.definition_version != deploy_package.strategy_version:
        blocking.append("STRATEGY_VERSION_MISMATCH")

    market_blocking, market_warning = _validate_market_broker(
        strategy_market_type=definition.market_type, target_market_type=deploy_package.market_type,
        target_broker_code=deploy_package.broker_code, target_account_kind=deploy_package.account_kind,
    )
    blocking.extend(market_blocking)
    warning.extend(market_warning)

    account, account_blocking = _resolve_account(
        session, target_account_kind=deploy_package.account_kind,
        target_user_broker_account_id=deploy_package.target_user_broker_account_id,
        target_paper_account_id=deploy_package.target_paper_account_id,
    )
    for code in account_blocking:
        blocking.append("ACCOUNT_CONFIGURATION_INVALID" if code == "ACCOUNT_INACTIVE" else code)

    if (
        account is not None
        and definition.owner_type == "USER"
        and definition.user_id is not None
        and account.user_id is not None
        and int(account.user_id) != int(definition.user_id)
    ):
        blocking.append("ACCOUNT_OWNERSHIP_MISMATCH")

    broker_snapshot, broker_blocking, broker_warning = _broker_snapshot_payload(
        session, account=account, target_account_kind=deploy_package.account_kind,
        requested_execution_mode=deploy_package.execution_mode,
    )
    blocking.extend(broker_blocking)
    warning.extend(broker_warning)

    risk_snapshot, risk_blocking, risk_warning = _risk_snapshot_payload(
        session, account=account, target_account_kind=deploy_package.account_kind,
        requested_execution_mode=deploy_package.execution_mode,
    )
    blocking.extend(risk_blocking)
    warning.extend(risk_warning)
    if deploy_package.execution_mode == EXECUTION_MODE_LIVE and not risk_snapshot.get("effective_risk_explicit"):
        blocking.append("EXPLICIT_LIVE_RISK_REQUIRED")

    operational_snapshot, op_blocking, op_warning = _operational_snapshot_payload(
        session, strategy_definition_id=strategy_definition_id, account=account,
        target_account_kind=deploy_package.account_kind,
    )
    # § Deployment Readiness에서 이미 Deployment가 존재하는 것은 정상(바로
    # 이 Deployment이므로) — DEPLOYMENT_ALREADY_EXISTS를 여기서는 오탐으로
    # 취급해 제외한다.
    blocking.extend(code for code in op_blocking if code != "DEPLOYMENT_ALREADY_EXISTS")
    warning.extend(op_warning)

    account_snapshot = _account_snapshot_payload(account, kind=deploy_package.account_kind)

    reg_history_exists = False
    if reg_commit is not None:
        reg_history_exists = session.scalar(
            select(StrategyRuntimeRegistrationHistoryEntity.history_id).where(
                StrategyRuntimeRegistrationHistoryEntity.strategy_definition_id == strategy_definition_id,
                StrategyRuntimeRegistrationHistoryEntity.event_type == "RUNTIME_REGISTERED",
                StrategyRuntimeRegistrationHistoryEntity.runtime_scope_hash == reg_commit.runtime_scope_hash,
            ).limit(1)
        ) is not None
    deploy_history_exists = session.scalar(
        select(StrategyDeploymentReadinessCommitEntity.deployment_readiness_commit_id).where(
            StrategyDeploymentReadinessCommitEntity.deployment_readiness_commit_id == deployment_readiness_commit_id
        ).limit(1)
    ) is not None
    if not reg_history_exists or not deploy_history_exists:
        blocking.append("HISTORY_NOT_FOUND")

    audit_exists = session.scalar(
        select(AuditEvent.audit_event_id).where(
            AuditEvent.strategy_id == str(strategy_definition_id),
            AuditEvent.event_type.in_(("RUNTIME_REGISTERED", "DEPLOYMENT_READY_TO_START")),
        ).limit(1)
    ) is not None
    if not audit_exists:
        blocking.append("AUDIT_NOT_FOUND")

    strategy_snapshot = {
        "strategy_definition_id": strategy_definition_id, "definition_version": definition.definition_version,
        "definition_hash": definition.definition_hash, "owner_type": definition.owner_type,
        "user_id": definition.user_id, "market_type": definition.market_type, "is_active": bool(definition.is_active),
    }
    promotion_snapshot = {
        "current_status": state["current_status"], "status_version": state["status_version"],
        "state_hash": state["state_hash"],
    }
    activation_snapshot = (
        {
            "activation_commit_id": int(activation_commit.activation_commit_id),
            "activation_commit_hash": activation_commit.activation_commit_hash,
            "execution_mode": activation_commit.execution_mode,
        }
        if activation_commit is not None
        else {}
    )
    runtime_registration_snapshot = (
        {
            "runtime_registration_commit_id": int(reg_commit.runtime_registration_commit_id),
            "registration_commit_hash": reg_commit.registration_commit_hash,
            "runtime_registry_id": deploy_commit.runtime_registry_id,
            "registry_enabled": bool(registry.enabled) if registry is not None else None,
            "registry_running": bool(registry.running) if registry is not None else None,
            "registry_status": registry.status if registry is not None else None,
        }
        if reg_commit is not None
        else {}
    )
    deployment_snapshot = {
        "deployment_readiness_commit_id": int(deploy_commit.deployment_readiness_commit_id),
        "deployment_commit_hash": deploy_commit.deployment_commit_hash,
        "strategy_deployment_id": deploy_commit.strategy_deployment_id,
        "deployment_status": deployment.status_code if deployment is not None else None,
    }
    scheduler_plan_snapshot = (
        {
            "scheduler_plan_id": int(scheduler_plan.scheduler_plan_id), "plan_hash": scheduler_plan.plan_hash,
            "enabled": bool(scheduler_plan.enabled), "registered_to_scheduler": bool(scheduler_plan.registered_to_scheduler),
            "scheduler_job_id": scheduler_plan.scheduler_job_id, "scheduler_type": scheduler_plan.scheduler_type,
        }
        if scheduler_plan is not None
        else {}
    )
    trading_flag_snapshot = {
        "auto_trading_enabled": risk_snapshot.get("auto_trading_enabled"),
        "buy_enabled": risk_snapshot.get("buy_enabled"), "sell_enabled": risk_snapshot.get("sell_enabled"),
        "live_order_enabled": account_snapshot.get("live_order_enabled"),
    }
    if not trading_flag_snapshot["auto_trading_enabled"]:
        blocking.append("TRADING_DISABLED")
    if deploy_package.execution_mode == EXECUTION_MODE_LIVE and not trading_flag_snapshot["live_order_enabled"]:
        blocking.append("LIVE_ORDER_DISABLED")
    if operational_snapshot.get("kill_switch_active"):
        blocking.append("KILL_SWITCH_ACTIVE")
    if operational_snapshot.get("recovery_paused"):
        blocking.append("RECOVERY_CONFLICT")
    kill_switch_snapshot = {
        "kill_switch_active": operational_snapshot.get("kill_switch_active"),
        "kill_switch_scope_codes": operational_snapshot.get("kill_switch_scope_codes"),
    }
    recovery_snapshot = {"recovery_paused": operational_snapshot.get("recovery_paused")}
    runtime_scope_snapshot = {
        "runtime_scope_hash": deploy_commit.runtime_scope_hash, "account_kind": deploy_package.account_kind,
        "market_type": deploy_package.market_type, "broker_code": deploy_package.broker_code,
        "execution_mode": deploy_package.execution_mode, "strategy_version": deploy_package.strategy_version,
    }
    deployment_scope_snapshot = {
        "strategy_deployment_id": deploy_commit.strategy_deployment_id,
        "scheduler_plan_id": deploy_commit.scheduler_plan_id, "runtime_scope_hash": deploy_commit.runtime_scope_hash,
    }
    history_snapshot = {
        "runtime_registration_history_exists": reg_history_exists,
        "deployment_readiness_history_exists": deploy_history_exists,
    }
    audit_snapshot = {"audit_exists": audit_exists}

    return {
        "definition": definition, "deploy_commit": deploy_commit, "deploy_package": deploy_package,
        "reg_commit": reg_commit, "registry": registry, "deployment": deployment, "scheduler_plan": scheduler_plan,
        "account": account, "blocking": sorted(set(blocking)), "warning": sorted(set(warning) - set(blocking)),
        "missing": sorted(set(missing)),
        "strategy_snapshot_payload": strategy_snapshot, "promotion_snapshot_payload": promotion_snapshot,
        "activation_snapshot_payload": activation_snapshot,
        "runtime_registration_snapshot_payload": runtime_registration_snapshot,
        "deployment_snapshot_payload": deployment_snapshot, "scheduler_plan_snapshot_payload": scheduler_plan_snapshot,
        "credential_snapshot_payload": broker_snapshot, "risk_snapshot_payload": risk_snapshot,
        "trading_flag_snapshot_payload": trading_flag_snapshot, "kill_switch_snapshot_payload": kill_switch_snapshot,
        "recovery_snapshot_payload": recovery_snapshot, "runtime_scope_snapshot_payload": runtime_scope_snapshot,
        "deployment_scope_snapshot_payload": deployment_scope_snapshot, "history_snapshot_payload": history_snapshot,
        "audit_snapshot_payload": audit_snapshot, "account_snapshot_payload": account_snapshot,
        "operational_snapshot_payload": operational_snapshot,
    }


def run_create_operation_readiness_package(
    session: Session,
    strategy_definition_id: int,
    *,
    deployment_readiness_commit_id: int,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if idempotency_key:
        existing = session.scalar(
            select(StrategyOperationReadinessPackageEntity).where(
                StrategyOperationReadinessPackageEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            same_request = (
                existing.strategy_definition_id == strategy_definition_id
                and existing.deployment_readiness_commit_id == deployment_readiness_commit_id
            )
            if same_request:
                return _to_package_dict(existing, idempotent_replay=True)
            raise OperationReadinessError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")

    ctx = _gather_operation_context(
        session, strategy_definition_id=strategy_definition_id,
        deployment_readiness_commit_id=deployment_readiness_commit_id,
    )
    created_at = datetime.now(timezone.utc)
    readiness_status = READINESS_STATUS_BLOCKED if ctx["blocking"] else READINESS_STATUS_READY
    certification_areas = _build_certification_areas(ctx["blocking"])

    operation_input_hash = compute_operation_input_hash(
        strategy_definition_id=strategy_definition_id, deployment_readiness_commit_id=deployment_readiness_commit_id,
        runtime_scope_hash=ctx["deploy_commit"].runtime_scope_hash,
        strategy_snapshot_payload=ctx["strategy_snapshot_payload"], promotion_snapshot_payload=ctx["promotion_snapshot_payload"],
        activation_snapshot_payload=ctx["activation_snapshot_payload"],
        runtime_registration_snapshot_payload=ctx["runtime_registration_snapshot_payload"],
        deployment_snapshot_payload=ctx["deployment_snapshot_payload"],
        scheduler_plan_snapshot_payload=ctx["scheduler_plan_snapshot_payload"],
        credential_snapshot_payload=ctx["credential_snapshot_payload"], risk_snapshot_payload=ctx["risk_snapshot_payload"],
        trading_flag_snapshot_payload=ctx["trading_flag_snapshot_payload"],
        kill_switch_snapshot_payload=ctx["kill_switch_snapshot_payload"], recovery_snapshot_payload=ctx["recovery_snapshot_payload"],
        runtime_scope_snapshot_payload=ctx["runtime_scope_snapshot_payload"],
        deployment_scope_snapshot_payload=ctx["deployment_scope_snapshot_payload"],
        history_snapshot_payload=ctx["history_snapshot_payload"], audit_snapshot_payload=ctx["audit_snapshot_payload"],
        blocking_reason_codes=ctx["blocking"], warning_reason_codes=ctx["warning"], missing_requirement_codes=ctx["missing"],
        algorithm_version=ALGORITHM_VERSION,
    )

    deploy_package = ctx["deploy_package"]
    package = StrategyOperationReadinessPackageEntity(
        strategy_definition_id=strategy_definition_id, deployment_readiness_commit_id=deployment_readiness_commit_id,
        runtime_registration_commit_id=ctx["deploy_commit"].runtime_registration_commit_id,
        runtime_registry_id=ctx["deploy_commit"].runtime_registry_id,
        strategy_deployment_id=ctx["deploy_commit"].strategy_deployment_id,
        scheduler_plan_id=ctx["deploy_commit"].scheduler_plan_id, runtime_scope_hash=ctx["deploy_commit"].runtime_scope_hash,
        target_user_id=deploy_package.target_user_id, account_kind=deploy_package.account_kind,
        target_user_broker_account_id=deploy_package.target_user_broker_account_id,
        target_paper_account_id=deploy_package.target_paper_account_id, market_type=deploy_package.market_type,
        broker_code=deploy_package.broker_code, execution_mode=deploy_package.execution_mode,
        strategy_version=deploy_package.strategy_version,
        strategy_snapshot_payload=ctx["strategy_snapshot_payload"], promotion_snapshot_payload=ctx["promotion_snapshot_payload"],
        activation_snapshot_payload=ctx["activation_snapshot_payload"],
        runtime_registration_snapshot_payload=ctx["runtime_registration_snapshot_payload"],
        deployment_snapshot_payload=ctx["deployment_snapshot_payload"],
        scheduler_plan_snapshot_payload=ctx["scheduler_plan_snapshot_payload"],
        credential_snapshot_payload=ctx["credential_snapshot_payload"], risk_snapshot_payload=ctx["risk_snapshot_payload"],
        trading_flag_snapshot_payload=ctx["trading_flag_snapshot_payload"],
        kill_switch_snapshot_payload=ctx["kill_switch_snapshot_payload"], recovery_snapshot_payload=ctx["recovery_snapshot_payload"],
        runtime_scope_snapshot_payload=ctx["runtime_scope_snapshot_payload"],
        deployment_scope_snapshot_payload=ctx["deployment_scope_snapshot_payload"],
        history_snapshot_payload=ctx["history_snapshot_payload"], audit_snapshot_payload=ctx["audit_snapshot_payload"],
        readiness_status=readiness_status, blocking_reason_codes=ctx["blocking"], warning_reason_codes=ctx["warning"],
        missing_requirement_codes=ctx["missing"], certification_areas_payload=certification_areas,
        operation_input_hash=operation_input_hash, algorithm_version=ALGORITHM_VERSION, created_by=actor,
        created_at=created_at, idempotency_key=(idempotency_key or None),
    )
    try:
        session.add(package)
        session.flush()
        _write_operation_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=ctx["deploy_commit"].runtime_scope_hash,
            deployment_id=None, event_type="REVIEW_CREATED", previous_status=None, current_status=readiness_status,
            source_type="PACKAGE", source_id=int(package.operation_readiness_package_id), actor=actor,
            occurred_at=created_at, metadata_payload={"blocking_reason_codes": ctx["blocking"]},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyOperationReadinessPackageEntity).where(
                    StrategyOperationReadinessPackageEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_package_dict(conflict, idempotent_replay=True)
        raise OperationReadinessError("DUPLICATE_OPERATION_READINESS_REVIEW", "동일 Package/History 저장 중 충돌이 발생했습니다.") from None

    session.refresh(package)
    return _to_package_dict(package, idempotent_replay=False)


def _to_package_dict(package: StrategyOperationReadinessPackageEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "operation_readiness_package_id": int(package.operation_readiness_package_id),
        "strategy_definition_id": package.strategy_definition_id,
        "deployment_readiness_commit_id": package.deployment_readiness_commit_id,
        "runtime_registration_commit_id": package.runtime_registration_commit_id,
        "runtime_registry_id": package.runtime_registry_id,
        "strategy_deployment_id": package.strategy_deployment_id,
        "scheduler_plan_id": package.scheduler_plan_id,
        "runtime_scope_hash": package.runtime_scope_hash,
        "account_kind": package.account_kind,
        "market_type": package.market_type,
        "broker_code": package.broker_code,
        "execution_mode": package.execution_mode,
        "strategy_version": package.strategy_version,
        "readiness_status": package.readiness_status,
        "blocking_reason_codes": package.blocking_reason_codes,
        "warning_reason_codes": package.warning_reason_codes,
        "missing_requirement_codes": package.missing_requirement_codes,
        "certification_areas_payload": package.certification_areas_payload,
        "operation_input_hash": package.operation_input_hash,
        "algorithm_version": package.algorithm_version,
        "created_by": package.created_by,
        "created_at": package.created_at,
        "idempotency_key": package.idempotency_key,
        "idempotent_replay": idempotent_replay,
    }


def check_operation_readiness_package_staleness(
    session: Session, package: StrategyOperationReadinessPackageEntity
) -> tuple[bool, list[str]]:
    try:
        ctx = _gather_operation_context(
            session, strategy_definition_id=package.strategy_definition_id,
            deployment_readiness_commit_id=package.deployment_readiness_commit_id,
        )
    except OperationReadinessError:
        return True, ["DEPLOYMENT_READINESS_COMMIT_MISSING"]

    reasons: list[str] = []
    if ctx["strategy_snapshot_payload"] != package.strategy_snapshot_payload:
        reasons.append("STRATEGY_SNAPSHOT_CHANGED")
    if ctx["promotion_snapshot_payload"] != package.promotion_snapshot_payload:
        reasons.append("PROMOTION_SNAPSHOT_CHANGED")
    if ctx["runtime_registration_snapshot_payload"] != package.runtime_registration_snapshot_payload:
        reasons.append("RUNTIME_REGISTRATION_SNAPSHOT_CHANGED")
    if ctx["deployment_snapshot_payload"] != package.deployment_snapshot_payload:
        reasons.append("DEPLOYMENT_SNAPSHOT_CHANGED")
    if ctx["scheduler_plan_snapshot_payload"] != package.scheduler_plan_snapshot_payload:
        reasons.append("SCHEDULER_PLAN_SNAPSHOT_CHANGED")
    if ctx["credential_snapshot_payload"] != package.credential_snapshot_payload:
        reasons.append("CREDENTIAL_SNAPSHOT_CHANGED")
    if ctx["risk_snapshot_payload"] != package.risk_snapshot_payload:
        reasons.append("RISK_SNAPSHOT_CHANGED")
    if ctx["trading_flag_snapshot_payload"] != package.trading_flag_snapshot_payload:
        reasons.append("TRADING_FLAG_SNAPSHOT_CHANGED")
    if ctx["kill_switch_snapshot_payload"] != package.kill_switch_snapshot_payload:
        reasons.append("KILL_SWITCH_SNAPSHOT_CHANGED")
    if ctx["recovery_snapshot_payload"] != package.recovery_snapshot_payload:
        reasons.append("RECOVERY_SNAPSHOT_CHANGED")
    if ctx["runtime_scope_snapshot_payload"] != package.runtime_scope_snapshot_payload:
        reasons.append("RUNTIME_SCOPE_SNAPSHOT_CHANGED")
    if ctx["deployment_scope_snapshot_payload"] != package.deployment_scope_snapshot_payload:
        reasons.append("DEPLOYMENT_SCOPE_SNAPSHOT_CHANGED")
    if ctx["history_snapshot_payload"] != package.history_snapshot_payload:
        reasons.append("HISTORY_SNAPSHOT_CHANGED")
    if ctx["audit_snapshot_payload"] != package.audit_snapshot_payload:
        reasons.append("AUDIT_SNAPSHOT_CHANGED")
    # § 위 15개 Snapshot 개별 비교로 포착되지 않는 변화(예: Account
    # is_active — 어떤 개별 Snapshot 컬럼에도 저장되지 않는 필드)까지
    # 안전하게 잡아내는 최종 방어선 — Blocking Code 목록 자체가 달라지면
    # 무조건 Stale로 판정한다.
    if sorted(ctx["blocking"]) != sorted(package.blocking_reason_codes):
        reasons.append("BLOCKING_REASON_CODES_CHANGED")

    existing_commit = session.scalar(
        select(StrategyOperationReadinessCommitEntity).where(
            StrategyOperationReadinessCommitEntity.runtime_scope_hash == package.runtime_scope_hash
        )
    )
    if existing_commit is not None:
        reasons.append("OPERATION_ALREADY_CERTIFIED")

    return len(reasons) > 0, reasons


def run_record_operation_readiness_decision(
    session: Session,
    strategy_definition_id: int,
    package_id: int,
    *,
    decision_type: str,
    reason_code: str,
    reason_text: str,
    checklist_confirmations: dict[str, bool],
    acknowledged_warnings: list[str],
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    package = session.get(StrategyOperationReadinessPackageEntity, package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise OperationReadinessError("PACKAGE_NOT_FOUND", f"Operation Readiness Package not found: {package_id}")
    if decision_type not in OPERATION_DECISION_TYPES:
        raise OperationReadinessError("INVALID_DECISION_TYPE", f"알 수 없는 Decision Type: {decision_type}")
    if reason_code not in REASON_CODES_BY_OPERATION_DECISION_TYPE.get(decision_type, frozenset()):
        raise OperationReadinessError("INVALID_REASON_CODE", f"{decision_type}에 허용되지 않는 reason_code입니다: {reason_code}")
    if not reason_text or not reason_text.strip():
        raise OperationReadinessError("REASON_TEXT_REQUIRED", "reason_text는 필수입니다.")

    existing_decision = session.scalar(
        select(StrategyOperationReadinessDecisionEntity).where(
            StrategyOperationReadinessDecisionEntity.operation_readiness_package_id == package_id
        )
    )
    if existing_decision is not None:
        same_request = (
            existing_decision.decision_type == decision_type
            and existing_decision.reason_code == reason_code
            and existing_decision.reason_text == reason_text
            and existing_decision.checklist_payload == checklist_confirmations
            and existing_decision.acknowledged_warnings_payload == acknowledged_warnings
        )
        if idempotency_key and existing_decision.idempotency_key == idempotency_key:
            if same_request:
                return _to_decision_dict(existing_decision, idempotent_replay=True)
            raise OperationReadinessError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")
        raise OperationReadinessError("DUPLICATE_OPERATION_READINESS_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다.")

    stale, stale_reasons = check_operation_readiness_package_staleness(session, package)
    if stale:
        raise OperationReadinessError("STALE_OPERATION_READINESS_PACKAGE", f"Operation Readiness Package가 Stale 상태입니다: {', '.join(stale_reasons)}")

    operation_ready = False
    if decision_type == OPERATION_DECISION_APPROVE:
        if package.readiness_status != READINESS_STATUS_READY:
            raise OperationReadinessError("PACKAGE_NOT_READY", f"Package 상태가 READY_FOR_OPERATION이 아닙니다(현재: {package.readiness_status}).")
        required_codes = {
            c["checklist_code"] for c in build_operation_readiness_checklist_template(package.execution_mode) if c["required"]
        }
        missing_confirmations = [c for c in required_codes if not checklist_confirmations.get(c)]
        if missing_confirmations:
            raise OperationReadinessError("INCOMPLETE_CHECKLIST", f"필수 Checklist 미확인 항목이 있습니다: {', '.join(sorted(missing_confirmations))}")
        if package.warning_reason_codes and "ALL" not in acknowledged_warnings:
            raise OperationReadinessError("WARNING_NOT_ACKNOWLEDGED", "모든 Warning을 확인(acknowledge)해야 합니다.")
        operation_ready = True

    same_actor_warning = actor == package.created_by
    decided_at = datetime.now(timezone.utc)
    decision_input_hash = compute_operation_decision_input_hash(
        operation_readiness_package_id=package_id, decision_type=decision_type, reason_code=reason_code,
        reason_text=reason_text, checklist_payload=checklist_confirmations,
        acknowledged_warnings_payload=acknowledged_warnings, decided_by=actor, decided_at=decided_at,
        algorithm_version=ALGORITHM_VERSION,
    )
    decision = StrategyOperationReadinessDecisionEntity(
        operation_readiness_package_id=package_id, strategy_definition_id=strategy_definition_id,
        runtime_scope_hash=package.runtime_scope_hash, decision_type=decision_type, reason_code=reason_code,
        reason_text=reason_text, checklist_payload=checklist_confirmations,
        acknowledged_warnings_payload=acknowledged_warnings, same_actor_warning=same_actor_warning,
        decided_by=actor, decided_at=decided_at, decision_input_hash=decision_input_hash,
        operation_ready=operation_ready, idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
    )
    try:
        session.add(decision)
        session.flush()
        _write_operation_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=package.runtime_scope_hash,
            deployment_id=None, event_type=_HISTORY_EVENT_BY_DECISION_TYPE[decision_type],
            previous_status=package.readiness_status, current_status=decision_type, source_type="DECISION",
            source_id=int(decision.operation_readiness_decision_id), actor=actor, occurred_at=decided_at,
            metadata_payload={"reason_code": reason_code},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = session.scalar(
            select(StrategyOperationReadinessDecisionEntity).where(
                StrategyOperationReadinessDecisionEntity.operation_readiness_package_id == package_id
            )
        )
        if conflict is not None:
            if idempotency_key and conflict.idempotency_key == idempotency_key:
                return _to_decision_dict(conflict, idempotent_replay=True)
            raise OperationReadinessError("DUPLICATE_OPERATION_READINESS_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다.") from None
        raise OperationReadinessError("DUPLICATE_OPERATION_READINESS_HISTORY", "동일 Decision에 대한 History가 이미 존재합니다.") from None
    session.refresh(decision)
    return _to_decision_dict(decision, idempotent_replay=False)


def _to_decision_dict(decision: StrategyOperationReadinessDecisionEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "operation_readiness_decision_id": int(decision.operation_readiness_decision_id),
        "operation_readiness_package_id": decision.operation_readiness_package_id,
        "strategy_definition_id": decision.strategy_definition_id,
        "runtime_scope_hash": decision.runtime_scope_hash,
        "decision_type": decision.decision_type,
        "reason_code": decision.reason_code,
        "reason_text": decision.reason_text,
        "checklist_payload": decision.checklist_payload,
        "acknowledged_warnings_payload": decision.acknowledged_warnings_payload,
        "same_actor_warning": decision.same_actor_warning,
        "decided_by": decision.decided_by,
        "decided_at": decision.decided_at,
        "decision_input_hash": decision.decision_input_hash,
        "operation_ready": decision.operation_ready,
        "idempotency_key": decision.idempotency_key,
        "algorithm_version": decision.algorithm_version,
        "idempotent_replay": idempotent_replay,
    }


def run_create_operation_readiness_commit(
    session: Session,
    strategy_definition_id: int,
    *,
    operation_readiness_package_id: int,
    operation_readiness_decision_id: int,
    deployment_readiness_commit_id: int,
    runtime_scope_hash: str,
    operation_input_hash: str,
    decision_input_hash: str,
    commit_reason: str,
    confirmation_text: str,
    acknowledge_same_actor_warning: bool = False,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not commit_reason or not commit_reason.strip():
        raise OperationReadinessError("COMMIT_REASON_REQUIRED", "commit_reason은 필수입니다.")
    if _normalize_confirmation_text(confirmation_text) != CONFIRMATION_TEXT_REQUIRED:
        raise OperationReadinessError("INVALID_CONFIRMATION", f"확인값이 올바르지 않습니다('{CONFIRMATION_TEXT_REQUIRED}'를 입력하세요).")

    definition = session.scalar(
        select(StrategyDefinitionEntity)
        .where(StrategyDefinitionEntity.strategy_id == strategy_definition_id)
        .with_for_update()
    )
    if definition is None or definition.deleted_at is not None:
        raise OperationReadinessError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    state = get_promotion_state(session, strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        raise OperationReadinessError("STRATEGY_NOT_ACTIVATED", f"Strategy Promotion State가 ACTIVATED가 아닙니다(현재: {state['current_status']}).")

    package = session.scalar(
        select(StrategyOperationReadinessPackageEntity)
        .where(StrategyOperationReadinessPackageEntity.operation_readiness_package_id == operation_readiness_package_id)
        .with_for_update()
    )
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise OperationReadinessError("PACKAGE_NOT_FOUND", f"Operation Readiness Package not found: {operation_readiness_package_id}")
    if package.runtime_scope_hash != runtime_scope_hash:
        raise OperationReadinessError("RUNTIME_SCOPE_MISMATCH", "요청한 runtime_scope_hash가 Package의 값과 일치하지 않습니다.")
    if package.deployment_readiness_commit_id != deployment_readiness_commit_id:
        raise OperationReadinessError("OWNERSHIP_MISMATCH", "요청한 deployment_readiness_commit_id가 Package의 값과 일치하지 않습니다.")

    decision = session.get(StrategyOperationReadinessDecisionEntity, operation_readiness_decision_id)
    if decision is None or decision.operation_readiness_package_id != operation_readiness_package_id:
        raise OperationReadinessError("DECISION_NOT_FOUND", f"Operation Readiness Decision not found: {operation_readiness_decision_id}")
    if decision.decision_type != OPERATION_DECISION_APPROVE:
        raise OperationReadinessError("DECISION_TYPE_MISMATCH", f"Decision Type이 APPROVE_OPERATION이 아닙니다(현재: {decision.decision_type}).")
    if not decision.operation_ready:
        raise OperationReadinessError("OPERATION_NOT_READY", "이 Decision은 operation_ready=false입니다.")
    if package.operation_input_hash != operation_input_hash:
        raise OperationReadinessError("READINESS_HASH_MISMATCH", "요청한 operation_input_hash가 Package의 값과 일치하지 않습니다.")
    if decision.decision_input_hash != decision_input_hash:
        raise OperationReadinessError("READINESS_HASH_MISMATCH", "요청한 decision_input_hash가 Decision의 값과 일치하지 않습니다.")
    if decision.same_actor_warning and not acknowledge_same_actor_warning:
        raise OperationReadinessError("SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED", "Package 생성자와 결정자가 동일합니다 — acknowledge_same_actor_warning=true가 필요합니다.")

    if idempotency_key:
        existing_by_key = session.scalar(
            select(StrategyOperationReadinessCommitEntity).where(
                StrategyOperationReadinessCommitEntity.idempotency_key == idempotency_key
            )
        )
        if existing_by_key is not None:
            same_request = (
                existing_by_key.strategy_definition_id == strategy_definition_id
                and existing_by_key.operation_readiness_package_id == operation_readiness_package_id
                and existing_by_key.operation_readiness_decision_id == operation_readiness_decision_id
                and existing_by_key.operation_input_hash == operation_input_hash
                and existing_by_key.decision_input_hash == decision_input_hash
            )
            if same_request:
                return _to_commit_dict(session, existing_by_key, idempotent_replay=True)
            raise OperationReadinessError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")

    existing_for_package = session.scalar(
        select(StrategyOperationReadinessCommitEntity).where(
            StrategyOperationReadinessCommitEntity.operation_readiness_package_id == operation_readiness_package_id
        )
    )
    if existing_for_package is not None:
        raise OperationReadinessError("OPERATION_ALREADY_CERTIFIED", f"Package #{operation_readiness_package_id}은 이미 Operation Commit이 존재합니다.")

    stale, stale_reasons = check_operation_readiness_package_staleness(session, package)
    if stale:
        raise OperationReadinessError("STALE_OPERATION_READINESS_PACKAGE", f"Operation Readiness Package가 Stale 상태입니다: {', '.join(stale_reasons)}")

    deploy_commit = session.get(StrategyDeploymentReadinessCommitEntity, deployment_readiness_commit_id)
    if deploy_commit is None:
        raise OperationReadinessError("DEPLOYMENT_READINESS_COMMIT_NOT_FOUND", f"Deployment Readiness Commit not found: {deployment_readiness_commit_id}")

    deployment = session.scalar(
        select(StrategyDeploymentEntity)
        .where(StrategyDeploymentEntity.strategy_deployment_id == package.strategy_deployment_id)
        .with_for_update()
    )
    if deployment is None or deployment.status_code != StrategyDeploymentStatus.READY_TO_START.value:
        raise OperationReadinessError("DEPLOYMENT_NOT_READY", "Deployment가 READY_TO_START 상태가 아닙니다.")

    committed_at = datetime.now(timezone.utc)
    confirmation_hash = _hash(_canonical_json({"confirmation_text": _normalize_confirmation_text(confirmation_text)}))
    operation_commit_hash = compute_operation_commit_hash(
        strategy_definition_id=strategy_definition_id, deployment_readiness_commit_id=deployment_readiness_commit_id,
        operation_readiness_package_id=operation_readiness_package_id,
        operation_readiness_decision_id=operation_readiness_decision_id, runtime_scope_hash=runtime_scope_hash,
        operation_input_hash=operation_input_hash, decision_input_hash=decision_input_hash, committed_by=actor,
        committed_at=committed_at, confirmation_hash=confirmation_hash, algorithm_version=ALGORITHM_VERSION,
    )

    try:
        # § STEP12-20 — 새 Deployment 행을 만들지 않는다. STEP12-19에서 만든
        # 바로 그 행의 `status_code`만 READY_TO_OPERATE로 전진시킨다.
        deployment.status_code = StrategyDeploymentStatus.READY_TO_OPERATE.value
        session.flush()

        readiness_commit = StrategyOperationReadinessCommitEntity(
            strategy_definition_id=strategy_definition_id, deployment_readiness_commit_id=deployment_readiness_commit_id,
            runtime_registration_commit_id=package.runtime_registration_commit_id,
            runtime_registry_id=package.runtime_registry_id, strategy_deployment_id=package.strategy_deployment_id,
            scheduler_plan_id=package.scheduler_plan_id, operation_readiness_package_id=operation_readiness_package_id,
            operation_readiness_decision_id=operation_readiness_decision_id, runtime_scope_hash=runtime_scope_hash,
            operation_input_hash=operation_input_hash, decision_input_hash=decision_input_hash,
            confirmation_hash=confirmation_hash, operation_commit_hash=operation_commit_hash, committed_by=actor,
            committed_at=committed_at, idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
        )
        session.add(readiness_commit)
        session.flush()

        _write_operation_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=runtime_scope_hash,
            deployment_id=int(deployment.strategy_deployment_id), event_type="READY_TO_OPERATE",
            previous_status=decision.decision_type, current_status=StrategyDeploymentStatus.READY_TO_OPERATE.value,
            source_type="COMMIT", source_id=int(readiness_commit.operation_readiness_commit_id), actor=actor,
            occurred_at=committed_at, metadata_payload={"operation_commit_hash": operation_commit_hash},
        )

        # § STEP12-19 Carry-forward(3.1) 원칙과 동일 — Audit은 add+flush만
        # 수행하고, 이 함수가 최상위에서 정확히 한 번 commit한다.
        AuditLogService(session).record(
            event_type="READY_TO_OPERATE", actor=actor, strategy_id=str(strategy_definition_id),
            detail={
                "operation_readiness_commit_id": int(readiness_commit.operation_readiness_commit_id),
                "strategy_deployment_id": package.strategy_deployment_id,
                "operation_commit_hash": operation_commit_hash, "runtime_scope_hash": runtime_scope_hash,
            },
            auto_commit=False,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyOperationReadinessCommitEntity).where(
                    StrategyOperationReadinessCommitEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_commit_dict(session, conflict, idempotent_replay=True)
        package_conflict = session.scalar(
            select(StrategyOperationReadinessCommitEntity).where(
                StrategyOperationReadinessCommitEntity.operation_readiness_package_id == operation_readiness_package_id
            )
        )
        if package_conflict is not None:
            raise OperationReadinessError("OPERATION_ALREADY_CERTIFIED", f"Package #{operation_readiness_package_id}은 이미 Operation Commit이 존재합니다.") from None
        scope_conflict = session.scalar(
            select(StrategyOperationReadinessCommitEntity).where(
                StrategyOperationReadinessCommitEntity.runtime_scope_hash == runtime_scope_hash
            )
        )
        if scope_conflict is not None:
            raise OperationReadinessError("OPERATION_ALREADY_CERTIFIED", "동일 Runtime Scope에 이미 Operation Commit이 존재합니다.") from None
        raise OperationReadinessError("DUPLICATE_OPERATION_READINESS_COMMIT", "동일 Operation Readiness Commit이 이미 존재합니다.") from None

    session.refresh(readiness_commit)
    return _to_commit_dict(session, readiness_commit, idempotent_replay=False)


def _to_commit_dict(
    session: Session, commit: StrategyOperationReadinessCommitEntity, *, idempotent_replay: bool
) -> dict[str, Any]:
    deployment = session.get(StrategyDeploymentEntity, commit.strategy_deployment_id)
    return {
        "operation_readiness_commit_id": int(commit.operation_readiness_commit_id),
        "strategy_definition_id": commit.strategy_definition_id,
        "deployment_readiness_commit_id": commit.deployment_readiness_commit_id,
        "runtime_registration_commit_id": commit.runtime_registration_commit_id,
        "runtime_registry_id": commit.runtime_registry_id,
        "strategy_deployment_id": commit.strategy_deployment_id,
        "scheduler_plan_id": commit.scheduler_plan_id,
        "operation_readiness_package_id": commit.operation_readiness_package_id,
        "operation_readiness_decision_id": commit.operation_readiness_decision_id,
        "runtime_scope_hash": commit.runtime_scope_hash,
        "operation_commit_hash": commit.operation_commit_hash,
        "committed_by": commit.committed_by,
        "committed_at": commit.committed_at,
        "deployment_status": deployment.status_code if deployment is not None else None,
        "next_action": "REVIEW_START_APPROVAL",
        "idempotent_replay": idempotent_replay,
    }


def get_operation_readiness_package(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = session.get(StrategyOperationReadinessPackageEntity, package_id)
    if package is None:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Package not found: {package_id}")
    if strategy_definition_id is not None and package.strategy_definition_id != strategy_definition_id:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Package not found: {package_id}")
    result = _to_package_dict(package, idempotent_replay=False)
    stale, stale_reasons = check_operation_readiness_package_staleness(session, package)
    commit = session.scalar(
        select(StrategyOperationReadinessCommitEntity).where(
            StrategyOperationReadinessCommitEntity.operation_readiness_package_id == package_id
        )
    )
    decision = session.scalar(
        select(StrategyOperationReadinessDecisionEntity).where(
            StrategyOperationReadinessDecisionEntity.operation_readiness_package_id == package_id
        )
    )
    if commit is not None:
        current_effective_status = "READY_TO_OPERATE"
    elif stale:
        current_effective_status = "STALE"
    elif decision is not None:
        current_effective_status = "DECIDED"
    else:
        current_effective_status = package.readiness_status
    result.update(
        {
            "created_readiness_status": package.readiness_status,
            "current_effective_status": current_effective_status,
            "stale": stale, "stale_reasons": stale_reasons, "decided": decision is not None,
            "certified": commit is not None,
        }
    )
    return result


def list_operation_readiness_packages(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyOperationReadinessPackageEntity)
        .where(StrategyOperationReadinessPackageEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyOperationReadinessPackageEntity.operation_readiness_package_id.desc())
    )
    return [_to_package_dict(r, idempotent_replay=False) for r in rows]


def get_operation_readiness_package_checklist(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyOperationReadinessPackageEntity, package_id)
    if package is None:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Package not found: {package_id}")
    decision = session.scalar(
        select(StrategyOperationReadinessDecisionEntity).where(
            StrategyOperationReadinessDecisionEntity.operation_readiness_package_id == package_id
        )
    )
    return {
        "operation_readiness_package_id": package_id,
        "checklist_template": build_operation_readiness_checklist_template(package.execution_mode),
        "checklist_confirmations": decision.checklist_payload if decision is not None else {},
    }


def get_operation_readiness_package_staleness(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyOperationReadinessPackageEntity, package_id)
    if package is None:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Package not found: {package_id}")
    stale, reasons = check_operation_readiness_package_staleness(session, package)
    return {"operation_readiness_package_id": package_id, "stale": stale, "reasons": reasons}


def get_operation_readiness_decision(session: Session, package_id: int) -> dict[str, Any] | None:
    decision = session.scalar(
        select(StrategyOperationReadinessDecisionEntity).where(
            StrategyOperationReadinessDecisionEntity.operation_readiness_package_id == package_id
        )
    )
    if decision is None:
        return None
    return _to_decision_dict(decision, idempotent_replay=False)


def get_operation_readiness_commit(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyOperationReadinessCommitEntity, commit_id)
    if commit is None:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Commit not found: {commit_id}")
    return _to_commit_dict(session, commit, idempotent_replay=False)


def list_operation_readiness_commits(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyOperationReadinessCommitEntity)
        .where(StrategyOperationReadinessCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyOperationReadinessCommitEntity.operation_readiness_commit_id.desc())
    )
    return [_to_commit_dict(session, r, idempotent_replay=False) for r in rows]


def get_operation_readiness_commit_provenance(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyOperationReadinessCommitEntity, commit_id)
    if commit is None:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Commit not found: {commit_id}")
    return {
        "operation_readiness_commit_id": int(commit.operation_readiness_commit_id),
        "runtime_scope_hash": commit.runtime_scope_hash,
        "operation_commit_hash": commit.operation_commit_hash,
        "deployment_readiness_commit_id": commit.deployment_readiness_commit_id,
    }


def get_operation_readiness_status(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    commits = session.scalars(
        select(StrategyOperationReadinessCommitEntity)
        .where(StrategyOperationReadinessCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyOperationReadinessCommitEntity.committed_at.desc())
    ).all()
    state = get_promotion_state(session, strategy_definition_id)
    if not commits:
        return {
            "strategy_definition_id": strategy_definition_id, "certified": False, "total_certifications": 0,
            "operation_readiness_commit_id": None, "strategy_promotion_status": state["current_status"],
            "next_action": "REVIEW_OPERATION_READINESS" if state["current_status"] == PROMOTION_STATE_ACTIVATED else "REVIEW_ACTIVATION",
        }
    result = _to_commit_dict(session, commits[0], idempotent_replay=False)
    result["certified"] = True
    result["total_certifications"] = len(commits)
    result["strategy_definition_id"] = strategy_definition_id
    result["strategy_promotion_status"] = state["current_status"]
    return result


def get_operation_readiness_history(
    session: Session, strategy_definition_id: int, *, runtime_scope_hash: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(StrategyOperationReadinessHistoryEntity).where(
        StrategyOperationReadinessHistoryEntity.strategy_definition_id == strategy_definition_id
    )
    if runtime_scope_hash is not None:
        stmt = stmt.where(StrategyOperationReadinessHistoryEntity.runtime_scope_hash == runtime_scope_hash)
    rows = session.scalars(
        stmt.order_by(
            StrategyOperationReadinessHistoryEntity.occurred_at.asc(),
            StrategyOperationReadinessHistoryEntity.history_id.asc(),
        )
    )
    return [_to_history_dict(h) for h in rows]


def get_operation_readiness_certification(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyOperationReadinessPackageEntity, package_id)
    if package is None:
        raise OperationReadinessError("NOT_FOUND", f"Operation Readiness Package not found: {package_id}")
    all_passed = all(area["passed"] for area in package.certification_areas_payload.values())
    return {
        "operation_readiness_package_id": package_id,
        "certification_areas": package.certification_areas_payload,
        "all_areas_passed": all_passed,
        "readiness_status": package.readiness_status,
    }
