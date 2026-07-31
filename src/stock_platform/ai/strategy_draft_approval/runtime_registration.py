"""STEP 12-18 — Runtime Registration Review Package / Decision / Commit.

ACTIVATED 상태의 Strategy Definition을 대상으로 계좌/시장/브로커/리스크/
운영 준비 상태를 재검증한 뒤, 관리자의 명시적 Runtime Registration
Commit으로 "Runtime에 등록 가능한 불변 구성"을 확정하고 `strategy_
runtime_registry`에 **비실행**(`enabled=false`, `running=false`) 상태로
등록한다. Runtime 시작, Scheduler 등록, Broker 연결/로그인, 실시간 시세
구독, Signal 계산, 주문 생성/전송, Paper/Live Trading 시작은 이 STEP
어디에서도 수행하지 않는다.

핵심 설계 결정 — Strategy Promotion State는 이 STEP에서 전혀 전이시키지
않는다: Runtime Registration은 Promotion State(ACTIVATED)와는 완전히
별개의 새 축("등록 여부")이며, ACTIVATED는 이 STEP 전후로 그대로다.
`strategy_promotion_history`는 Promotion State 전이 기록 전용이므로 이
STEP의 이벤트를 그 테이블에 추가하지 않는다(의미가 다른 축을 같은
History에 섞으면 STEP12-16R이 경계했던 것과 동일한 문제가 재발한다).
Runtime Registration Commit은 Strategy당 정확히 1개(UNIQUE)이므로 별도
History 테이블 없이 Commit 행 자체 + Audit 이벤트로 "이력"을 충분히
재구성할 수 있다(`get_runtime_registration_history()`가 이를 합성한다).

재사용(중복 생성 금지 확인):
- 계좌/Credential/Risk/운영(Kill Switch·Recovery·Trading Flag) 검증은
  STEP12-17 `activation.py`의 기존 헬퍼(`_resolve_account`,
  `_broker_snapshot_payload`, `_risk_snapshot_payload`,
  `_operational_snapshot_payload`, `_validate_market_broker`,
  `_market_family`)를 그대로 가져와 쓴다(로직 복제 없음).
- Candidate Lifecycle 차단 목록은 `decision_package.py`의 기존
  `_STALE_LIFECYCLE_STATUSES`를 재사용한다.
- Activation 재검증은 `activation.py`의 기존
  `check_activation_package_staleness()`를 그대로 재사용한다(재계산
  없음).
- Deployment/AccountStrategyLink 존재 확인은 기존 Entity를 읽기 전용으로
  조회한다 — Deployment는 생성하지 않는다(STEP12-19 범위).
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
    _market_family,
    _operational_snapshot_payload,
    _resolve_account,
    _risk_snapshot_payload,
    _validate_market_broker,
    check_activation_package_staleness,
)
from stock_platform.ai.strategy_draft_approval.activation_entities import (
    ACCOUNT_KIND_PAPER,
    ACCOUNT_KIND_USER_BROKER,
    ACCOUNT_KIND_VALUES,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_VALUES,
    StrategyActivationCommitEntity,
    StrategyActivationReviewPackageEntity,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.decision_package import _STALE_LIFECYCLE_STATUSES
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    _ensure_and_lock_promotion_state,
    get_promotion_state,
)
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import PROMOTION_STATE_ACTIVATED
from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
    REGISTRATION_DECISION_APPROVE,
    REGISTRATION_DECISION_TYPES,
    REGISTRATION_READINESS_BLOCKED,
    REGISTRATION_READINESS_READY,
    REGISTRY_STATUS_REGISTERED,
    StrategyRuntimeRegistrationCommitEntity,
    StrategyRuntimeRegistrationDecisionEntity,
    StrategyRuntimeRegistrationHistoryEntity,
    StrategyRuntimeRegistrationPackageEntity,
    StrategyRuntimeRegistryEntity,
)
from stock_platform.api.deps_admin import AuditLogService
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

ALGORITHM_VERSION = "1.0.0"
CONFIRMATION_TEXT_REQUIRED = "REGISTER"

FIXED_RUNTIME_STATUS = "NOT_STARTED"
FIXED_SCHEDULER_STATUS = "NOT_REGISTERED"
FIXED_BROKER_CONNECTION_STATUS = "NOT_STARTED"
FIXED_MARKET_DATA_STATUS = "NOT_SUBSCRIBED"
FIXED_SIGNAL_STATUS = "DISABLED"
FIXED_ORDER_EXECUTION_STATUS = "DISABLED"
FIXED_TRADING_STATUS = "NOT_STARTED"
FIXED_NEXT_ACTION = "REVIEW_DEPLOYMENT_READINESS"

_HISTORY_EVENT_BY_DECISION_TYPE: dict[str, str] = {
    "APPROVE_RUNTIME_REGISTRATION": "RUNTIME_REGISTRATION_APPROVED",
    "REQUEST_RUNTIME_REGISTRATION_CHANGES": "RUNTIME_REGISTRATION_CHANGES_REQUESTED",
    "REJECT_RUNTIME_REGISTRATION": "RUNTIME_REGISTRATION_REJECTED",
}

REASON_CODES_BY_REGISTRATION_DECISION_TYPE: dict[str, frozenset[str]] = {
    "APPROVE_RUNTIME_REGISTRATION": frozenset(
        {"ACTIVATION_REQUIREMENTS_VERIFIED", "ACCOUNT_AND_RISK_REVIEW_COMPLETED", "READY_FOR_RUNTIME_REGISTRATION_COMMIT"}
    ),
    "REQUEST_RUNTIME_REGISTRATION_CHANGES": frozenset(
        {"ACCOUNT_CONFIGURATION_REQUIRED", "RISK_LIMIT_ADJUSTMENT_REQUIRED", "RUNTIME_SCOPE_CONFLICT_REVIEW_REQUIRED"}
    ),
    "REJECT_RUNTIME_REGISTRATION": frozenset(
        {"ACCOUNT_NOT_ELIGIBLE", "UNACCEPTABLE_RISK", "POLICY_VIOLATION", "STRATEGY_NOT_ELIGIBLE", "DUPLICATE_REGISTRATION"}
    ),
}


class RuntimeRegistrationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _normalize_confirmation_text(value: str) -> str:
    return (value or "").strip().upper()


def build_runtime_registration_checklist_template(execution_mode: str) -> list[dict[str, Any]]:
    items = [
        {"checklist_code": "STRATEGY_ACTIVATED_CONFIRMED", "required": True, "question": "Strategy가 ACTIVATED 상태임을 확인했는가"},
        {"checklist_code": "ACTIVATION_COMMIT_CONFIRMED", "required": True, "question": "Activation Commit을 확인했는가"},
        {"checklist_code": "STRATEGY_VERSION_CONFIRMED", "required": True, "question": "Strategy Version을 확인했는가"},
        {"checklist_code": "EXECUTABLE_HASH_CONFIRMED", "required": True, "question": "Executable Hash를 확인했는가"},
        {"checklist_code": "TARGET_USER_CONFIRMED", "required": True, "question": "Target User를 확인했는가"},
        {"checklist_code": "ACCOUNT_OWNERSHIP_CONFIRMED", "required": True, "question": "Account 소유권을 확인했는가"},
        {"checklist_code": "ACCOUNT_STATUS_CONFIRMED", "required": True, "question": "Account 상태를 확인했는가"},
        {"checklist_code": "MARKET_BROKER_CONFIRMED", "required": True, "question": "Market/Broker를 확인했는가"},
        {"checklist_code": "RUNTIME_SCOPE_CONFIRMED", "required": True, "question": "Runtime Scope를 확인했는가"},
        {"checklist_code": "NO_DUPLICATE_RUNTIME_CONFIRMED", "required": True, "question": "중복 Runtime이 없음을 확인했는가"},
        {"checklist_code": "NO_DEPLOYMENT_CONFIRMED", "required": True, "question": "기존 Deployment가 없음을 확인했는가"},
        {"checklist_code": "NO_LINK_CONFLICT_CONFIRMED", "required": True, "question": "AccountStrategyLink 충돌이 없음을 확인했는가"},
        {"checklist_code": "RISK_SNAPSHOT_CONFIRMED", "required": True, "question": "Risk Snapshot을 확인했는가"},
        {"checklist_code": "KILL_SWITCH_INACTIVE_CONFIRMED", "required": True, "question": "Kill Switch 비활성을 확인했는가"},
        {"checklist_code": "ACCOUNT_PAUSE_CONFIRMED", "required": True, "question": "Account Pause 없음을 확인했는가"},
        {"checklist_code": "RECOVERY_CONFLICT_CONFIRMED", "required": True, "question": "Recovery Conflict 없음을 확인했는가"},
        {"checklist_code": "NOT_RUNTIME_START_CONFIRMED", "required": True, "question": "Runtime 등록이 Runtime 실행이 아님을 확인했는가"},
        {"checklist_code": "SCHEDULER_NOT_STARTED_CONFIRMED", "required": True, "question": "Scheduler가 시작되지 않음을 확인했는가"},
        {"checklist_code": "BROKER_NOT_CONNECTED_CONFIRMED", "required": True, "question": "Broker 연결이 수행되지 않음을 확인했는가"},
        {"checklist_code": "NO_ORDER_EXECUTION_CONFIRMED", "required": True, "question": "주문이 실행되지 않음을 확인했는가"},
    ]
    if execution_mode == EXECUTION_MODE_LIVE:
        items.extend(
            [
                {"checklist_code": "LIVE_ACCOUNT_CONFIRMED", "required": True, "question": "LIVE 계좌를 확인했는가"},
                {"checklist_code": "CREDENTIAL_VERIFIED_CONFIRMED", "required": True, "question": "Credential Verified를 확인했는가"},
                {"checklist_code": "CREDENTIAL_VERSION_CONFIRMED", "required": True, "question": "Credential Version을 확인했는가"},
                {"checklist_code": "EXPLICIT_RISK_CONFIRMED", "required": True, "question": "Explicit Risk 설정을 확인했는가"},
                {"checklist_code": "TRADING_ENABLED_CONFIRMED", "required": True, "question": "Trading Enabled를 확인했는가"},
                {"checklist_code": "LIVE_ORDER_ENABLED_CONFIRMED", "required": True, "question": "Live Order Enabled를 확인했는가"},
                {"checklist_code": "INVESTMENT_LIMIT_CONFIRMED", "required": True, "question": "투자 한도를 확인했는가"},
                {"checklist_code": "LOSS_LIMIT_CONFIRMED", "required": True, "question": "손실 한도를 확인했는가"},
                {"checklist_code": "SAME_ACTOR_WARNING_CONFIRMED", "required": False, "question": "Same Actor Warning을 확인했는가(해당 시)"},
                {"checklist_code": "LIVE_CAPITAL_RISK_ACKNOWLEDGED", "required": True, "question": "실제 자금 위험을 인지했는가"},
            ]
        )
    else:
        items.extend(
            [
                {"checklist_code": "PAPER_ACCOUNT_CONFIRMED", "required": True, "question": "Paper Account를 확인했는가"},
                {"checklist_code": "SAFE_PAPER_RISK_CONFIRMED", "required": True, "question": "Safe Paper Risk를 확인했는가"},
                {"checklist_code": "NO_LIVE_ORDER_CONFIRMED", "required": True, "question": "실계좌 주문이 발생하지 않음을 확인했는가"},
                {"checklist_code": "PAPER_RUNTIME_NOT_STARTED_CONFIRMED", "required": True, "question": "Paper Runtime이 아직 시작되지 않음을 확인했는가"},
            ]
        )
    return items


def compute_runtime_scope_hash(
    *,
    user_id: int | None,
    account_kind: str,
    account_id: int | None,
    strategy_id: int,
    strategy_version: int | None,
    market_type: str,
    broker_code: str,
    execution_mode: str,
) -> str:
    canonical = {
        "user_id": user_id, "account_kind": account_kind, "account_id": account_id, "strategy_id": strategy_id,
        "strategy_version": strategy_version, "market_type": market_type, "broker_code": broker_code,
        "execution_mode": execution_mode,
    }
    return _hash(_canonical_json(canonical))


def compute_registration_input_hash(
    *,
    strategy_definition_id: int,
    activation_commit_id: int,
    activation_decision_id: int,
    runtime_scope_payload: dict[str, Any],
    account_snapshot_payload: dict[str, Any],
    credential_snapshot_payload: dict[str, Any],
    risk_snapshot_payload: dict[str, Any],
    operational_snapshot_payload: dict[str, Any],
    activation_snapshot_payload: dict[str, Any],
    blocking_reason_codes: list[str],
    warning_reason_codes: list[str],
    missing_requirement_codes: list[str],
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "activation_commit_id": activation_commit_id,
        "activation_decision_id": activation_decision_id, "runtime_scope_payload": runtime_scope_payload,
        "account_snapshot_payload": account_snapshot_payload, "credential_snapshot_payload": credential_snapshot_payload,
        "risk_snapshot_payload": risk_snapshot_payload, "operational_snapshot_payload": operational_snapshot_payload,
        "activation_snapshot_payload": activation_snapshot_payload,
        "blocking_reason_codes": sorted(blocking_reason_codes), "warning_reason_codes": sorted(warning_reason_codes),
        "missing_requirement_codes": sorted(missing_requirement_codes), "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_registration_decision_input_hash(
    *,
    runtime_registration_package_id: int,
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
        "runtime_registration_package_id": runtime_registration_package_id, "decision_type": decision_type,
        "reason_code": reason_code, "reason_text": reason_text, "checklist_payload": checklist_payload,
        "acknowledged_warnings_payload": sorted(acknowledged_warnings_payload), "decided_by": decided_by,
        "decided_at": decided_at.isoformat(), "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_registration_commit_hash(
    *,
    strategy_definition_id: int,
    activation_commit_id: int,
    runtime_registration_package_id: int,
    registration_input_hash: str,
    runtime_registration_decision_id: int,
    decision_input_hash: str,
    runtime_scope_hash: str,
    committed_by: str,
    committed_at: datetime,
    confirmation_hash: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "activation_commit_id": activation_commit_id,
        "runtime_registration_package_id": runtime_registration_package_id,
        "registration_input_hash": registration_input_hash,
        "runtime_registration_decision_id": runtime_registration_decision_id,
        "decision_input_hash": decision_input_hash, "runtime_scope_hash": runtime_scope_hash,
        "committed_by": committed_by, "committed_at": committed_at.isoformat(), "confirmation_hash": confirmation_hash,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def _validate_activation_prerequisites(
    session: Session, *, definition: StrategyDefinitionEntity, strategy_definition_id: int, activation_commit_id: int
) -> tuple[list[str], StrategyActivationCommitEntity | None, dict[str, Any]]:
    blocking: list[str] = []
    state = get_promotion_state(session, strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        blocking.append("STRATEGY_NOT_ACTIVATED")

    commit = session.get(StrategyActivationCommitEntity, activation_commit_id)
    if commit is None or commit.strategy_definition_id != strategy_definition_id:
        blocking.append("ACTIVATION_COMMIT_NOT_FOUND")
        return blocking, None, {}

    package = session.get(StrategyActivationReviewPackageEntity, commit.activation_review_package_id)
    if package is not None:
        stale, _reasons = check_activation_package_staleness(session, package)
        if stale:
            blocking.append("ACTIVATION_STALE")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            blocking.append("STRATEGY_NOT_ACTIVATED")

    activation_snapshot = {
        "activation_commit_id": int(commit.activation_commit_id),
        "activation_commit_hash": commit.activation_commit_hash,
        "strategy_promotion_status": state["current_status"],
        "promotion_state_version": state["status_version"],
        "promotion_state_hash": state["state_hash"],
        "target_market_type": commit.target_market_type,
        "target_broker_code": commit.target_broker_code,
        "target_account_kind": commit.target_account_kind,
        "target_user_broker_account_id": commit.target_user_broker_account_id,
        "execution_mode": commit.execution_mode,
    }
    return blocking, commit, activation_snapshot


def _run_registration_validations(
    session: Session,
    *,
    definition: StrategyDefinitionEntity,
    strategy_definition_id: int,
    activation_commit: StrategyActivationCommitEntity,
    target_account_kind: str,
    target_user_broker_account_id: int | None,
    target_paper_account_id: int | None,
    target_market_type: str,
    target_broker_code: str,
    execution_mode: str,
) -> dict[str, Any]:
    blocking: list[str] = []
    warning: list[str] = []
    missing: list[str] = []

    if execution_mode not in EXECUTION_MODE_VALUES:
        blocking.append("INVALID_EXECUTION_MODE")
    if target_account_kind not in ACCOUNT_KIND_VALUES:
        blocking.append("INVALID_ACCOUNT_KIND")

    mb_blocking, mb_warning = _validate_market_broker(
        strategy_market_type=definition.market_type, target_market_type=target_market_type,
        target_broker_code=target_broker_code, target_account_kind=target_account_kind,
    )
    blocking.extend(mb_blocking)
    warning.extend(mb_warning)

    account, account_blocking = _resolve_account(
        session, target_account_kind=target_account_kind,
        target_user_broker_account_id=target_user_broker_account_id,
        target_paper_account_id=target_paper_account_id,
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
        session, account=account, target_account_kind=target_account_kind, requested_execution_mode=execution_mode,
    )
    blocking.extend(broker_blocking)
    warning.extend(broker_warning)

    risk_snapshot, risk_blocking, risk_warning = _risk_snapshot_payload(
        session, account=account, target_account_kind=target_account_kind, requested_execution_mode=execution_mode,
    )
    blocking.extend(risk_blocking)
    warning.extend(risk_warning)
    if execution_mode == EXECUTION_MODE_LIVE and not risk_snapshot.get("effective_risk_explicit"):
        blocking.append("EXPLICIT_LIVE_RISK_REQUIRED")

    operational_snapshot, op_blocking, op_warning = _operational_snapshot_payload(
        session, strategy_definition_id=strategy_definition_id, account=account, target_account_kind=target_account_kind,
    )
    blocking.extend(op_blocking)
    warning.extend(op_warning)

    account_id = None
    user_id = None
    if account is not None:
        if isinstance(account, UserBrokerAccount):
            account_id = int(account.user_broker_account_id)
            user_id = int(account.user_id)
        elif isinstance(account, PaperAccount):
            account_id = int(account.account_id)
            user_id = account.user_id

    runtime_scope_hash = compute_runtime_scope_hash(
        user_id=user_id, account_kind=target_account_kind, account_id=account_id,
        strategy_id=strategy_definition_id, strategy_version=definition.definition_version,
        market_type=target_market_type, broker_code=target_broker_code, execution_mode=execution_mode,
    )

    # § STEP12-18R — Runtime Scope Conflict 재설계. 동일 Strategy가 서로
    # 다른 정상 Scope(다른 Account/User/Execution Mode/Version)에 각각
    # 등록되는 것은 정상이며 차단하지 않는다. 차단해야 하는 것은 오직
    # (a) 완전히 동일한 Scope의 중복 등록, (b) 같은 Account에 이미
    # 다른 Version이 등록된 상태에서 새 Version을 또 등록하려는 시도
    # (같은 물리적 대상에 대해 서로 다른 Version이 동시에 유효하다고
    # 주장하는 모순) 뿐이다.
    existing_same_hash = session.scalar(
        select(StrategyRuntimeRegistryEntity).where(StrategyRuntimeRegistryEntity.runtime_scope_hash == runtime_scope_hash)
    )
    if existing_same_hash is not None:
        blocking.append("RUNTIME_SCOPE_ALREADY_REGISTERED")

    if account_id is not None:
        same_account_stmt = select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == strategy_definition_id,
            StrategyRuntimeRegistryEntity.account_kind == target_account_kind,
        )
        if target_account_kind == ACCOUNT_KIND_USER_BROKER:
            same_account_stmt = same_account_stmt.where(
                StrategyRuntimeRegistryEntity.target_user_broker_account_id == account_id
            )
        else:
            same_account_stmt = same_account_stmt.where(
                StrategyRuntimeRegistryEntity.target_paper_account_id == account_id
            )
        existing_same_account = session.scalar(same_account_stmt)
        if existing_same_account is not None and existing_same_account.runtime_scope_hash != runtime_scope_hash:
            if existing_same_account.strategy_version != definition.definition_version:
                blocking.append("STRATEGY_VERSION_CONFLICT")
            else:
                blocking.append("RUNTIME_SCOPE_CONFLICT")

    return {
        "blocking": sorted(set(blocking)),
        "warning": sorted(set(warning) - set(blocking)),
        "missing": sorted(set(missing)),
        "account": account,
        "account_id": account_id,
        "user_id": user_id,
        "runtime_scope_hash": runtime_scope_hash,
        "account_snapshot_payload": _account_snapshot_payload(account, kind=target_account_kind),
        "broker_snapshot_payload": broker_snapshot,
        "risk_snapshot_payload": risk_snapshot,
        "operational_snapshot_payload": operational_snapshot,
    }


def compute_runtime_registration_history_event_hash(
    *,
    strategy_definition_id: int,
    runtime_scope_hash: str | None,
    event_type: str,
    previous_status: str | None,
    current_status: str,
    source_type: str,
    source_id: int,
    actor_id: str,
    occurred_at: datetime,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id, "runtime_scope_hash": runtime_scope_hash,
        "event_type": event_type, "previous_status": previous_status, "current_status": current_status,
        "source_type": source_type, "source_id": source_id, "actor_id": actor_id,
        "occurred_at": occurred_at.isoformat(), "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def _write_registration_history(
    session: Session,
    *,
    strategy_definition_id: int,
    runtime_scope_hash: str | None,
    event_type: str,
    previous_status: str | None,
    current_status: str,
    source_type: str,
    source_id: int,
    actor: str,
    occurred_at: datetime,
    metadata_payload: dict[str, Any],
) -> StrategyRuntimeRegistrationHistoryEntity:
    """§ STEP12-18R — 영속 불변 History(INSERT ONLY). Package/Decision/
    Commit 각각이 생성되는 바로 그 Transaction 안에서 호출된다(동적 합성
    없음). 이 함수는 add+flush만 수행하고 commit은 호출자(같은 Transaction
    의 최종 commit)에게 맡긴다 — History INSERT 실패가 호출자의 나머지
    작업과 함께 Rollback되도록 하기 위해서다."""
    event_hash = compute_runtime_registration_history_event_hash(
        strategy_definition_id=strategy_definition_id, runtime_scope_hash=runtime_scope_hash,
        event_type=event_type, previous_status=previous_status, current_status=current_status,
        source_type=source_type, source_id=source_id, actor_id=actor, occurred_at=occurred_at,
        algorithm_version=ALGORITHM_VERSION,
    )
    history = StrategyRuntimeRegistrationHistoryEntity(
        strategy_definition_id=strategy_definition_id, runtime_scope_hash=runtime_scope_hash,
        event_type=event_type, previous_status=previous_status, current_status=current_status,
        source_type=source_type, source_id=source_id, actor_id=actor, metadata_payload=metadata_payload,
        event_hash=event_hash, occurred_at=occurred_at,
    )
    session.add(history)
    session.flush()
    return history


def _to_history_dict(history: StrategyRuntimeRegistrationHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(history.history_id),
        "strategy_definition_id": history.strategy_definition_id,
        "runtime_scope_hash": history.runtime_scope_hash,
        "event_type": history.event_type,
        "previous_status": history.previous_status,
        "current_status": history.current_status,
        "source_type": history.source_type,
        "source_id": history.source_id,
        "actor_id": history.actor_id,
        "metadata_payload": history.metadata_payload,
        "event_hash": history.event_hash,
        "occurred_at": history.occurred_at,
    }


def run_create_runtime_registration_package(
    session: Session,
    strategy_definition_id: int,
    *,
    activation_commit_id: int,
    activation_decision_id: int,
    target_account_kind: str,
    target_user_broker_account_id: int | None = None,
    target_paper_account_id: int | None = None,
    target_market_type: str,
    target_broker_code: str,
    execution_mode: str,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    definition = session.get(StrategyDefinitionEntity, strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    if idempotency_key:
        existing = session.scalar(
            select(StrategyRuntimeRegistrationPackageEntity).where(
                StrategyRuntimeRegistrationPackageEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            same_request = (
                existing.strategy_definition_id == strategy_definition_id
                and existing.activation_commit_id == activation_commit_id
                and existing.activation_decision_id == activation_decision_id
                and existing.target_account_kind == target_account_kind
                and existing.target_user_broker_account_id == target_user_broker_account_id
                and existing.target_paper_account_id == target_paper_account_id
                and existing.target_market_type == target_market_type
                and existing.target_broker_code == target_broker_code
                and existing.execution_mode == execution_mode
            )
            if same_request:
                return _to_registration_package_dict(existing, idempotent_replay=True)
            raise RuntimeRegistrationError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")

    activation_blocking, activation_commit, activation_snapshot = _validate_activation_prerequisites(
        session, definition=definition, strategy_definition_id=strategy_definition_id, activation_commit_id=activation_commit_id,
    )
    if activation_commit is None:
        # Activation Commit 자체를 못 찾으면 나머지 검증을 계속할 근거가 없다.
        raise RuntimeRegistrationError("ACTIVATION_COMMIT_NOT_FOUND", f"Activation Commit not found: {activation_commit_id}")
    if activation_commit.activation_decision_id != activation_decision_id:
        raise RuntimeRegistrationError(
            "OWNERSHIP_MISMATCH", f"Activation Decision #{activation_decision_id}은 이 Activation Commit의 Decision이 아닙니다."
        )

    validation = _run_registration_validations(
        session, definition=definition, strategy_definition_id=strategy_definition_id, activation_commit=activation_commit,
        target_account_kind=target_account_kind, target_user_broker_account_id=target_user_broker_account_id,
        target_paper_account_id=target_paper_account_id, target_market_type=target_market_type,
        target_broker_code=target_broker_code, execution_mode=execution_mode,
    )
    blocking = sorted(set(activation_blocking) | set(validation["blocking"]))

    runtime_scope_payload = {
        "user_id": validation["user_id"], "account_kind": target_account_kind, "account_id": validation["account_id"],
        "strategy_id": strategy_definition_id, "strategy_version": definition.definition_version,
        "market_type": target_market_type, "broker_code": target_broker_code, "execution_mode": execution_mode,
    }

    registration_input_hash = compute_registration_input_hash(
        strategy_definition_id=strategy_definition_id, activation_commit_id=activation_commit_id,
        activation_decision_id=activation_decision_id, runtime_scope_payload=runtime_scope_payload,
        account_snapshot_payload=validation["account_snapshot_payload"],
        credential_snapshot_payload=validation["broker_snapshot_payload"],
        risk_snapshot_payload=validation["risk_snapshot_payload"],
        operational_snapshot_payload=validation["operational_snapshot_payload"],
        activation_snapshot_payload=activation_snapshot, blocking_reason_codes=blocking,
        warning_reason_codes=validation["warning"], missing_requirement_codes=validation["missing"],
        algorithm_version=ALGORITHM_VERSION,
    )

    readiness_status = REGISTRATION_READINESS_BLOCKED if blocking else REGISTRATION_READINESS_READY
    created_at = datetime.now(timezone.utc)

    package_uba_id = target_user_broker_account_id if (validation["account"] is not None and target_account_kind == ACCOUNT_KIND_USER_BROKER) else None
    package_paper_id = target_paper_account_id if (validation["account"] is not None and target_account_kind == ACCOUNT_KIND_PAPER) else None

    package = StrategyRuntimeRegistrationPackageEntity(
        strategy_definition_id=strategy_definition_id, activation_commit_id=activation_commit_id,
        activation_decision_id=activation_decision_id, target_user_id=validation["user_id"],
        target_account_kind=target_account_kind, target_user_broker_account_id=package_uba_id,
        target_paper_account_id=package_paper_id, target_market_type=target_market_type,
        target_broker_code=target_broker_code, execution_mode=execution_mode,
        strategy_version=definition.definition_version, runtime_scope_payload=runtime_scope_payload,
        runtime_scope_hash=validation["runtime_scope_hash"], account_snapshot_payload=validation["account_snapshot_payload"],
        credential_snapshot_payload=validation["broker_snapshot_payload"], risk_snapshot_payload=validation["risk_snapshot_payload"],
        operational_snapshot_payload=validation["operational_snapshot_payload"], activation_snapshot_payload=activation_snapshot,
        registration_readiness_status=readiness_status, blocking_reason_codes=blocking,
        warning_reason_codes=validation["warning"], missing_requirement_codes=validation["missing"],
        registration_input_hash=registration_input_hash, algorithm_version=ALGORITHM_VERSION, created_by=actor,
        created_at=created_at, idempotency_key=(idempotency_key or None),
    )
    try:
        session.add(package)
        session.flush()
        _write_registration_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=validation["runtime_scope_hash"],
            event_type="RUNTIME_REGISTRATION_REVIEW_CREATED", previous_status=None, current_status=readiness_status,
            source_type="PACKAGE", source_id=int(package.runtime_registration_package_id), actor=actor,
            occurred_at=created_at, metadata_payload={"blocking_reason_codes": blocking},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyRuntimeRegistrationPackageEntity).where(
                    StrategyRuntimeRegistrationPackageEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_registration_package_dict(conflict, idempotent_replay=True)
        raise RuntimeRegistrationError("DUPLICATE_RUNTIME_REGISTRATION_REVIEW", "동일 Package/History 저장 중 충돌이 발생했습니다.") from None
    session.refresh(package)
    return _to_registration_package_dict(package, idempotent_replay=False)


def _to_registration_package_dict(package: StrategyRuntimeRegistrationPackageEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "runtime_registration_package_id": int(package.runtime_registration_package_id),
        "strategy_definition_id": package.strategy_definition_id,
        "activation_commit_id": package.activation_commit_id,
        "activation_decision_id": package.activation_decision_id,
        "target_user_id": package.target_user_id,
        "target_account_kind": package.target_account_kind,
        "target_user_broker_account_id": package.target_user_broker_account_id,
        "target_paper_account_id": package.target_paper_account_id,
        "target_market_type": package.target_market_type,
        "target_broker_code": package.target_broker_code,
        "execution_mode": package.execution_mode,
        "strategy_version": package.strategy_version,
        "runtime_scope_payload": package.runtime_scope_payload,
        "runtime_scope_hash": package.runtime_scope_hash,
        "account_snapshot_payload": package.account_snapshot_payload,
        "credential_snapshot_payload": package.credential_snapshot_payload,
        "risk_snapshot_payload": package.risk_snapshot_payload,
        "operational_snapshot_payload": package.operational_snapshot_payload,
        "activation_snapshot_payload": package.activation_snapshot_payload,
        "registration_readiness_status": package.registration_readiness_status,
        "blocking_reason_codes": package.blocking_reason_codes,
        "warning_reason_codes": package.warning_reason_codes,
        "missing_requirement_codes": package.missing_requirement_codes,
        "registration_input_hash": package.registration_input_hash,
        "algorithm_version": package.algorithm_version,
        "created_by": package.created_by,
        "created_at": package.created_at,
        "idempotency_key": package.idempotency_key,
        "idempotent_replay": idempotent_replay,
    }


def check_runtime_registration_package_staleness(
    session: Session, package: StrategyRuntimeRegistrationPackageEntity
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    definition = session.get(StrategyDefinitionEntity, package.strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        return True, ["DEFINITION_MISSING"]
    if definition.definition_version != package.strategy_version:
        reasons.append("DEFINITION_VERSION_CHANGED")

    activation_commit = session.get(StrategyActivationCommitEntity, package.activation_commit_id)
    if activation_commit is None:
        reasons.append("ACTIVATION_COMMIT_MISSING")
    else:
        activation_package = session.get(StrategyActivationReviewPackageEntity, activation_commit.activation_review_package_id)
        if activation_package is not None:
            stale, _reasons = check_activation_package_staleness(session, activation_package)
            if stale:
                reasons.append("ACTIVATION_STALE")

    state = get_promotion_state(session, package.strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        reasons.append("PROMOTION_STATE_CHANGED")
    snapshot = package.activation_snapshot_payload or {}
    if state["status_version"] != snapshot.get("promotion_state_version"):
        reasons.append("PROMOTION_STATE_VERSION_CHANGED")
    if state["state_hash"] != snapshot.get("promotion_state_hash"):
        reasons.append("PROMOTION_STATE_HASH_CHANGED")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            reasons.append(f"LIFECYCLE_{lifecycle.lifecycle_status}")

    account, _account_blocking = _resolve_account(
        session, target_account_kind=package.target_account_kind,
        target_user_broker_account_id=package.target_user_broker_account_id,
        target_paper_account_id=package.target_paper_account_id,
    )
    current_account_snapshot = _account_snapshot_payload(account, kind=package.target_account_kind)
    if current_account_snapshot != package.account_snapshot_payload:
        reasons.append("ACCOUNT_SNAPSHOT_CHANGED")

    broker_snapshot, _bb, _bw = _broker_snapshot_payload(
        session, account=account, target_account_kind=package.target_account_kind,
        requested_execution_mode=package.execution_mode,
    )
    if broker_snapshot.get("verification_status") != package.credential_snapshot_payload.get("verification_status"):
        reasons.append("CREDENTIAL_SNAPSHOT_CHANGED")
    if broker_snapshot.get("key_version") != package.credential_snapshot_payload.get("key_version"):
        reasons.append("CREDENTIAL_VERSION_CHANGED")

    risk_snapshot, _rb, _rw = _risk_snapshot_payload(
        session, account=account, target_account_kind=package.target_account_kind,
        requested_execution_mode=package.execution_mode,
    )
    if risk_snapshot != package.risk_snapshot_payload:
        reasons.append("RISK_SNAPSHOT_CHANGED")

    operational_snapshot, _ob, _ow = _operational_snapshot_payload(
        session, strategy_definition_id=package.strategy_definition_id, account=account,
        target_account_kind=package.target_account_kind,
    )
    if operational_snapshot != package.operational_snapshot_payload:
        reasons.append("OPERATIONAL_SNAPSHOT_CHANGED")

    return len(reasons) > 0, reasons


def run_record_runtime_registration_decision(
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
    package = session.get(StrategyRuntimeRegistrationPackageEntity, package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise RuntimeRegistrationError("PACKAGE_NOT_FOUND", f"Runtime Registration Package not found: {package_id}")
    if decision_type not in REGISTRATION_DECISION_TYPES:
        raise RuntimeRegistrationError("INVALID_DECISION_TYPE", f"알 수 없는 Decision Type: {decision_type}")
    if reason_code not in REASON_CODES_BY_REGISTRATION_DECISION_TYPE.get(decision_type, frozenset()):
        raise RuntimeRegistrationError("INVALID_REASON_CODE", f"{decision_type}에 허용되지 않는 reason_code입니다: {reason_code}")
    if not reason_text or not reason_text.strip():
        raise RuntimeRegistrationError("REASON_TEXT_REQUIRED", "reason_text는 필수입니다.")

    existing_decision = session.scalar(
        select(StrategyRuntimeRegistrationDecisionEntity).where(
            StrategyRuntimeRegistrationDecisionEntity.runtime_registration_package_id == package_id
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
                return _to_registration_decision_dict(existing_decision, idempotent_replay=True)
            raise RuntimeRegistrationError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다."
            )
        raise RuntimeRegistrationError(
            "DUPLICATE_RUNTIME_REGISTRATION_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다."
        )

    stale, stale_reasons = check_runtime_registration_package_staleness(session, package)
    if stale:
        raise RuntimeRegistrationError(
            "STALE_RUNTIME_REGISTRATION_PACKAGE", f"Runtime Registration Package가 Stale 상태입니다: {', '.join(stale_reasons)}"
        )

    registration_ready = False
    if decision_type == REGISTRATION_DECISION_APPROVE:
        if package.registration_readiness_status != REGISTRATION_READINESS_READY:
            raise RuntimeRegistrationError(
                "PACKAGE_NOT_READY", f"Package 상태가 READY_FOR_RUNTIME_REGISTRATION이 아닙니다(현재: {package.registration_readiness_status})."
            )
        required_codes = {
            c["checklist_code"] for c in build_runtime_registration_checklist_template(package.execution_mode) if c["required"]
        }
        missing_confirmations = [c for c in required_codes if not checklist_confirmations.get(c)]
        if missing_confirmations:
            raise RuntimeRegistrationError(
                "INCOMPLETE_CHECKLIST", f"필수 Checklist 미확인 항목이 있습니다: {', '.join(sorted(missing_confirmations))}"
            )
        if package.warning_reason_codes and set(package.warning_reason_codes) - set(acknowledged_warnings) - {"ALL"}:
            if "ALL" not in acknowledged_warnings:
                raise RuntimeRegistrationError("WARNING_NOT_ACKNOWLEDGED", "모든 Warning을 확인(acknowledge)해야 합니다.")
        registration_ready = True

    same_actor_warning = actor == package.created_by
    decided_at = datetime.now(timezone.utc)
    decision_input_hash = compute_registration_decision_input_hash(
        runtime_registration_package_id=package_id, decision_type=decision_type, reason_code=reason_code,
        reason_text=reason_text, checklist_payload=checklist_confirmations,
        acknowledged_warnings_payload=acknowledged_warnings, decided_by=actor, decided_at=decided_at,
        algorithm_version=ALGORITHM_VERSION,
    )
    decision = StrategyRuntimeRegistrationDecisionEntity(
        runtime_registration_package_id=package_id, strategy_definition_id=strategy_definition_id,
        decision_type=decision_type, reason_code=reason_code, reason_text=reason_text,
        checklist_payload=checklist_confirmations, acknowledged_warnings_payload=acknowledged_warnings,
        same_actor_warning=same_actor_warning, decided_by=actor, decided_at=decided_at,
        decision_input_hash=decision_input_hash, registration_ready=registration_ready,
        idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
    )
    try:
        session.add(decision)
        session.flush()
        _write_registration_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=package.runtime_scope_hash,
            event_type=_HISTORY_EVENT_BY_DECISION_TYPE[decision_type], previous_status=package.registration_readiness_status,
            current_status=decision_type, source_type="DECISION", source_id=int(decision.runtime_registration_decision_id),
            actor=actor, occurred_at=decided_at, metadata_payload={"reason_code": reason_code},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = session.scalar(
            select(StrategyRuntimeRegistrationDecisionEntity).where(
                StrategyRuntimeRegistrationDecisionEntity.runtime_registration_package_id == package_id
            )
        )
        if conflict is not None:
            if idempotency_key and conflict.idempotency_key == idempotency_key:
                return _to_registration_decision_dict(conflict, idempotent_replay=True)
            raise RuntimeRegistrationError(
                "DUPLICATE_RUNTIME_REGISTRATION_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다."
            ) from None
        raise RuntimeRegistrationError("DUPLICATE_RUNTIME_REGISTRATION_HISTORY", "동일 Decision에 대한 History가 이미 존재합니다.") from None
    session.refresh(decision)
    return _to_registration_decision_dict(decision, idempotent_replay=False)


def _to_registration_decision_dict(decision: StrategyRuntimeRegistrationDecisionEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "runtime_registration_decision_id": int(decision.runtime_registration_decision_id),
        "runtime_registration_package_id": decision.runtime_registration_package_id,
        "strategy_definition_id": decision.strategy_definition_id,
        "decision_type": decision.decision_type,
        "reason_code": decision.reason_code,
        "reason_text": decision.reason_text,
        "checklist_payload": decision.checklist_payload,
        "acknowledged_warnings_payload": decision.acknowledged_warnings_payload,
        "same_actor_warning": decision.same_actor_warning,
        "decided_by": decision.decided_by,
        "decided_at": decision.decided_at,
        "decision_input_hash": decision.decision_input_hash,
        "registration_ready": decision.registration_ready,
        "idempotency_key": decision.idempotency_key,
        "algorithm_version": decision.algorithm_version,
        "idempotent_replay": idempotent_replay,
    }


def run_create_runtime_registration_commit(
    session: Session,
    strategy_definition_id: int,
    *,
    runtime_registration_package_id: int,
    runtime_registration_decision_id: int,
    registration_input_hash: str,
    decision_input_hash: str,
    commit_reason: str,
    confirmation_text: str,
    acknowledge_same_actor_warning: bool = False,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not commit_reason or not commit_reason.strip():
        raise RuntimeRegistrationError("COMMIT_REASON_REQUIRED", "commit_reason은 필수입니다.")
    if _normalize_confirmation_text(confirmation_text) != CONFIRMATION_TEXT_REQUIRED:
        raise RuntimeRegistrationError("INVALID_CONFIRMATION", f"확인값이 올바르지 않습니다('{CONFIRMATION_TEXT_REQUIRED}'를 입력하세요).")

    definition = session.scalar(
        select(StrategyDefinitionEntity)
        .where(StrategyDefinitionEntity.strategy_id == strategy_definition_id)
        .with_for_update()
    )
    if definition is None or definition.deleted_at is not None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    # § STEP12-18R — Promotion State 동시성 보호. `_ensure_and_lock_
    # promotion_state()`(promotion_commit.py 재사용)로 행을 FOR UPDATE
    # 잠근 뒤부터는, 이 Transaction이 끝날 때까지 다른 Session이 이
    # Strategy의 Promotion State를 바꿀 수 없다 — 이후 이 함수 안의 모든
    # `state`/`get_promotion_state()` 재조회는 이 잠금 덕분에 항상
    # 최신·안전한 값이다(동일 Transaction 내 재조회이므로 자기 잠금에
    # 막히지 않는다).
    promotion_state = _ensure_and_lock_promotion_state(session, strategy_definition_id, actor=actor)
    state = get_promotion_state(session, strategy_definition_id)
    if state["current_status"] != PROMOTION_STATE_ACTIVATED:
        raise RuntimeRegistrationError(
            "STRATEGY_NOT_ACTIVATED", f"Strategy Promotion State가 ACTIVATED가 아닙니다(현재: {state['current_status']})."
        )

    package = session.get(StrategyRuntimeRegistrationPackageEntity, runtime_registration_package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise RuntimeRegistrationError("PACKAGE_NOT_FOUND", f"Runtime Registration Package not found: {runtime_registration_package_id}")

    decision = session.get(StrategyRuntimeRegistrationDecisionEntity, runtime_registration_decision_id)
    if decision is None or decision.runtime_registration_package_id != runtime_registration_package_id:
        raise RuntimeRegistrationError("DECISION_NOT_FOUND", f"Runtime Registration Decision not found: {runtime_registration_decision_id}")
    if decision.decision_type != REGISTRATION_DECISION_APPROVE:
        raise RuntimeRegistrationError(
            "DECISION_TYPE_MISMATCH", f"Decision Type이 APPROVE_RUNTIME_REGISTRATION이 아닙니다(현재: {decision.decision_type})."
        )
    if not decision.registration_ready:
        raise RuntimeRegistrationError("REGISTRATION_NOT_READY", "이 Decision은 registration_ready=false입니다.")
    if package.registration_input_hash != registration_input_hash:
        raise RuntimeRegistrationError("READINESS_HASH_MISMATCH", "요청한 registration_input_hash가 Package의 값과 일치하지 않습니다.")
    if decision.decision_input_hash != decision_input_hash:
        raise RuntimeRegistrationError("READINESS_HASH_MISMATCH", "요청한 decision_input_hash가 Decision의 값과 일치하지 않습니다.")
    if decision.same_actor_warning and not acknowledge_same_actor_warning:
        raise RuntimeRegistrationError(
            "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED", "Package 생성자와 결정자가 동일합니다 — acknowledge_same_actor_warning=true가 필요합니다."
        )

    # § STEP12-18R — Idempotency 판정을 Package당 UNIQUE 충돌보다 먼저
    # 수행한다. `strategy_definition_id`는 더 이상 단독 UNIQUE가 아니므로
    # (동일 Strategy가 여러 Scope에 등록 가능), idempotency_key는 Key
    # 자체로 조회하고(어느 Strategy/Package였든) 요청 필드를 직접
    # 비교한다 — 같은 Key라도 입력이 다르면 IDEMPOTENCY_CONFLICT.
    if idempotency_key:
        existing_by_key = session.scalar(
            select(StrategyRuntimeRegistrationCommitEntity).where(
                StrategyRuntimeRegistrationCommitEntity.idempotency_key == idempotency_key
            )
        )
        if existing_by_key is not None:
            same_request = (
                existing_by_key.strategy_definition_id == strategy_definition_id
                and existing_by_key.runtime_registration_package_id == runtime_registration_package_id
                and existing_by_key.runtime_registration_decision_id == runtime_registration_decision_id
                and existing_by_key.registration_input_hash == registration_input_hash
                and existing_by_key.decision_input_hash == decision_input_hash
            )
            if same_request:
                return _to_registration_commit_dict(session, existing_by_key, idempotent_replay=True)
            raise RuntimeRegistrationError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다."
            )

    # Package당 Commit 1개(§ `uq_runtime_reg_commit_package`) — 이 Package가
    # 이미 Commit됐다면(다른 요청으로) 명확한 Domain Error로 알린다.
    existing_for_package = session.scalar(
        select(StrategyRuntimeRegistrationCommitEntity).where(
            StrategyRuntimeRegistrationCommitEntity.runtime_registration_package_id == runtime_registration_package_id
        )
    )
    if existing_for_package is not None:
        raise RuntimeRegistrationError(
            "ALREADY_REGISTERED", f"Runtime Registration Package #{runtime_registration_package_id}은 이미 Commit이 존재합니다."
        )

    stale, stale_reasons = check_runtime_registration_package_staleness(session, package)
    if stale:
        raise RuntimeRegistrationError(
            "STALE_RUNTIME_REGISTRATION_PACKAGE", f"Runtime Registration Package가 Stale 상태입니다: {', '.join(stale_reasons)}"
        )

    committed_at = datetime.now(timezone.utc)
    confirmation_hash = _hash(_canonical_json({"confirmation_text": _normalize_confirmation_text(confirmation_text)}))
    registration_commit_hash = compute_registration_commit_hash(
        strategy_definition_id=strategy_definition_id, activation_commit_id=package.activation_commit_id,
        runtime_registration_package_id=runtime_registration_package_id, registration_input_hash=registration_input_hash,
        runtime_registration_decision_id=runtime_registration_decision_id, decision_input_hash=decision_input_hash,
        runtime_scope_hash=package.runtime_scope_hash, committed_by=actor, committed_at=committed_at,
        confirmation_hash=confirmation_hash, algorithm_version=ALGORITHM_VERSION,
    )

    commit = StrategyRuntimeRegistrationCommitEntity(
        strategy_definition_id=strategy_definition_id, activation_commit_id=package.activation_commit_id,
        runtime_registration_package_id=runtime_registration_package_id,
        runtime_registration_decision_id=runtime_registration_decision_id, target_user_id=package.target_user_id,
        account_kind=package.target_account_kind, target_user_broker_account_id=package.target_user_broker_account_id,
        target_paper_account_id=package.target_paper_account_id, market_type=package.target_market_type,
        broker_code=package.target_broker_code, execution_mode=package.execution_mode,
        strategy_version=package.strategy_version, runtime_scope_payload=package.runtime_scope_payload,
        runtime_scope_hash=package.runtime_scope_hash, account_snapshot_payload=package.account_snapshot_payload,
        credential_snapshot_payload=package.credential_snapshot_payload, risk_snapshot_payload=package.risk_snapshot_payload,
        operational_snapshot_payload=package.operational_snapshot_payload, registration_input_hash=registration_input_hash,
        decision_input_hash=decision_input_hash, confirmation_hash=confirmation_hash,
        registration_commit_hash=registration_commit_hash, committed_by=actor, committed_at=committed_at,
        idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
    )

    try:
        session.add(commit)
        session.flush()

        registry = StrategyRuntimeRegistryEntity(
            strategy_definition_id=strategy_definition_id, runtime_registration_commit_id=int(commit.runtime_registration_commit_id),
            runtime_scope_payload=package.runtime_scope_payload, runtime_scope_hash=package.runtime_scope_hash,
            strategy_version=package.strategy_version, account_kind=package.target_account_kind,
            target_user_broker_account_id=package.target_user_broker_account_id,
            target_paper_account_id=package.target_paper_account_id, market_type=package.target_market_type,
            broker_code=package.target_broker_code, execution_mode=package.execution_mode,
            status=REGISTRY_STATUS_REGISTERED, enabled=False, running=False, registered_by=actor,
            registered_at=committed_at, created_at=committed_at,
        )
        session.add(registry)
        session.flush()

        # § 명세 §13 — AccountStrategyLink가 없으면 비활성 상태로 생성
        # 가능(자동 활성화 절대 금지). 이미 활성 Link가 있으면 Package
        # 생성 시점에 이미 ACCOUNT_STRATEGY_LINK_CONFLICT로 차단됐어야
        # 하므로(§ _operational_snapshot_payload), 여기서는 없을 때만
        # 비활성으로 신규 생성한다.
        link_exists = session.scalar(
            select(AccountStrategyLinkEntity).where(
                AccountStrategyLinkEntity.strategy_id == strategy_definition_id,
                AccountStrategyLinkEntity.paper_account_id == package.target_paper_account_id
                if package.target_paper_account_id is not None
                else AccountStrategyLinkEntity.user_broker_account_id == package.target_user_broker_account_id,
            ).limit(1)
        )
        if link_exists is None and package.target_user_id is not None:
            link = AccountStrategyLinkEntity(
                strategy_id=strategy_definition_id, user_id=package.target_user_id,
                paper_account_id=package.target_paper_account_id,
                user_broker_account_id=package.target_user_broker_account_id, is_active=False, created_by=actor,
            )
            session.add(link)
            session.flush()

        _write_registration_history(
            session, strategy_definition_id=strategy_definition_id, runtime_scope_hash=package.runtime_scope_hash,
            event_type="RUNTIME_REGISTERED", previous_status=decision.decision_type, current_status="REGISTERED",
            source_type="COMMIT", source_id=int(commit.runtime_registration_commit_id), actor=actor,
            occurred_at=committed_at,
            metadata_payload={"registration_commit_hash": registration_commit_hash, "registry_status": REGISTRY_STATUS_REGISTERED},
        )

        # § STEP12-19 Carry-forward(3.1) — Transaction 경계 명확화. Audit는
        # `auto_commit=False`로 add+flush만 수행하고, 이 함수(최상위
        # Application Service)가 아래에서 정확히 한 번 commit한다 — 이전
        # STEP12-18R처럼 AuditLogService의 내부 commit에 암묵적으로
        # 의존하지 않는다(Domain Service가 스스로 commit을 트리거하는
        # 구조는 상위 계층의 Transaction 경계를 예측 불가능하게 만든다).
        AuditLogService(session).record(
            event_type="RUNTIME_REGISTERED", actor=actor, strategy_id=str(strategy_definition_id),
            detail={
                "runtime_registration_commit_id": int(commit.runtime_registration_commit_id),
                "registration_commit_hash": registration_commit_hash,
                "runtime_scope_hash": package.runtime_scope_hash,
            },
            auto_commit=False,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyRuntimeRegistrationCommitEntity).where(
                    StrategyRuntimeRegistrationCommitEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_registration_commit_dict(session, conflict, idempotent_replay=True)
        package_conflict = session.scalar(
            select(StrategyRuntimeRegistrationCommitEntity).where(
                StrategyRuntimeRegistrationCommitEntity.runtime_registration_package_id == runtime_registration_package_id
            )
        )
        if package_conflict is not None:
            raise RuntimeRegistrationError(
                "ALREADY_REGISTERED", f"Runtime Registration Package #{runtime_registration_package_id}은 이미 Commit이 존재합니다."
            ) from None
        scope_conflict = session.scalar(
            select(StrategyRuntimeRegistrationCommitEntity).where(
                StrategyRuntimeRegistrationCommitEntity.runtime_scope_hash == package.runtime_scope_hash
            )
        )
        if scope_conflict is not None:
            raise RuntimeRegistrationError(
                "RUNTIME_SCOPE_ALREADY_REGISTERED", "동일 Runtime Scope가 이미 등록되어 있습니다."
            ) from None
        raise RuntimeRegistrationError("DUPLICATE_RUNTIME_REGISTRATION_COMMIT", "동일 Runtime Registration Commit이 이미 존재합니다.") from None

    session.refresh(commit)
    return _to_registration_commit_dict(session, commit, idempotent_replay=False)


def _to_registration_commit_dict(
    session: Session, commit: StrategyRuntimeRegistrationCommitEntity, *, idempotent_replay: bool
) -> dict[str, Any]:
    registry = session.scalar(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.runtime_registration_commit_id == commit.runtime_registration_commit_id
        )
    )
    return {
        "runtime_registration_commit_id": int(commit.runtime_registration_commit_id),
        "strategy_definition_id": commit.strategy_definition_id,
        "activation_commit_id": commit.activation_commit_id,
        "runtime_registration_package_id": commit.runtime_registration_package_id,
        "runtime_registration_decision_id": commit.runtime_registration_decision_id,
        "registration_commit_hash": commit.registration_commit_hash,
        "committed_by": commit.committed_by,
        "committed_at": commit.committed_at,
        "registration_status": REGISTRY_STATUS_REGISTERED,
        "runtime_status": FIXED_RUNTIME_STATUS,
        "scheduler_status": FIXED_SCHEDULER_STATUS,
        "broker_connection_status": FIXED_BROKER_CONNECTION_STATUS,
        "market_data_status": FIXED_MARKET_DATA_STATUS,
        "signal_status": FIXED_SIGNAL_STATUS,
        "order_execution_status": FIXED_ORDER_EXECUTION_STATUS,
        "trading_status": FIXED_TRADING_STATUS,
        "next_action": FIXED_NEXT_ACTION,
        "registry_enabled": bool(registry.enabled) if registry is not None else False,
        "registry_running": bool(registry.running) if registry is not None else False,
        "idempotent_replay": idempotent_replay,
    }


def get_runtime_registration_package(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = session.get(StrategyRuntimeRegistrationPackageEntity, package_id)
    if package is None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Package not found: {package_id}")
    if strategy_definition_id is not None and package.strategy_definition_id != strategy_definition_id:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Package not found: {package_id}")
    result = _to_registration_package_dict(package, idempotent_replay=False)
    stale, stale_reasons = check_runtime_registration_package_staleness(session, package)
    commit = session.scalar(
        select(StrategyRuntimeRegistrationCommitEntity).where(
            StrategyRuntimeRegistrationCommitEntity.runtime_registration_package_id == package_id
        )
    )
    decision = session.scalar(
        select(StrategyRuntimeRegistrationDecisionEntity).where(
            StrategyRuntimeRegistrationDecisionEntity.runtime_registration_package_id == package_id
        )
    )
    if commit is not None:
        current_effective_status = "RUNTIME_REGISTERED"
    elif stale:
        current_effective_status = "STALE"
    elif decision is not None:
        current_effective_status = "DECIDED"
    else:
        current_effective_status = package.registration_readiness_status
    result.update(
        {
            "created_readiness_status": package.registration_readiness_status,
            "current_effective_status": current_effective_status,
            "stale": stale,
            "stale_reasons": stale_reasons,
            "decided": decision is not None,
            "registered": commit is not None,
        }
    )
    return result


def list_runtime_registration_packages(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyRuntimeRegistrationPackageEntity)
        .where(StrategyRuntimeRegistrationPackageEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyRuntimeRegistrationPackageEntity.runtime_registration_package_id.desc())
    )
    return [_to_registration_package_dict(r, idempotent_replay=False) for r in rows]


def get_runtime_registration_package_checklist(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyRuntimeRegistrationPackageEntity, package_id)
    if package is None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Package not found: {package_id}")
    decision = session.scalar(
        select(StrategyRuntimeRegistrationDecisionEntity).where(
            StrategyRuntimeRegistrationDecisionEntity.runtime_registration_package_id == package_id
        )
    )
    return {
        "runtime_registration_package_id": package_id,
        "checklist_template": build_runtime_registration_checklist_template(package.execution_mode),
        "checklist_confirmations": decision.checklist_payload if decision is not None else {},
    }


def get_runtime_registration_package_staleness(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyRuntimeRegistrationPackageEntity, package_id)
    if package is None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Package not found: {package_id}")
    stale, reasons = check_runtime_registration_package_staleness(session, package)
    return {"runtime_registration_package_id": package_id, "stale": stale, "reasons": reasons}


def get_runtime_registration_decision(session: Session, package_id: int) -> dict[str, Any] | None:
    decision = session.scalar(
        select(StrategyRuntimeRegistrationDecisionEntity).where(
            StrategyRuntimeRegistrationDecisionEntity.runtime_registration_package_id == package_id
        )
    )
    if decision is None:
        return None
    return _to_registration_decision_dict(decision, idempotent_replay=False)


def get_runtime_registration_commit(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyRuntimeRegistrationCommitEntity, commit_id)
    if commit is None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Commit not found: {commit_id}")
    return _to_registration_commit_dict(session, commit, idempotent_replay=False)


def list_runtime_registration_commits(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyRuntimeRegistrationCommitEntity)
        .where(StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyRuntimeRegistrationCommitEntity.runtime_registration_commit_id.desc())
    )
    return [_to_registration_commit_dict(session, r, idempotent_replay=False) for r in rows]


def get_runtime_registration_commit_provenance(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyRuntimeRegistrationCommitEntity, commit_id)
    if commit is None:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise RuntimeRegistrationError("NOT_FOUND", f"Runtime Registration Commit not found: {commit_id}")
    return {
        "runtime_registration_commit_id": int(commit.runtime_registration_commit_id),
        "runtime_scope_payload": commit.runtime_scope_payload,
        "risk_snapshot_payload": commit.risk_snapshot_payload,
        "account_snapshot_payload": commit.account_snapshot_payload,
        "credential_snapshot_payload": commit.credential_snapshot_payload,
        "registration_commit_hash": commit.registration_commit_hash,
    }


def get_runtime_registration_status(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    """§ STEP12-18R — 동일 Strategy가 여러 Scope에 등록될 수 있으므로,
    이 Status는 "가장 최근 Commit 1개"를 대표로 보여주되
    `total_registrations`로 실제 등록 개수를 함께 노출한다(전체 목록은
    `list_runtime_registration_commits()`로 조회)."""
    commits = session.scalars(
        select(StrategyRuntimeRegistrationCommitEntity)
        .where(StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyRuntimeRegistrationCommitEntity.committed_at.desc())
    ).all()
    state = get_promotion_state(session, strategy_definition_id)
    if not commits:
        return {
            "strategy_definition_id": strategy_definition_id, "registered": False, "total_registrations": 0,
            "runtime_registration_commit_id": None, "strategy_promotion_status": state["current_status"],
            "runtime_status": FIXED_RUNTIME_STATUS, "scheduler_status": FIXED_SCHEDULER_STATUS,
            "broker_connection_status": FIXED_BROKER_CONNECTION_STATUS, "market_data_status": FIXED_MARKET_DATA_STATUS,
            "signal_status": FIXED_SIGNAL_STATUS, "order_execution_status": FIXED_ORDER_EXECUTION_STATUS,
            "trading_status": FIXED_TRADING_STATUS,
            "next_action": "REVIEW_RUNTIME_REGISTRATION" if state["current_status"] == PROMOTION_STATE_ACTIVATED else "REVIEW_ACTIVATION",
        }
    result = _to_registration_commit_dict(session, commits[0], idempotent_replay=False)
    result["registered"] = True
    result["total_registrations"] = len(commits)
    result["strategy_definition_id"] = strategy_definition_id
    result["strategy_promotion_status"] = state["current_status"]
    return result


def get_runtime_registration_history(
    session: Session,
    strategy_definition_id: int,
    *,
    runtime_scope_hash: str | None = None,
    runtime_registration_commit_id: int | None = None,
    account_id: int | None = None,
    execution_mode: str | None = None,
) -> list[dict[str, Any]]:
    """§ STEP12-19 Carry-forward(3.2) — 영속 불변 `strategy_runtime_
    registration_history` 테이블을 조회한다(동적 합성 아님).
    `runtime_scope_hash`로 필터링하면 Cross-Scope 혼합 없이 정확히 한
    Scope의 이력만 반환한다. `runtime_registration_commit_id`/
    `account_id`/`execution_mode`는 해당 Commit(들)의 `runtime_scope_hash`
    로 변환해 동일하게 필터링한다(History 테이블 자체에는 account_id/
    execution_mode 컬럼이 없으므로 Commit을 경유해 Scope Hash를 얻는다).
    `occurred_at ASC, history_id ASC`로 결정적 정렬한다."""
    stmt = select(StrategyRuntimeRegistrationHistoryEntity).where(
        StrategyRuntimeRegistrationHistoryEntity.strategy_definition_id == strategy_definition_id
    )

    scope_hashes: set[str] | None = None
    if runtime_scope_hash is not None:
        scope_hashes = {runtime_scope_hash}
    if runtime_registration_commit_id is not None or account_id is not None or execution_mode is not None:
        commit_stmt = select(StrategyRuntimeRegistrationCommitEntity.runtime_scope_hash).where(
            StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == strategy_definition_id
        )
        if runtime_registration_commit_id is not None:
            commit_stmt = commit_stmt.where(
                StrategyRuntimeRegistrationCommitEntity.runtime_registration_commit_id == runtime_registration_commit_id
            )
        if account_id is not None:
            commit_stmt = commit_stmt.where(
                (StrategyRuntimeRegistrationCommitEntity.target_user_broker_account_id == account_id)
                | (StrategyRuntimeRegistrationCommitEntity.target_paper_account_id == account_id)
            )
        if execution_mode is not None:
            commit_stmt = commit_stmt.where(StrategyRuntimeRegistrationCommitEntity.execution_mode == execution_mode)
        matched = set(session.scalars(commit_stmt).all())
        scope_hashes = matched if scope_hashes is None else (scope_hashes & matched)

    if scope_hashes is not None:
        if not scope_hashes:
            return []
        stmt = stmt.where(StrategyRuntimeRegistrationHistoryEntity.runtime_scope_hash.in_(scope_hashes))

    rows = session.scalars(
        stmt.order_by(
            StrategyRuntimeRegistrationHistoryEntity.occurred_at.asc(),
            StrategyRuntimeRegistrationHistoryEntity.history_id.asc(),
        )
    )
    return [_to_history_dict(h) for h in rows]


def get_runtime_registration_scopes(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    """§ STEP12-19 Carry-forward(3.3) — 다중 Runtime Scope 목록. Strategy
    하나가 여러 Scope(Account/User/Execution Mode/Version)에 등록될 수
    있으므로, Scope별 등록 상태를 개별 행으로 반환한다(단일 최신 Status
    카드로는 표현할 수 없는 정보)."""
    commits = session.scalars(
        select(StrategyRuntimeRegistrationCommitEntity)
        .where(StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyRuntimeRegistrationCommitEntity.committed_at.asc())
    ).all()
    scopes: list[dict[str, Any]] = []
    for commit in commits:
        registry = session.scalar(
            select(StrategyRuntimeRegistryEntity).where(
                StrategyRuntimeRegistryEntity.runtime_registration_commit_id == commit.runtime_registration_commit_id
            )
        )
        scopes.append(
            {
                "runtime_scope_hash": commit.runtime_scope_hash,
                "runtime_registration_commit_id": int(commit.runtime_registration_commit_id),
                "runtime_registry_id": int(registry.runtime_registry_id) if registry is not None else None,
                "target_user_id": commit.target_user_id,
                "account_kind": commit.account_kind,
                "target_user_broker_account_id": commit.target_user_broker_account_id,
                "target_paper_account_id": commit.target_paper_account_id,
                "market_type": commit.market_type,
                "broker_code": commit.broker_code,
                "execution_mode": commit.execution_mode,
                "strategy_version": commit.strategy_version,
                "registration_status": REGISTRY_STATUS_REGISTERED,
                "registry_enabled": bool(registry.enabled) if registry is not None else False,
                "registry_running": bool(registry.running) if registry is not None else False,
                "committed_at": commit.committed_at,
            }
        )
    return scopes
