"""STEP 12-19 — Deployment Readiness Review Package / Decision / Commit.

REGISTERED(비실행, `enabled=false`/`running=false`) 상태인 Runtime
Registry를 대상으로 계좌/시장/브로커/리스크/운영 준비 상태를 재검증한
뒤, 관리자의 명시적 Deployment Commit으로 "실행 직전까지 구성이 확정된"
`READY_TO_START` 상태를 만든다. 기존 `trading.strategy_deployment`(§
STEP31-1 `PaperStrategyDeploymentService`가 쓰는 진짜 실행 테이블)를
그대로 재사용하되, 그 테이블의 `status_code="ACTIVE"`는 이미 "실제
활성/실행 중"이라는 의미로 확립돼 있으므로 절대 재사용하지 않는다 —
`StrategyDeploymentStatus.READY_TO_START`(신규 추가값)만 사용한다.
Scheduler Plan(`strategy_runtime_scheduler_plan`)은 `enabled=false`,
`registered_to_scheduler=false`, `scheduler_job_id=NULL`로만 저장되는
"미래 실행을 위한 계획"이며 실제 APScheduler Job Store와 무관하다.

Runtime 시작, Scheduler 실제 등록, Broker 연결/로그인, 실시간 시세 구독,
Signal 계산, 주문 생성/전송, Paper/Live Trading 시작은 이 STEP 어디에서도
수행하지 않는다.

재사용(중복 생성 금지 확인):
- 계좌/Credential/Risk/운영 검증은 STEP12-17 `activation.py`의 기존
  헬퍼(`_resolve_account`, `_account_snapshot_payload`,
  `_broker_snapshot_payload`, `_risk_snapshot_payload`,
  `_operational_snapshot_payload`)를 그대로 가져와 쓴다.
- Promotion State 재검증/잠금은 `promotion_commit.py`의 기존
  `_ensure_and_lock_promotion_state()`/`get_promotion_state()`를
  재사용한다.
- 기존 `trading.strategy_deployment`/`StrategyDeploymentStatus`를 그대로
  재사용한다(신규 Deployment 테이블 없음). `strategy_performance_run_id`
  NOT NULL 제약은 STEP12-x 파이프라인과 무관한 STEP7-x 개념이므로
  Migration에서 NULL 허용으로 최소 변경했다(§ 완료보고 참고).
- Market 시간대/영업 시간 기본값은 `risk_engine/runtime.py`의 기존
  `realtime_risk_policy.trading_start_time/trading_end_time`(09:00/15:20)
  과 `scheduler/market_session.py`의 기존 `Asia/Seoul` 관례를 그대로
  재사용한다(임의 하드코딩 없음).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft_approval.activation import (
    _account_snapshot_payload,
    _broker_snapshot_payload,
    _market_family,
    _operational_snapshot_payload,
    _resolve_account,
    _risk_snapshot_payload,
)
from stock_platform.ai.strategy_draft_approval.activation_entities import (
    ACCOUNT_KIND_USER_BROKER,
    EXECUTION_MODE_LIVE,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.decision_package import _STALE_LIFECYCLE_STATUSES
from stock_platform.ai.strategy_draft_approval.deployment_readiness_entities import (
    DEPLOYMENT_DECISION_APPROVE,
    DEPLOYMENT_DECISION_TYPES,
    READINESS_STATUS_BLOCKED,
    READINESS_STATUS_READY,
    SCHEDULER_TYPE_INTERVAL,
    SCHEDULER_TYPE_MARKET_SESSION,
    StrategyDeploymentReadinessCommitEntity,
    StrategyDeploymentReadinessDecisionEntity,
    StrategyDeploymentReadinessHistoryEntity,
    StrategyDeploymentReadinessPackageEntity,
    StrategyRuntimeSchedulerPlanEntity,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    _ensure_and_lock_promotion_state,
    get_promotion_state,
)
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import PROMOTION_STATE_ACTIVATED
from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
    StrategyRuntimeRegistrationCommitEntity,
    StrategyRuntimeRegistryEntity,
)
from stock_platform.api.deps_admin import AuditLogService
from stock_platform.risk_engine.runtime import realtime_risk_policy
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity
from stock_platform.strategy_deployment.models import StrategyDeploymentStatus

ALGORITHM_VERSION = "1.0.0"
CONFIRMATION_TEXT_REQUIRED = "DEPLOY"

_HISTORY_EVENT_BY_DECISION_TYPE: dict[str, str] = {
    "APPROVE_DEPLOYMENT": "DEPLOYMENT_APPROVED",
    "REQUEST_DEPLOYMENT_CHANGES": "DEPLOYMENT_CHANGES_REQUESTED",
    "REJECT_DEPLOYMENT": "DEPLOYMENT_REJECTED",
}

REASON_CODES_BY_DEPLOYMENT_DECISION_TYPE: dict[str, frozenset[str]] = {
    "APPROVE_DEPLOYMENT": frozenset(
        {"ACTIVATION_REQUIREMENTS_VERIFIED", "ACCOUNT_AND_RISK_REVIEW_COMPLETED", "READY_FOR_DEPLOYMENT_COMMIT"}
    ),
    "REQUEST_DEPLOYMENT_CHANGES": frozenset(
        {"ACCOUNT_CONFIGURATION_REQUIRED", "RISK_LIMIT_ADJUSTMENT_REQUIRED", "SCHEDULER_CONFIGURATION_REVIEW_REQUIRED"}
    ),
    "REJECT_DEPLOYMENT": frozenset(
        {"ACCOUNT_NOT_ELIGIBLE", "UNACCEPTABLE_RISK", "POLICY_VIOLATION", "STRATEGY_NOT_ELIGIBLE", "DUPLICATE_DEPLOYMENT"}
    ),
}


class DeploymentReadinessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _normalize_confirmation_text(value: str) -> str:
    return (value or "").strip().upper()


def _seconds_since_midnight(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def build_deployment_checklist_template(execution_mode: str) -> list[dict[str, Any]]:
    items = [
        {"checklist_code": "RUNTIME_REGISTRATION_COMMIT_CONFIRMED", "required": True, "question": "Runtime Registration Commit을 확인했는가"},
        {"checklist_code": "RUNTIME_REGISTRY_CONFIRMED", "required": True, "question": "Runtime Registry를 확인했는가"},
        {"checklist_code": "RUNTIME_SCOPE_CONFIRMED", "required": True, "question": "Runtime Scope를 확인했는가"},
        {"checklist_code": "RUNTIME_ENABLED_FALSE_CONFIRMED", "required": True, "question": "Runtime enabled=false를 확인했는가"},
        {"checklist_code": "RUNTIME_RUNNING_FALSE_CONFIRMED", "required": True, "question": "Runtime running=false를 확인했는가"},
        {"checklist_code": "STRATEGY_ACTIVATED_CONFIRMED", "required": True, "question": "Strategy가 ACTIVATED 상태임을 확인했는가"},
        {"checklist_code": "STRATEGY_VERSION_CONFIRMED", "required": True, "question": "Strategy Version을 확인했는가"},
        {"checklist_code": "ACCOUNT_OWNERSHIP_CONFIRMED", "required": True, "question": "Account 소유권을 확인했는가"},
        {"checklist_code": "ACCOUNT_STATUS_CONFIRMED", "required": True, "question": "Account 상태를 확인했는가"},
        {"checklist_code": "MARKET_BROKER_CONFIRMED", "required": True, "question": "Market/Broker를 확인했는가"},
        {"checklist_code": "RISK_SNAPSHOT_CONFIRMED", "required": True, "question": "Risk Snapshot을 확인했는가"},
        {"checklist_code": "KILL_SWITCH_INACTIVE_CONFIRMED", "required": True, "question": "Kill Switch 비활성을 확인했는가"},
        {"checklist_code": "ACCOUNT_PAUSE_CONFIRMED", "required": True, "question": "Account Pause 없음을 확인했는가"},
        {"checklist_code": "RECOVERY_CONFLICT_CONFIRMED", "required": True, "question": "Recovery Conflict 없음을 확인했는가"},
        {"checklist_code": "NO_DEPLOYMENT_CONFLICT_CONFIRMED", "required": True, "question": "기존 Deployment 충돌이 없음을 확인했는가"},
        {"checklist_code": "SCHEDULER_PLAN_CONFIRMED", "required": True, "question": "Scheduler Plan 설정을 확인했는가"},
        {"checklist_code": "SCHEDULER_PLAN_DISABLED_CONFIRMED", "required": True, "question": "Scheduler Plan enabled=false를 확인했는가"},
        {"checklist_code": "SCHEDULER_NOT_REGISTERED_CONFIRMED", "required": True, "question": "Scheduler에 실제 Job이 등록되지 않음을 확인했는가"},
        {"checklist_code": "BROKER_NOT_CONNECTED_CONFIRMED", "required": True, "question": "Broker 미연결을 확인했는가"},
        {"checklist_code": "ORDER_NOT_ALLOWED_CONFIRMED", "required": True, "question": "주문 불가 상태를 확인했는가"},
        {"checklist_code": "NOT_AUTO_TRADING_START_CONFIRMED", "required": True, "question": "Deployment Commit이 자동매매 시작이 아님을 확인했는가"},
    ]
    if execution_mode == EXECUTION_MODE_LIVE:
        items.extend(
            [
                {"checklist_code": "CREDENTIAL_VERIFIED_CONFIRMED", "required": True, "question": "Credential Verified를 확인했는가"},
                {"checklist_code": "CREDENTIAL_VERSION_CONFIRMED", "required": True, "question": "Credential Version을 확인했는가"},
                {"checklist_code": "EXPLICIT_RISK_CONFIRMED", "required": True, "question": "Explicit Risk 설정을 확인했는가"},
                {"checklist_code": "LIVE_ORDER_FLAG_CONFIRMED", "required": True, "question": "Live Order Flag를 확인했는가"},
                {"checklist_code": "INVESTMENT_LIMIT_CONFIRMED", "required": True, "question": "투자 한도를 확인했는가"},
                {"checklist_code": "LOSS_LIMIT_CONFIRMED", "required": True, "question": "손실 한도를 확인했는가"},
                {"checklist_code": "LIVE_CAPITAL_RISK_ACKNOWLEDGED", "required": True, "question": "실제 자금 위험을 인지했는가"},
                {"checklist_code": "START_APPROVAL_SEPARATE_CONFIRMED", "required": True, "question": "START 전 최종 운영 승인이 별도임을 확인했는가"},
            ]
        )
    else:
        items.extend(
            [
                {"checklist_code": "NO_LIVE_CREDENTIAL_CONFIRMED", "required": True, "question": "실계좌 Credential을 사용하지 않음을 확인했는가"},
                {"checklist_code": "SAFE_PAPER_RISK_CONFIRMED", "required": True, "question": "SAFE_PAPER_DEFAULT 또는 명시적 Risk를 확인했는가"},
                {"checklist_code": "PAPER_RUNTIME_NOT_STARTED_CONFIRMED", "required": True, "question": "Paper Runtime이 아직 시작되지 않음을 확인했는가"},
            ]
        )
    return items


def compute_deployment_input_hash(
    *,
    strategy_definition_id: int,
    runtime_registration_commit_id: int,
    runtime_registry_id: int,
    runtime_scope_hash: str,
    deployment_snapshot_payload: dict[str, Any],
    runtime_snapshot_payload: dict[str, Any],
    scheduler_plan_snapshot_payload: dict[str, Any],
    account_snapshot_payload: dict[str, Any],
    credential_snapshot_payload: dict[str, Any],
    risk_snapshot_payload: dict[str, Any],
    operational_snapshot_payload: dict[str, Any],
    recovery_snapshot_payload: dict[str, Any],
    blocking_reason_codes: list[str],
    warning_reason_codes: list[str],
    missing_requirement_codes: list[str],
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "runtime_registration_commit_id": runtime_registration_commit_id,
        "runtime_registry_id": runtime_registry_id, "runtime_scope_hash": runtime_scope_hash,
        "deployment_snapshot_payload": deployment_snapshot_payload, "runtime_snapshot_payload": runtime_snapshot_payload,
        "scheduler_plan_snapshot_payload": scheduler_plan_snapshot_payload,
        "account_snapshot_payload": account_snapshot_payload, "credential_snapshot_payload": credential_snapshot_payload,
        "risk_snapshot_payload": risk_snapshot_payload, "operational_snapshot_payload": operational_snapshot_payload,
        "recovery_snapshot_payload": recovery_snapshot_payload,
        "blocking_reason_codes": sorted(blocking_reason_codes), "warning_reason_codes": sorted(warning_reason_codes),
        "missing_requirement_codes": sorted(missing_requirement_codes), "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_deployment_decision_input_hash(
    *,
    deployment_readiness_package_id: int,
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
        "deployment_readiness_package_id": deployment_readiness_package_id, "decision_type": decision_type,
        "reason_code": reason_code, "reason_text": reason_text, "checklist_payload": checklist_payload,
        "acknowledged_warnings_payload": sorted(acknowledged_warnings_payload), "decided_by": decided_by,
        "decided_at": decided_at.isoformat(), "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_scheduler_plan_hash(
    *,
    runtime_scope_hash: str,
    scheduler_type: str,
    timezone_name: str,
    market_calendar: str,
    cron_expression: str | None,
    interval_seconds: int | None,
    start_policy: str,
    stop_policy: str,
    market_open_offset: int | None,
    market_close_offset: int | None,
    holiday_policy: str,
    plan_version: int,
    algorithm_version: str,
) -> str:
    canonical = {
        "runtime_scope_hash": runtime_scope_hash, "scheduler_type": scheduler_type, "timezone": timezone_name,
        "market_calendar": market_calendar, "cron_expression": cron_expression, "interval_seconds": interval_seconds,
        "start_policy": start_policy, "stop_policy": stop_policy, "market_open_offset": market_open_offset,
        "market_close_offset": market_close_offset, "holiday_policy": holiday_policy, "plan_version": plan_version,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_deployment_commit_hash(
    *,
    strategy_definition_id: int,
    runtime_registration_commit_id: int,
    runtime_registry_id: int,
    deployment_readiness_package_id: int,
    deployment_readiness_decision_id: int,
    runtime_scope_hash: str,
    strategy_deployment_id: int,
    scheduler_plan_id: int,
    deployment_input_hash: str,
    decision_input_hash: str,
    scheduler_plan_hash: str,
    committed_by: str,
    committed_at: datetime,
    confirmation_hash: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "runtime_registration_commit_id": runtime_registration_commit_id,
        "runtime_registry_id": runtime_registry_id, "deployment_readiness_package_id": deployment_readiness_package_id,
        "deployment_readiness_decision_id": deployment_readiness_decision_id, "runtime_scope_hash": runtime_scope_hash,
        "strategy_deployment_id": strategy_deployment_id, "scheduler_plan_id": scheduler_plan_id,
        "deployment_input_hash": deployment_input_hash, "decision_input_hash": decision_input_hash,
        "scheduler_plan_hash": scheduler_plan_hash, "committed_by": committed_by,
        "committed_at": committed_at.isoformat(), "confirmation_hash": confirmation_hash,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def _build_scheduler_plan_defaults(*, market_type: str) -> dict[str, Any]:
    """§ 명세 §8 — 임의의 운영 시간을 새로 하드코딩하지 않고 기존
    `realtime_risk_policy.trading_start_time/trading_end_time`(09:00/
    15:20)과 `Asia/Seoul` 관례(§ scheduler/market_session.py)를 그대로
    재사용한다. CRYPTO(24시간 시장)는 시장 시간 개념이 없으므로 주기
    실행(INTERVAL) 정책을 쓴다."""
    if _market_family(market_type) == "CRYPTO":
        return {
            "scheduler_type": SCHEDULER_TYPE_INTERVAL, "timezone": "UTC", "market_calendar": "24_7",
            "cron_expression": None, "interval_seconds": 60, "market_open_offset": None, "market_close_offset": None,
            "holiday_policy": "NONE",
        }
    return {
        "scheduler_type": SCHEDULER_TYPE_MARKET_SESSION, "timezone": "Asia/Seoul", "market_calendar": "KRX",
        "cron_expression": None, "interval_seconds": None,
        "market_open_offset": _seconds_since_midnight(realtime_risk_policy.trading_start_time),
        "market_close_offset": _seconds_since_midnight(realtime_risk_policy.trading_end_time),
        "holiday_policy": "KRX_HOLIDAY_CALENDAR",
    }


def _write_deployment_history(
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
) -> StrategyDeploymentReadinessHistoryEntity:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "runtime_scope_hash": runtime_scope_hash,
        "event_type": event_type, "previous_status": previous_status, "current_status": current_status,
        "source_type": source_type, "source_id": source_id, "actor_id": actor, "occurred_at": occurred_at.isoformat(),
        "algorithm_version": ALGORITHM_VERSION,
    }
    event_hash = _hash(_canonical_json(canonical))
    history = StrategyDeploymentReadinessHistoryEntity(
        strategy_definition_id=strategy_definition_id, runtime_scope_hash=runtime_scope_hash,
        deployment_id=deployment_id, event_type=event_type, previous_status=previous_status,
        current_status=current_status, source_type=source_type, source_id=source_id, actor_id=actor,
        metadata_payload=metadata_payload, event_hash=event_hash, occurred_at=occurred_at,
    )
    session.add(history)
    session.flush()
    return history


def _to_history_dict(history: StrategyDeploymentReadinessHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(history.history_id), "strategy_definition_id": history.strategy_definition_id,
        "runtime_scope_hash": history.runtime_scope_hash, "deployment_id": history.deployment_id,
        "event_type": history.event_type, "previous_status": history.previous_status,
        "current_status": history.current_status, "source_type": history.source_type, "source_id": history.source_id,
        "actor_id": history.actor_id, "metadata_payload": history.metadata_payload, "event_hash": history.event_hash,
        "occurred_at": history.occurred_at,
    }


def _validate_registration_prerequisites(
    session: Session, *, definition: StrategyDefinitionEntity, strategy_definition_id: int,
    runtime_registration_commit_id: int, runtime_registry_id: int,
) -> tuple[list[str], StrategyRuntimeRegistrationCommitEntity | None, StrategyRuntimeRegistryEntity | None, dict[str, Any]]:
    blocking: list[str] = []
    state = get_promotion_state(session, strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        blocking.append("STRATEGY_NOT_ACTIVATED")

    commit = session.get(StrategyRuntimeRegistrationCommitEntity, runtime_registration_commit_id)
    if commit is None or commit.strategy_definition_id != strategy_definition_id:
        blocking.append("RUNTIME_REGISTRATION_COMMIT_NOT_FOUND")
        return blocking, None, None, {}

    registry = session.get(StrategyRuntimeRegistryEntity, runtime_registry_id)
    if registry is None or registry.runtime_registration_commit_id != commit.runtime_registration_commit_id:
        blocking.append("RUNTIME_REGISTRY_NOT_FOUND")
        return blocking, commit, None, {}
    if registry.runtime_scope_hash != commit.runtime_scope_hash:
        blocking.append("RUNTIME_SCOPE_MISMATCH")
    if registry.enabled:
        blocking.append("RUNTIME_ALREADY_ENABLED")
    if registry.running:
        blocking.append("RUNTIME_ALREADY_RUNNING")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            blocking.append("STRATEGY_NOT_ACTIVATED")
    if definition.definition_version != commit.strategy_version:
        blocking.append("STRATEGY_VERSION_MISMATCH")

    runtime_snapshot = {
        "runtime_registration_commit_id": int(commit.runtime_registration_commit_id),
        "registration_commit_hash": commit.registration_commit_hash,
        "runtime_registry_id": int(registry.runtime_registry_id),
        "registry_status": registry.status, "registry_enabled": bool(registry.enabled),
        "registry_running": bool(registry.running), "runtime_scope_hash": commit.runtime_scope_hash,
        "strategy_promotion_status": state["current_status"], "promotion_state_version": state["status_version"],
        "promotion_state_hash": state["state_hash"],
    }
    return blocking, commit, registry, runtime_snapshot


def _run_deployment_validations(
    session: Session, *, definition: StrategyDefinitionEntity, strategy_definition_id: int,
    commit: StrategyRuntimeRegistrationCommitEntity,
) -> dict[str, Any]:
    blocking: list[str] = []
    warning: list[str] = []
    missing: list[str] = []

    account, account_blocking = _resolve_account(
        session, target_account_kind=commit.account_kind,
        target_user_broker_account_id=commit.target_user_broker_account_id,
        target_paper_account_id=commit.target_paper_account_id,
    )
    blocking.extend(account_blocking)

    if (
        account is not None
        and definition.owner_type == "USER"
        and definition.user_id is not None
        and account.user_id is not None
        and int(account.user_id) != int(definition.user_id)
    ):
        blocking.append("ACCOUNT_OWNERSHIP_MISMATCH")

    broker_snapshot, broker_blocking, broker_warning = _broker_snapshot_payload(
        session, account=account, target_account_kind=commit.account_kind, requested_execution_mode=commit.execution_mode,
    )
    blocking.extend(broker_blocking)
    warning.extend(broker_warning)

    risk_snapshot, risk_blocking, risk_warning = _risk_snapshot_payload(
        session, account=account, target_account_kind=commit.account_kind, requested_execution_mode=commit.execution_mode,
    )
    blocking.extend(risk_blocking)
    warning.extend(risk_warning)
    if commit.execution_mode == EXECUTION_MODE_LIVE and not risk_snapshot.get("effective_risk_explicit"):
        blocking.append("EXPLICIT_LIVE_RISK_REQUIRED")

    operational_snapshot, op_blocking, op_warning = _operational_snapshot_payload(
        session, strategy_definition_id=strategy_definition_id, account=account, target_account_kind=commit.account_kind,
    )
    blocking.extend(op_blocking)
    warning.extend(op_warning)

    # § Deployment Conflict — 동일 Runtime Scope에 이미 READY_TO_START
    # Deployment가 있으면 차단(UNIQUE로도 보호되지만 Package 생성 시점에
    # 미리 알려준다). Registry는 Scope Hash와 1:1이므로 별도 검사가
    # 필요 없다.
    existing_deployment = session.scalar(
        select(StrategyDeploymentReadinessCommitEntity).where(
            StrategyDeploymentReadinessCommitEntity.runtime_scope_hash == commit.runtime_scope_hash
        )
    )
    if existing_deployment is not None:
        blocking.append("DEPLOYMENT_ALREADY_EXISTS")

    existing_scheduler_plan = session.scalar(
        select(StrategyRuntimeSchedulerPlanEntity).where(
            StrategyRuntimeSchedulerPlanEntity.runtime_scope_hash == commit.runtime_scope_hash
        )
    )
    if existing_scheduler_plan is not None:
        blocking.append("SCHEDULER_PLAN_ALREADY_EXISTS")

    link_exists = False
    if account is not None:
        stmt = select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.strategy_id == strategy_definition_id,
        )
        if commit.account_kind == ACCOUNT_KIND_USER_BROKER:
            stmt = stmt.where(AccountStrategyLinkEntity.user_broker_account_id == commit.target_user_broker_account_id)
        else:
            stmt = stmt.where(AccountStrategyLinkEntity.paper_account_id == commit.target_paper_account_id)
        link_exists = session.scalar(stmt.limit(1)) is not None

    account_snapshot = _account_snapshot_payload(account, kind=commit.account_kind)
    recovery_snapshot = {
        "recovery_paused": operational_snapshot.get("recovery_paused"),
        "kill_switch_active": operational_snapshot.get("kill_switch_active"),
    }

    scheduler_defaults = _build_scheduler_plan_defaults(market_type=commit.market_type)
    scheduler_plan_snapshot = {**scheduler_defaults, "enabled": False, "registered_to_scheduler": False}

    return {
        "blocking": sorted(set(blocking)),
        "warning": sorted(set(warning) - set(blocking)),
        "missing": sorted(set(missing)),
        "account": account,
        "account_strategy_link_exists": link_exists,
        "account_snapshot_payload": account_snapshot,
        "broker_snapshot_payload": broker_snapshot,
        "risk_snapshot_payload": risk_snapshot,
        "operational_snapshot_payload": operational_snapshot,
        "recovery_snapshot_payload": recovery_snapshot,
        "scheduler_plan_snapshot_payload": scheduler_plan_snapshot,
    }


def run_create_deployment_readiness_package(
    session: Session,
    strategy_definition_id: int,
    *,
    runtime_registration_commit_id: int,
    runtime_registry_id: int,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    definition = session.get(StrategyDefinitionEntity, strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        raise DeploymentReadinessError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    if idempotency_key:
        existing = session.scalar(
            select(StrategyDeploymentReadinessPackageEntity).where(
                StrategyDeploymentReadinessPackageEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            same_request = (
                existing.strategy_definition_id == strategy_definition_id
                and existing.runtime_registration_commit_id == runtime_registration_commit_id
                and existing.runtime_registry_id == runtime_registry_id
            )
            if same_request:
                return _to_package_dict(existing, idempotent_replay=True)
            raise DeploymentReadinessError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")

    registration_blocking, commit, registry, runtime_snapshot = _validate_registration_prerequisites(
        session, definition=definition, strategy_definition_id=strategy_definition_id,
        runtime_registration_commit_id=runtime_registration_commit_id, runtime_registry_id=runtime_registry_id,
    )
    if commit is None:
        raise DeploymentReadinessError("RUNTIME_REGISTRATION_COMMIT_NOT_FOUND", f"Runtime Registration Commit not found: {runtime_registration_commit_id}")
    if registry is None:
        raise DeploymentReadinessError("RUNTIME_REGISTRY_NOT_FOUND", f"Runtime Registry not found: {runtime_registry_id}")

    validation = _run_deployment_validations(
        session, definition=definition, strategy_definition_id=strategy_definition_id, commit=commit,
    )
    blocking = sorted(set(registration_blocking) | set(validation["blocking"]))

    deployment_snapshot = {
        "strategy_definition_id": strategy_definition_id, "definition_version": definition.definition_version,
        "definition_hash": definition.definition_hash, "executable_hash": commit.credential_snapshot_payload.get("key_version")
        if False else None,
        "market_type": commit.market_type, "broker_code": commit.broker_code, "execution_mode": commit.execution_mode,
        "account_kind": commit.account_kind,
    }

    created_at = datetime.now(timezone.utc)
    readiness_status = READINESS_STATUS_BLOCKED if blocking else READINESS_STATUS_READY

    deployment_input_hash = compute_deployment_input_hash(
        strategy_definition_id=strategy_definition_id, runtime_registration_commit_id=runtime_registration_commit_id,
        runtime_registry_id=runtime_registry_id, runtime_scope_hash=commit.runtime_scope_hash,
        deployment_snapshot_payload=deployment_snapshot, runtime_snapshot_payload=runtime_snapshot,
        scheduler_plan_snapshot_payload=validation["scheduler_plan_snapshot_payload"],
        account_snapshot_payload=validation["account_snapshot_payload"],
        credential_snapshot_payload=validation["broker_snapshot_payload"],
        risk_snapshot_payload=validation["risk_snapshot_payload"],
        operational_snapshot_payload=validation["operational_snapshot_payload"],
        recovery_snapshot_payload=validation["recovery_snapshot_payload"], blocking_reason_codes=blocking,
        warning_reason_codes=validation["warning"], missing_requirement_codes=validation["missing"],
        algorithm_version=ALGORITHM_VERSION,
    )

    package_uba_id = commit.target_user_broker_account_id if validation["account"] is not None else None
    package_paper_id = commit.target_paper_account_id if validation["account"] is not None else None

    package = StrategyDeploymentReadinessPackageEntity(
        strategy_definition_id=strategy_definition_id, runtime_registration_commit_id=runtime_registration_commit_id,
        runtime_registry_id=runtime_registry_id, runtime_scope_hash=commit.runtime_scope_hash,
        target_user_id=commit.target_user_id, account_kind=commit.account_kind,
        target_user_broker_account_id=package_uba_id, target_paper_account_id=package_paper_id,
        market_type=commit.market_type, broker_code=commit.broker_code, execution_mode=commit.execution_mode,
        strategy_version=commit.strategy_version, deployment_snapshot_payload=deployment_snapshot,
        runtime_snapshot_payload=runtime_snapshot,
        scheduler_plan_snapshot_payload=validation["scheduler_plan_snapshot_payload"],
        account_snapshot_payload=validation["account_snapshot_payload"],
        credential_snapshot_payload=validation["broker_snapshot_payload"], risk_snapshot_payload=validation["risk_snapshot_payload"],
        operational_snapshot_payload=validation["operational_snapshot_payload"],
        recovery_snapshot_payload=validation["recovery_snapshot_payload"], readiness_status=readiness_status,
        blocking_reason_codes=blocking, warning_reason_codes=validation["warning"], missing_requirement_codes=validation["missing"],
        deployment_input_hash=deployment_input_hash, algorithm_version=ALGORITHM_VERSION, created_by=actor,
        created_at=created_at, idempotency_key=(idempotency_key or None),
    )
    try:
        session.add(package)
        session.flush()
        _write_deployment_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=commit.runtime_scope_hash,
            deployment_id=None, event_type="DEPLOYMENT_READINESS_REVIEW_CREATED", previous_status=None,
            current_status=readiness_status, source_type="PACKAGE",
            source_id=int(package.deployment_readiness_package_id), actor=actor, occurred_at=created_at,
            metadata_payload={"blocking_reason_codes": blocking},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyDeploymentReadinessPackageEntity).where(
                    StrategyDeploymentReadinessPackageEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_package_dict(conflict, idempotent_replay=True)
        raise DeploymentReadinessError("DUPLICATE_DEPLOYMENT_READINESS_REVIEW", "동일 Package/History 저장 중 충돌이 발생했습니다.") from None

    session.refresh(package)
    return _to_package_dict(package, idempotent_replay=False)


def _to_package_dict(package: StrategyDeploymentReadinessPackageEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "deployment_readiness_package_id": int(package.deployment_readiness_package_id),
        "strategy_definition_id": package.strategy_definition_id,
        "runtime_registration_commit_id": package.runtime_registration_commit_id,
        "runtime_registry_id": package.runtime_registry_id,
        "runtime_scope_hash": package.runtime_scope_hash,
        "target_user_id": package.target_user_id,
        "account_kind": package.account_kind,
        "target_user_broker_account_id": package.target_user_broker_account_id,
        "target_paper_account_id": package.target_paper_account_id,
        "market_type": package.market_type,
        "broker_code": package.broker_code,
        "execution_mode": package.execution_mode,
        "strategy_version": package.strategy_version,
        "deployment_snapshot_payload": package.deployment_snapshot_payload,
        "runtime_snapshot_payload": package.runtime_snapshot_payload,
        "scheduler_plan_snapshot_payload": package.scheduler_plan_snapshot_payload,
        "account_snapshot_payload": package.account_snapshot_payload,
        "credential_snapshot_payload": package.credential_snapshot_payload,
        "risk_snapshot_payload": package.risk_snapshot_payload,
        "operational_snapshot_payload": package.operational_snapshot_payload,
        "recovery_snapshot_payload": package.recovery_snapshot_payload,
        "readiness_status": package.readiness_status,
        "blocking_reason_codes": package.blocking_reason_codes,
        "warning_reason_codes": package.warning_reason_codes,
        "missing_requirement_codes": package.missing_requirement_codes,
        "deployment_input_hash": package.deployment_input_hash,
        "algorithm_version": package.algorithm_version,
        "created_by": package.created_by,
        "created_at": package.created_at,
        "idempotency_key": package.idempotency_key,
        "idempotent_replay": idempotent_replay,
    }


def check_deployment_readiness_package_staleness(
    session: Session, package: StrategyDeploymentReadinessPackageEntity
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    definition = session.get(StrategyDefinitionEntity, package.strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        return True, ["DEFINITION_MISSING"]
    if definition.definition_version != package.strategy_version:
        reasons.append("DEFINITION_VERSION_CHANGED")

    commit = session.get(StrategyRuntimeRegistrationCommitEntity, package.runtime_registration_commit_id)
    if commit is None:
        reasons.append("RUNTIME_REGISTRATION_COMMIT_MISSING")
        return True, reasons
    if commit.registration_commit_hash != package.runtime_snapshot_payload.get("registration_commit_hash"):
        reasons.append("RUNTIME_REGISTRATION_COMMIT_HASH_CHANGED")
    if commit.runtime_scope_hash != package.runtime_scope_hash:
        reasons.append("RUNTIME_SCOPE_CHANGED")

    registry = session.get(StrategyRuntimeRegistryEntity, package.runtime_registry_id)
    if registry is None:
        reasons.append("RUNTIME_REGISTRY_MISSING")
    else:
        if bool(registry.enabled) != package.runtime_snapshot_payload.get("registry_enabled"):
            reasons.append("RUNTIME_REGISTRY_STATUS_CHANGED")
        if bool(registry.running) != package.runtime_snapshot_payload.get("registry_running"):
            reasons.append("RUNTIME_REGISTRY_STATUS_CHANGED")

    state = get_promotion_state(session, package.strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        reasons.append("PROMOTION_STATE_CHANGED")
    if state["status_version"] != package.runtime_snapshot_payload.get("promotion_state_version"):
        reasons.append("PROMOTION_STATE_VERSION_CHANGED")
    if state["state_hash"] != package.runtime_snapshot_payload.get("promotion_state_hash"):
        reasons.append("PROMOTION_STATE_HASH_CHANGED")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            reasons.append(f"LIFECYCLE_{lifecycle.lifecycle_status}")

    if commit is not None:
        account, _ = _resolve_account(
            session, target_account_kind=package.account_kind,
            target_user_broker_account_id=package.target_user_broker_account_id,
            target_paper_account_id=package.target_paper_account_id,
        )
        current_account_snapshot = _account_snapshot_payload(account, kind=package.account_kind)
        if current_account_snapshot != package.account_snapshot_payload:
            reasons.append("ACCOUNT_SNAPSHOT_CHANGED")

        broker_snapshot, _bb, _bw = _broker_snapshot_payload(
            session, account=account, target_account_kind=package.account_kind,
            requested_execution_mode=package.execution_mode,
        )
        if broker_snapshot.get("verification_status") != package.credential_snapshot_payload.get("verification_status"):
            reasons.append("CREDENTIAL_SNAPSHOT_CHANGED")
        if broker_snapshot.get("key_version") != package.credential_snapshot_payload.get("key_version"):
            reasons.append("CREDENTIAL_VERSION_CHANGED")

        risk_snapshot, _rb, _rw = _risk_snapshot_payload(
            session, account=account, target_account_kind=package.account_kind,
            requested_execution_mode=package.execution_mode,
        )
        if risk_snapshot != package.risk_snapshot_payload:
            reasons.append("RISK_SNAPSHOT_CHANGED")

        operational_snapshot, _ob, _ow = _operational_snapshot_payload(
            session, strategy_definition_id=package.strategy_definition_id, account=account,
            target_account_kind=package.account_kind,
        )
        if operational_snapshot != package.operational_snapshot_payload:
            reasons.append("OPERATIONAL_SNAPSHOT_CHANGED")

    existing_deployment = session.scalar(
        select(StrategyDeploymentReadinessCommitEntity).where(
            StrategyDeploymentReadinessCommitEntity.runtime_scope_hash == package.runtime_scope_hash
        )
    )
    if existing_deployment is not None:
        reasons.append("DEPLOYMENT_ALREADY_EXISTS")
    existing_scheduler_plan = session.scalar(
        select(StrategyRuntimeSchedulerPlanEntity).where(
            StrategyRuntimeSchedulerPlanEntity.runtime_scope_hash == package.runtime_scope_hash
        )
    )
    if existing_scheduler_plan is not None:
        reasons.append("SCHEDULER_PLAN_CHANGED")

    return len(reasons) > 0, reasons


def run_record_deployment_readiness_decision(
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
    package = session.get(StrategyDeploymentReadinessPackageEntity, package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise DeploymentReadinessError("PACKAGE_NOT_FOUND", f"Deployment Readiness Package not found: {package_id}")
    if decision_type not in DEPLOYMENT_DECISION_TYPES:
        raise DeploymentReadinessError("INVALID_DECISION_TYPE", f"알 수 없는 Decision Type: {decision_type}")
    if reason_code not in REASON_CODES_BY_DEPLOYMENT_DECISION_TYPE.get(decision_type, frozenset()):
        raise DeploymentReadinessError("INVALID_REASON_CODE", f"{decision_type}에 허용되지 않는 reason_code입니다: {reason_code}")
    if not reason_text or not reason_text.strip():
        raise DeploymentReadinessError("REASON_TEXT_REQUIRED", "reason_text는 필수입니다.")

    existing_decision = session.scalar(
        select(StrategyDeploymentReadinessDecisionEntity).where(
            StrategyDeploymentReadinessDecisionEntity.deployment_readiness_package_id == package_id
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
            raise DeploymentReadinessError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")
        raise DeploymentReadinessError("DUPLICATE_DEPLOYMENT_READINESS_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다.")

    stale, stale_reasons = check_deployment_readiness_package_staleness(session, package)
    if stale:
        raise DeploymentReadinessError("STALE_DEPLOYMENT_READINESS_PACKAGE", f"Deployment Readiness Package가 Stale 상태입니다: {', '.join(stale_reasons)}")

    deployment_ready = False
    if decision_type == DEPLOYMENT_DECISION_APPROVE:
        if package.readiness_status != READINESS_STATUS_READY:
            raise DeploymentReadinessError("PACKAGE_NOT_READY", f"Package 상태가 READY_FOR_DEPLOYMENT가 아닙니다(현재: {package.readiness_status}).")
        required_codes = {
            c["checklist_code"] for c in build_deployment_checklist_template(package.execution_mode) if c["required"]
        }
        missing_confirmations = [c for c in required_codes if not checklist_confirmations.get(c)]
        if missing_confirmations:
            raise DeploymentReadinessError("INCOMPLETE_CHECKLIST", f"필수 Checklist 미확인 항목이 있습니다: {', '.join(sorted(missing_confirmations))}")
        if package.warning_reason_codes and set(package.warning_reason_codes) - set(acknowledged_warnings) - {"ALL"}:
            if "ALL" not in acknowledged_warnings:
                raise DeploymentReadinessError("WARNING_NOT_ACKNOWLEDGED", "모든 Warning을 확인(acknowledge)해야 합니다.")
        deployment_ready = True

    same_actor_warning = actor == package.created_by
    decided_at = datetime.now(timezone.utc)
    decision_input_hash = compute_deployment_decision_input_hash(
        deployment_readiness_package_id=package_id, decision_type=decision_type, reason_code=reason_code,
        reason_text=reason_text, checklist_payload=checklist_confirmations,
        acknowledged_warnings_payload=acknowledged_warnings, decided_by=actor, decided_at=decided_at,
        algorithm_version=ALGORITHM_VERSION,
    )
    decision = StrategyDeploymentReadinessDecisionEntity(
        deployment_readiness_package_id=package_id, strategy_definition_id=strategy_definition_id,
        runtime_scope_hash=package.runtime_scope_hash, decision_type=decision_type, reason_code=reason_code,
        reason_text=reason_text, checklist_payload=checklist_confirmations,
        acknowledged_warnings_payload=acknowledged_warnings, same_actor_warning=same_actor_warning,
        decided_by=actor, decided_at=decided_at, decision_input_hash=decision_input_hash,
        deployment_ready=deployment_ready, idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
    )
    try:
        session.add(decision)
        session.flush()
        _write_deployment_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=package.runtime_scope_hash,
            deployment_id=None, event_type=_HISTORY_EVENT_BY_DECISION_TYPE[decision_type],
            previous_status=package.readiness_status, current_status=decision_type, source_type="DECISION",
            source_id=int(decision.deployment_readiness_decision_id), actor=actor, occurred_at=decided_at,
            metadata_payload={"reason_code": reason_code},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = session.scalar(
            select(StrategyDeploymentReadinessDecisionEntity).where(
                StrategyDeploymentReadinessDecisionEntity.deployment_readiness_package_id == package_id
            )
        )
        if conflict is not None:
            if idempotency_key and conflict.idempotency_key == idempotency_key:
                return _to_decision_dict(conflict, idempotent_replay=True)
            raise DeploymentReadinessError("DUPLICATE_DEPLOYMENT_READINESS_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다.") from None
        raise DeploymentReadinessError("DUPLICATE_DEPLOYMENT_READINESS_HISTORY", "동일 Decision에 대한 History가 이미 존재합니다.") from None
    session.refresh(decision)
    return _to_decision_dict(decision, idempotent_replay=False)


def _to_decision_dict(decision: StrategyDeploymentReadinessDecisionEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "deployment_readiness_decision_id": int(decision.deployment_readiness_decision_id),
        "deployment_readiness_package_id": decision.deployment_readiness_package_id,
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
        "deployment_ready": decision.deployment_ready,
        "idempotency_key": decision.idempotency_key,
        "algorithm_version": decision.algorithm_version,
        "idempotent_replay": idempotent_replay,
    }


def run_create_deployment_readiness_commit(
    session: Session,
    strategy_definition_id: int,
    *,
    deployment_readiness_package_id: int,
    deployment_readiness_decision_id: int,
    runtime_registration_commit_id: int,
    runtime_scope_hash: str,
    deployment_input_hash: str,
    decision_input_hash: str,
    commit_reason: str,
    confirmation_text: str,
    acknowledge_same_actor_warning: bool = False,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not commit_reason or not commit_reason.strip():
        raise DeploymentReadinessError("COMMIT_REASON_REQUIRED", "commit_reason은 필수입니다.")
    if _normalize_confirmation_text(confirmation_text) != CONFIRMATION_TEXT_REQUIRED:
        raise DeploymentReadinessError("INVALID_CONFIRMATION", f"확인값이 올바르지 않습니다('{CONFIRMATION_TEXT_REQUIRED}'를 입력하세요).")

    definition = session.scalar(
        select(StrategyDefinitionEntity)
        .where(StrategyDefinitionEntity.strategy_id == strategy_definition_id)
        .with_for_update()
    )
    if definition is None or definition.deleted_at is not None:
        raise DeploymentReadinessError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    # § STEP12-19 — Promotion State FOR UPDATE Lock(§ STEP12-18R와 동일한
    # 원칙). Runtime Registry는 이 STEP에서 자체 Row Lock을 추가로 걸지
    # 않는다(값을 변경하지 않고 읽기만 하며, Registry의 유일성은 이미
    # `strategy_runtime_registry.runtime_scope_hash` UNIQUE와 이 함수의
    # Deployment Readiness Commit UNIQUE(runtime_scope_hash)로 보호된다).
    _ensure_and_lock_promotion_state(session, strategy_definition_id, actor=actor)
    state = get_promotion_state(session, strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        raise DeploymentReadinessError("STRATEGY_NOT_ACTIVATED", f"Strategy Promotion State가 ACTIVATED가 아닙니다(현재: {state['current_status']}).")

    package = session.get(StrategyDeploymentReadinessPackageEntity, deployment_readiness_package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise DeploymentReadinessError("PACKAGE_NOT_FOUND", f"Deployment Readiness Package not found: {deployment_readiness_package_id}")
    if package.runtime_scope_hash != runtime_scope_hash:
        raise DeploymentReadinessError("RUNTIME_SCOPE_MISMATCH", "요청한 runtime_scope_hash가 Package의 값과 일치하지 않습니다.")
    if package.runtime_registration_commit_id != runtime_registration_commit_id:
        raise DeploymentReadinessError("OWNERSHIP_MISMATCH", "요청한 runtime_registration_commit_id가 Package의 값과 일치하지 않습니다.")

    decision = session.get(StrategyDeploymentReadinessDecisionEntity, deployment_readiness_decision_id)
    if decision is None or decision.deployment_readiness_package_id != deployment_readiness_package_id:
        raise DeploymentReadinessError("DECISION_NOT_FOUND", f"Deployment Readiness Decision not found: {deployment_readiness_decision_id}")
    if decision.decision_type != DEPLOYMENT_DECISION_APPROVE:
        raise DeploymentReadinessError("DECISION_TYPE_MISMATCH", f"Decision Type이 APPROVE_DEPLOYMENT가 아닙니다(현재: {decision.decision_type}).")
    if not decision.deployment_ready:
        raise DeploymentReadinessError("DEPLOYMENT_NOT_READY", "이 Decision은 deployment_ready=false입니다.")
    if package.deployment_input_hash != deployment_input_hash:
        raise DeploymentReadinessError("READINESS_HASH_MISMATCH", "요청한 deployment_input_hash가 Package의 값과 일치하지 않습니다.")
    if decision.decision_input_hash != decision_input_hash:
        raise DeploymentReadinessError("READINESS_HASH_MISMATCH", "요청한 decision_input_hash가 Decision의 값과 일치하지 않습니다.")
    if decision.same_actor_warning and not acknowledge_same_actor_warning:
        raise DeploymentReadinessError("SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED", "Package 생성자와 결정자가 동일합니다 — acknowledge_same_actor_warning=true가 필요합니다.")

    if idempotency_key:
        existing_by_key = session.scalar(
            select(StrategyDeploymentReadinessCommitEntity).where(
                StrategyDeploymentReadinessCommitEntity.idempotency_key == idempotency_key
            )
        )
        if existing_by_key is not None:
            same_request = (
                existing_by_key.strategy_definition_id == strategy_definition_id
                and existing_by_key.deployment_readiness_package_id == deployment_readiness_package_id
                and existing_by_key.deployment_readiness_decision_id == deployment_readiness_decision_id
                and existing_by_key.deployment_input_hash == deployment_input_hash
                and existing_by_key.decision_input_hash == decision_input_hash
            )
            if same_request:
                return _to_commit_dict(session, existing_by_key, idempotent_replay=True)
            raise DeploymentReadinessError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")

    existing_for_package = session.scalar(
        select(StrategyDeploymentReadinessCommitEntity).where(
            StrategyDeploymentReadinessCommitEntity.deployment_readiness_package_id == deployment_readiness_package_id
        )
    )
    if existing_for_package is not None:
        raise DeploymentReadinessError("DEPLOYMENT_ALREADY_EXISTS", f"Package #{deployment_readiness_package_id}은 이미 Deployment Commit이 존재합니다.")

    stale, stale_reasons = check_deployment_readiness_package_staleness(session, package)
    if stale:
        raise DeploymentReadinessError("STALE_DEPLOYMENT_READINESS_PACKAGE", f"Deployment Readiness Package가 Stale 상태입니다: {', '.join(stale_reasons)}")

    commit = session.get(StrategyRuntimeRegistrationCommitEntity, runtime_registration_commit_id)
    if commit is None:
        raise DeploymentReadinessError("RUNTIME_REGISTRATION_COMMIT_NOT_FOUND", f"Runtime Registration Commit not found: {runtime_registration_commit_id}")

    committed_at = datetime.now(timezone.utc)
    confirmation_hash = _hash(_canonical_json({"confirmation_text": _normalize_confirmation_text(confirmation_text)}))

    scheduler_defaults = package.scheduler_plan_snapshot_payload
    plan_version = 1
    scheduler_plan_hash = compute_scheduler_plan_hash(
        runtime_scope_hash=runtime_scope_hash, scheduler_type=scheduler_defaults["scheduler_type"],
        timezone_name=scheduler_defaults["timezone"], market_calendar=scheduler_defaults["market_calendar"],
        cron_expression=scheduler_defaults.get("cron_expression"), interval_seconds=scheduler_defaults.get("interval_seconds"),
        start_policy="MARKET_OPEN" if scheduler_defaults["scheduler_type"] == SCHEDULER_TYPE_MARKET_SESSION else "IMMEDIATE_INTERVAL",
        stop_policy="MARKET_CLOSE" if scheduler_defaults["scheduler_type"] == SCHEDULER_TYPE_MARKET_SESSION else "MANUAL",
        market_open_offset=scheduler_defaults.get("market_open_offset"), market_close_offset=scheduler_defaults.get("market_close_offset"),
        holiday_policy=scheduler_defaults["holiday_policy"], plan_version=plan_version, algorithm_version=ALGORITHM_VERSION,
    )

    deployment = StrategyDeploymentEntity(
        strategy_code=definition.strategy_code, strategy_performance_run_id=None,
        market_code=package.broker_code if package.account_kind == ACCOUNT_KIND_USER_BROKER else ("UPBIT" if _market_family(package.market_type) == "CRYPTO" else "KRX"),
        symbol=None, mode_code=("LIVE" if package.execution_mode == EXECUTION_MODE_LIVE else "PAPER"),
        status_code=StrategyDeploymentStatus.READY_TO_START.value, parameter_payload={},
        requested_by=actor, strategy_id=strategy_definition_id,
        owner_type=definition.owner_type, user_id=(package.target_user_id if definition.owner_type == "USER" else None),
    )

    try:
        session.add(deployment)
        session.flush()

        scheduler_plan = StrategyRuntimeSchedulerPlanEntity(
            runtime_registry_id=package.runtime_registry_id, runtime_scope_hash=runtime_scope_hash,
            scheduler_type=scheduler_defaults["scheduler_type"], timezone=scheduler_defaults["timezone"],
            market_calendar=scheduler_defaults["market_calendar"], cron_expression=scheduler_defaults.get("cron_expression"),
            interval_seconds=scheduler_defaults.get("interval_seconds"),
            start_policy="MARKET_OPEN" if scheduler_defaults["scheduler_type"] == SCHEDULER_TYPE_MARKET_SESSION else "IMMEDIATE_INTERVAL",
            stop_policy="MARKET_CLOSE" if scheduler_defaults["scheduler_type"] == SCHEDULER_TYPE_MARKET_SESSION else "MANUAL",
            market_open_offset=scheduler_defaults.get("market_open_offset"), market_close_offset=scheduler_defaults.get("market_close_offset"),
            holiday_policy=scheduler_defaults["holiday_policy"], retry_policy_payload={"max_retries": 0},
            misfire_policy_payload={"grace_seconds": 0}, concurrency_policy_payload={"max_instances": 1},
            enabled=False, registered_to_scheduler=False, scheduler_job_id=None, plan_version=plan_version,
            plan_hash=scheduler_plan_hash, created_by=actor, created_at=committed_at,
        )
        session.add(scheduler_plan)
        session.flush()

        deployment_commit_hash = compute_deployment_commit_hash(
            strategy_definition_id=strategy_definition_id, runtime_registration_commit_id=runtime_registration_commit_id,
            runtime_registry_id=package.runtime_registry_id, deployment_readiness_package_id=deployment_readiness_package_id,
            deployment_readiness_decision_id=deployment_readiness_decision_id, runtime_scope_hash=runtime_scope_hash,
            strategy_deployment_id=int(deployment.strategy_deployment_id), scheduler_plan_id=int(scheduler_plan.scheduler_plan_id),
            deployment_input_hash=deployment_input_hash, decision_input_hash=decision_input_hash,
            scheduler_plan_hash=scheduler_plan_hash, committed_by=actor, committed_at=committed_at,
            confirmation_hash=confirmation_hash, algorithm_version=ALGORITHM_VERSION,
        )

        readiness_commit = StrategyDeploymentReadinessCommitEntity(
            strategy_definition_id=strategy_definition_id, runtime_registration_commit_id=runtime_registration_commit_id,
            runtime_registry_id=package.runtime_registry_id, deployment_readiness_package_id=deployment_readiness_package_id,
            deployment_readiness_decision_id=deployment_readiness_decision_id, runtime_scope_hash=runtime_scope_hash,
            strategy_deployment_id=int(deployment.strategy_deployment_id), scheduler_plan_id=int(scheduler_plan.scheduler_plan_id),
            deployment_input_hash=deployment_input_hash, decision_input_hash=decision_input_hash,
            scheduler_plan_hash=scheduler_plan_hash, confirmation_hash=confirmation_hash,
            deployment_commit_hash=deployment_commit_hash, committed_by=actor, committed_at=committed_at,
            idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
        )
        session.add(readiness_commit)
        session.flush()

        _write_deployment_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=runtime_scope_hash,
            deployment_id=int(deployment.strategy_deployment_id), event_type="DEPLOYMENT_READY_TO_START",
            previous_status=decision.decision_type, current_status=StrategyDeploymentStatus.READY_TO_START.value,
            source_type="COMMIT", source_id=int(readiness_commit.deployment_readiness_commit_id), actor=actor,
            occurred_at=committed_at, metadata_payload={"deployment_commit_hash": deployment_commit_hash},
        )

        # § STEP12-19 Carry-forward(3.1) — Transaction 경계 명확화. Audit는
        # add+flush만 수행하고, 이 함수가 최상위에서 정확히 한 번 commit한다.
        AuditLogService(session).record(
            event_type="DEPLOYMENT_READY_TO_START", actor=actor, strategy_id=str(strategy_definition_id),
            detail={
                "deployment_readiness_commit_id": int(readiness_commit.deployment_readiness_commit_id),
                "strategy_deployment_id": int(deployment.strategy_deployment_id),
                "deployment_commit_hash": deployment_commit_hash, "runtime_scope_hash": runtime_scope_hash,
            },
            auto_commit=False,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyDeploymentReadinessCommitEntity).where(
                    StrategyDeploymentReadinessCommitEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_commit_dict(session, conflict, idempotent_replay=True)
        package_conflict = session.scalar(
            select(StrategyDeploymentReadinessCommitEntity).where(
                StrategyDeploymentReadinessCommitEntity.deployment_readiness_package_id == deployment_readiness_package_id
            )
        )
        if package_conflict is not None:
            raise DeploymentReadinessError("DEPLOYMENT_ALREADY_EXISTS", f"Package #{deployment_readiness_package_id}은 이미 Deployment Commit이 존재합니다.") from None
        scope_conflict = session.scalar(
            select(StrategyDeploymentReadinessCommitEntity).where(
                StrategyDeploymentReadinessCommitEntity.runtime_scope_hash == runtime_scope_hash
            )
        )
        if scope_conflict is not None:
            raise DeploymentReadinessError("DEPLOYMENT_ALREADY_EXISTS", "동일 Runtime Scope에 이미 Deployment가 존재합니다.") from None
        raise DeploymentReadinessError("DUPLICATE_DEPLOYMENT_READINESS_COMMIT", "동일 Deployment Readiness Commit이 이미 존재합니다.") from None

    session.refresh(readiness_commit)
    return _to_commit_dict(session, readiness_commit, idempotent_replay=False)


def _to_commit_dict(
    session: Session, commit: StrategyDeploymentReadinessCommitEntity, *, idempotent_replay: bool
) -> dict[str, Any]:
    deployment = session.get(StrategyDeploymentEntity, commit.strategy_deployment_id)
    scheduler_plan = session.get(StrategyRuntimeSchedulerPlanEntity, commit.scheduler_plan_id)
    return {
        "deployment_readiness_commit_id": int(commit.deployment_readiness_commit_id),
        "strategy_definition_id": commit.strategy_definition_id,
        "runtime_registration_commit_id": commit.runtime_registration_commit_id,
        "runtime_registry_id": commit.runtime_registry_id,
        "deployment_readiness_package_id": commit.deployment_readiness_package_id,
        "deployment_readiness_decision_id": commit.deployment_readiness_decision_id,
        "runtime_scope_hash": commit.runtime_scope_hash,
        "strategy_deployment_id": commit.strategy_deployment_id,
        "scheduler_plan_id": commit.scheduler_plan_id,
        "deployment_commit_hash": commit.deployment_commit_hash,
        "committed_by": commit.committed_by,
        "committed_at": commit.committed_at,
        "deployment_status": deployment.status_code if deployment is not None else None,
        "scheduler_plan_enabled": bool(scheduler_plan.enabled) if scheduler_plan is not None else False,
        "scheduler_plan_registered_to_scheduler": bool(scheduler_plan.registered_to_scheduler) if scheduler_plan is not None else False,
        "scheduler_job_id": scheduler_plan.scheduler_job_id if scheduler_plan is not None else None,
        "next_action": "REVIEW_START_APPROVAL",
        "idempotent_replay": idempotent_replay,
    }


def get_deployment_readiness_package(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = session.get(StrategyDeploymentReadinessPackageEntity, package_id)
    if package is None:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Package not found: {package_id}")
    if strategy_definition_id is not None and package.strategy_definition_id != strategy_definition_id:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Package not found: {package_id}")
    result = _to_package_dict(package, idempotent_replay=False)
    stale, stale_reasons = check_deployment_readiness_package_staleness(session, package)
    commit = session.scalar(
        select(StrategyDeploymentReadinessCommitEntity).where(
            StrategyDeploymentReadinessCommitEntity.deployment_readiness_package_id == package_id
        )
    )
    decision = session.scalar(
        select(StrategyDeploymentReadinessDecisionEntity).where(
            StrategyDeploymentReadinessDecisionEntity.deployment_readiness_package_id == package_id
        )
    )
    if commit is not None:
        current_effective_status = "READY_TO_START"
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
            "deployed": commit is not None,
        }
    )
    return result


def list_deployment_readiness_packages(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyDeploymentReadinessPackageEntity)
        .where(StrategyDeploymentReadinessPackageEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyDeploymentReadinessPackageEntity.deployment_readiness_package_id.desc())
    )
    return [_to_package_dict(r, idempotent_replay=False) for r in rows]


def get_deployment_readiness_package_checklist(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyDeploymentReadinessPackageEntity, package_id)
    if package is None:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Package not found: {package_id}")
    decision = session.scalar(
        select(StrategyDeploymentReadinessDecisionEntity).where(
            StrategyDeploymentReadinessDecisionEntity.deployment_readiness_package_id == package_id
        )
    )
    return {
        "deployment_readiness_package_id": package_id,
        "checklist_template": build_deployment_checklist_template(package.execution_mode),
        "checklist_confirmations": decision.checklist_payload if decision is not None else {},
    }


def get_deployment_readiness_package_staleness(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyDeploymentReadinessPackageEntity, package_id)
    if package is None:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Package not found: {package_id}")
    stale, reasons = check_deployment_readiness_package_staleness(session, package)
    return {"deployment_readiness_package_id": package_id, "stale": stale, "reasons": reasons}


def get_deployment_readiness_decision(session: Session, package_id: int) -> dict[str, Any] | None:
    decision = session.scalar(
        select(StrategyDeploymentReadinessDecisionEntity).where(
            StrategyDeploymentReadinessDecisionEntity.deployment_readiness_package_id == package_id
        )
    )
    if decision is None:
        return None
    return _to_decision_dict(decision, idempotent_replay=False)


def get_deployment_readiness_commit(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyDeploymentReadinessCommitEntity, commit_id)
    if commit is None:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Commit not found: {commit_id}")
    return _to_commit_dict(session, commit, idempotent_replay=False)


def list_deployment_readiness_commits(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyDeploymentReadinessCommitEntity)
        .where(StrategyDeploymentReadinessCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyDeploymentReadinessCommitEntity.deployment_readiness_commit_id.desc())
    )
    return [_to_commit_dict(session, r, idempotent_replay=False) for r in rows]


def get_deployment_readiness_commit_provenance(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyDeploymentReadinessCommitEntity, commit_id)
    if commit is None:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise DeploymentReadinessError("NOT_FOUND", f"Deployment Readiness Commit not found: {commit_id}")
    return {
        "deployment_readiness_commit_id": int(commit.deployment_readiness_commit_id),
        "runtime_scope_hash": commit.runtime_scope_hash,
        "deployment_commit_hash": commit.deployment_commit_hash,
        "scheduler_plan_hash": commit.scheduler_plan_hash,
    }


def get_deployment_readiness_status(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    commits = session.scalars(
        select(StrategyDeploymentReadinessCommitEntity)
        .where(StrategyDeploymentReadinessCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyDeploymentReadinessCommitEntity.committed_at.desc())
    ).all()
    state = get_promotion_state(session, strategy_definition_id)
    if not commits:
        return {
            "strategy_definition_id": strategy_definition_id, "deployed": False, "total_deployments": 0,
            "deployment_readiness_commit_id": None, "strategy_promotion_status": state["current_status"],
            "next_action": "REVIEW_DEPLOYMENT_READINESS" if state["current_status"] == PROMOTION_STATE_ACTIVATED else "REVIEW_ACTIVATION",
        }
    result = _to_commit_dict(session, commits[0], idempotent_replay=False)
    result["deployed"] = True
    result["total_deployments"] = len(commits)
    result["strategy_definition_id"] = strategy_definition_id
    result["strategy_promotion_status"] = state["current_status"]
    return result


def get_deployment_readiness_scopes(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    commits = session.scalars(
        select(StrategyDeploymentReadinessCommitEntity)
        .where(StrategyDeploymentReadinessCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyDeploymentReadinessCommitEntity.committed_at.asc())
    ).all()
    scopes: list[dict[str, Any]] = []
    for commit in commits:
        deployment = session.get(StrategyDeploymentEntity, commit.strategy_deployment_id)
        scheduler_plan = session.get(StrategyRuntimeSchedulerPlanEntity, commit.scheduler_plan_id)
        scopes.append(
            {
                "runtime_scope_hash": commit.runtime_scope_hash,
                "deployment_readiness_commit_id": int(commit.deployment_readiness_commit_id),
                "strategy_deployment_id": commit.strategy_deployment_id,
                "deployment_status": deployment.status_code if deployment is not None else None,
                "scheduler_plan_id": commit.scheduler_plan_id,
                "scheduler_plan_enabled": bool(scheduler_plan.enabled) if scheduler_plan is not None else False,
                "scheduler_registered_to_scheduler": bool(scheduler_plan.registered_to_scheduler) if scheduler_plan is not None else False,
                "committed_at": commit.committed_at,
            }
        )
    return scopes


def get_deployment_readiness_history(
    session: Session, strategy_definition_id: int, *, runtime_scope_hash: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(StrategyDeploymentReadinessHistoryEntity).where(
        StrategyDeploymentReadinessHistoryEntity.strategy_definition_id == strategy_definition_id
    )
    if runtime_scope_hash is not None:
        stmt = stmt.where(StrategyDeploymentReadinessHistoryEntity.runtime_scope_hash == runtime_scope_hash)
    rows = session.scalars(
        stmt.order_by(
            StrategyDeploymentReadinessHistoryEntity.occurred_at.asc(),
            StrategyDeploymentReadinessHistoryEntity.history_id.asc(),
        )
    )
    return [_to_history_dict(h) for h in rows]


def list_scheduler_plans(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    commits = session.scalars(
        select(StrategyDeploymentReadinessCommitEntity).where(
            StrategyDeploymentReadinessCommitEntity.strategy_definition_id == strategy_definition_id
        )
    ).all()
    plan_ids = [c.scheduler_plan_id for c in commits]
    if not plan_ids:
        return []
    rows = session.scalars(
        select(StrategyRuntimeSchedulerPlanEntity).where(StrategyRuntimeSchedulerPlanEntity.scheduler_plan_id.in_(plan_ids))
    )
    return [_to_scheduler_plan_dict(p) for p in rows]


def get_scheduler_plan(session: Session, plan_id: int) -> dict[str, Any]:
    plan = session.get(StrategyRuntimeSchedulerPlanEntity, plan_id)
    if plan is None:
        raise DeploymentReadinessError("NOT_FOUND", f"Scheduler Plan not found: {plan_id}")
    return _to_scheduler_plan_dict(plan)


def _to_scheduler_plan_dict(plan: StrategyRuntimeSchedulerPlanEntity) -> dict[str, Any]:
    return {
        "scheduler_plan_id": int(plan.scheduler_plan_id),
        "runtime_registry_id": plan.runtime_registry_id,
        "runtime_scope_hash": plan.runtime_scope_hash,
        "scheduler_type": plan.scheduler_type,
        "timezone": plan.timezone,
        "market_calendar": plan.market_calendar,
        "cron_expression": plan.cron_expression,
        "interval_seconds": plan.interval_seconds,
        "start_policy": plan.start_policy,
        "stop_policy": plan.stop_policy,
        "market_open_offset": plan.market_open_offset,
        "market_close_offset": plan.market_close_offset,
        "holiday_policy": plan.holiday_policy,
        "enabled": bool(plan.enabled),
        "registered_to_scheduler": bool(plan.registered_to_scheduler),
        "scheduler_job_id": plan.scheduler_job_id,
        "plan_version": plan.plan_version,
        "plan_hash": plan.plan_hash,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
    }
