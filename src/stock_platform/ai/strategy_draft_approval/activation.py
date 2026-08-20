"""STEP 12-17 — Activation Review & Activation Commit.

PROMOTION_COMMITTED 상태인 Strategy Definition을 대상으로 계좌·시장·
브로커·리스크·운영 준비 상태를 검증하는 불변 Activation Review
Package를 생성하고, 관리자의 Human Activation Decision을 거쳐, 명시적
Activation Commit으로 Strategy Promotion State를 ACTIVATED로 전이한다.

Runtime 등록/시작, Scheduler 등록, Broker 연결/로그인, 주문 실행,
Paper/Live Trading 시작은 전혀 수행하지 않는다(§ 모듈 최상단 "Activation
이 의미하지 않는 것"). Credential은 복호화하지 않고 `BrokerCredentialVault
Service.status()`가 제공하는 metadata(검증 상태/마스킹된 식별자)만
읽는다 — 평문 Secret은 이 모듈 어디에서도 다루지 않는다.

핵심 도메인 결정 — Candidate Lifecycle에는 절대 WRITE하지 않음(§
STEP12-16R과 동일한 원칙 유지): 읽기 전용 게이팅에만 사용한다. Strategy
Promotion State가 이번 STEP에서도 공식 Source of Truth이며,
`PROMOTION_COMMITTED -> ACTIVATION_REVIEW -> ACTIVATED` 전이만 이번
STEP에서 실제로 사용한다(그 이후 상태는 Enum 값만 존재, 향후 STEP 전용).

재사용(중복 생성 금지 확인):
- Strategy Promotion State/History 테이블은 STEP12-16R에서 이미 생성된
  `strategy_promotion_state`/`strategy_promotion_history`를 그대로
  재사용한다(신규 History 테이블 생성 없음). `_ensure_and_lock_promotion_
  state()`, `compute_promotion_state_hash()`, `compute_promotion_state_
  event_hash()`는 `promotion_commit.py`의 기존 구현을 그대로 가져와
  쓴다(복제 없음).
- Market/Broker 호환성은 `strategy_deployment/ownership.py`의 기존
  `market_compatible()`을 재사용한다(새 호환성 로직 없음).
- Effective Risk Setting은 `risk_engine/resolved_policy.py`의 기존
  `ResolvedRiskPolicyResolver`를 재사용한다(재계산 없음).
- Kill Switch는 `risk_engine/kill_switch_service.py`의 기존
  `KillSwitchService.is_active_for_scopes()`를 재사용한다.
- Recovery Conflict는 `broker/recovery_lock.py`의 기존
  `RecoveryAccountLockService.is_trading_paused()`를 재사용한다.
- Credential 상태는 `broker/credential_vault_service.py`의 기존
  `BrokerCredentialVaultService.status()`(복호화하지 않는 안전한 조회
  경로)를 재사용한다 — `decrypt_payload()`는 이 모듈에서 절대 호출하지
  않는다.
- Deployment/Runtime 등록 여부 조회는 기존 `StrategyDeploymentEntity`/
  `AccountStrategyLinkEntity`를 읽기 전용으로 조회한다(신규 Runtime
  등록 로직 없음).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft_approval.activation_entities import (
    ACCOUNT_KIND_PAPER,
    ACCOUNT_KIND_USER_BROKER,
    ACCOUNT_KIND_VALUES,
    ACTIVATION_DECISION_APPROVE,
    ACTIVATION_DECISION_REJECT,
    ACTIVATION_DECISION_REQUEST_CHANGES,
    ACTIVATION_DECISION_TYPES,
    ACTIVATION_READINESS_BLOCKED,
    ACTIVATION_READINESS_READY,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_PAPER,
    EXECUTION_MODE_VALUES,
    StrategyActivationCommitEntity,
    StrategyActivationDecisionEntity,
    StrategyActivationReviewPackageEntity,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.decision_package import _STALE_LIFECYCLE_STATUSES
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    _ensure_and_lock_promotion_state,
    compute_promotion_state_event_hash,
    compute_promotion_state_hash,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit_entities import (
    StrategyPromotionCommitEntity,
)
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
    PROMOTION_STATE_ACTIVATED,
    PROMOTION_STATE_ACTIVATION_REVIEW,
    PROMOTION_STATE_PROMOTION_COMMITTED,
    StrategyPromotionHistoryEntity,
    StrategyPromotionStateEntity,
)
from stock_platform.broker.credential_vault_service import BrokerCredentialVaultService
from stock_platform.broker.recovery_lock import RecoveryAccountLockService
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity
from stock_platform.strategy_deployment.ownership import market_compatible
from stock_platform.trading.account_identity import (
    paper_kill_switch_scope,
    uba_kill_switch_scope,
)
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

ALGORITHM_VERSION = "1.0.0"
CHECKLIST_TEMPLATE_VERSION = "1.0.0"
CONFIRMATION_TEXT_REQUIRED = "ACTIVATE"

# § "ACTIVATED가 의미하지 않는 것" — 고정 응답 필드(§ 명세 "Activation
# 결과"). 이 STEP에서는 절대 시작되지 않는다.
FIXED_DEPLOYMENT_STATUS = "NOT_STARTED"
FIXED_RUNTIME_STATUS = "NOT_REGISTERED"
FIXED_SCHEDULER_STATUS = "NOT_REGISTERED"
FIXED_BROKER_CONNECTION_STATUS = "NOT_STARTED"
FIXED_ORDER_EXECUTION_STATUS = "DISABLED"
FIXED_NEXT_ACTION = "REVIEW_RUNTIME_REGISTRATION"

# § Transition Map 명시(§ STEP12-16R 인수 조건 4) — Enum 존재만으로
# 자동 전이를 허용하지 않는다. 이번 STEP이 실제로 사용하는 전이만 명시.
_ALLOWED_ACTIVATION_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    PROMOTION_STATE_PROMOTION_COMMITTED: frozenset({PROMOTION_STATE_ACTIVATION_REVIEW}),
    PROMOTION_STATE_ACTIVATION_REVIEW: frozenset({PROMOTION_STATE_ACTIVATED}),
}


def _can_transition_activation_state(from_status: str, to_status: str) -> bool:
    return to_status in _ALLOWED_ACTIVATION_STATE_TRANSITIONS.get(from_status, frozenset())


class ActivationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


REASON_CODES_BY_ACTIVATION_DECISION_TYPE: dict[str, frozenset[str]] = {
    ACTIVATION_DECISION_APPROVE: frozenset(
        {
            "ACTIVATION_REQUIREMENTS_VERIFIED", "ACCOUNT_AND_RISK_REVIEW_COMPLETED",
            "LIVE_SAFETY_REVIEW_COMPLETED", "PAPER_ACTIVATION_REVIEW_COMPLETED", "READY_FOR_ACTIVATION_COMMIT",
        }
    ),
    ACTIVATION_DECISION_REQUEST_CHANGES: frozenset(
        {
            "ACCOUNT_CONFIGURATION_REQUIRED", "CREDENTIAL_VERIFICATION_REQUIRED",
            "RISK_LIMIT_ADJUSTMENT_REQUIRED", "MARKET_BROKER_MISMATCH",
            "TRADING_FLAG_CONFIGURATION_REQUIRED", "RUNTIME_SCOPE_CONFLICT",
            "RECOVERY_CONFLICT_REVIEW_REQUIRED", "STRATEGY_CONFIGURATION_CLARIFICATION",
        }
    ),
    ACTIVATION_DECISION_REJECT: frozenset(
        {
            "PROMOTION_INVALID", "ACCOUNT_NOT_ELIGIBLE", "UNACCEPTABLE_RISK", "CREDENTIAL_INVALID",
            "POLICY_VIOLATION", "LIVE_TRADING_NOT_ALLOWED", "STRATEGY_REVOKED", "DUPLICATE_ACTIVATION",
        }
    ),
}


def _normalize_confirmation_text(value: str) -> str:
    return (value or "").strip().upper()


# ---------------------------------------------------------------------------
# Hash 계산 — Canonical JSON(backtest_spec._canonical_json/_hash 재사용).
# ---------------------------------------------------------------------------


def compute_activation_review_input_hash(
    *,
    strategy_definition_id: int,
    promotion_commit_id: int,
    target_market_type: str,
    target_broker_code: str,
    target_account_kind: str,
    target_user_broker_account_id: int | None,
    target_paper_account_id: int | None,
    requested_execution_mode: str,
    requested_runtime_scope_payload: dict[str, Any],
    requested_capital_limit: str | None,
    effective_risk_snapshot_payload: dict[str, Any],
    account_snapshot_payload: dict[str, Any],
    broker_snapshot_payload: dict[str, Any],
    operational_snapshot_payload: dict[str, Any],
    blocking_reason_codes: list[str],
    warning_reason_codes: list[str],
    missing_requirement_codes: list[str],
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "promotion_commit_id": promotion_commit_id,
        "target_market_type": target_market_type,
        "target_broker_code": target_broker_code,
        "target_account_kind": target_account_kind,
        "target_user_broker_account_id": target_user_broker_account_id,
        "target_paper_account_id": target_paper_account_id,
        "requested_execution_mode": requested_execution_mode,
        "requested_runtime_scope_payload": requested_runtime_scope_payload,
        "requested_capital_limit": requested_capital_limit,
        "effective_risk_snapshot_payload": effective_risk_snapshot_payload,
        "account_snapshot_payload": account_snapshot_payload,
        "broker_snapshot_payload": broker_snapshot_payload,
        "operational_snapshot_payload": operational_snapshot_payload,
        "blocking_reason_codes": sorted(blocking_reason_codes),
        "warning_reason_codes": sorted(warning_reason_codes),
        "missing_requirement_codes": sorted(missing_requirement_codes),
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_activation_decision_input_hash(
    *,
    activation_review_package_id: int,
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
        "activation_review_package_id": activation_review_package_id,
        "decision_type": decision_type,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "checklist_payload": checklist_payload,
        "acknowledged_warnings_payload": sorted(acknowledged_warnings_payload),
        "decided_by": decided_by,
        "decided_at": decided_at.isoformat(),
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_activation_commit_hash(
    *,
    strategy_definition_id: int,
    definition_version: int | None,
    definition_hash: str | None,
    executable_hash: str | None,
    promotion_commit_id: int,
    promotion_commit_hash: str,
    activation_review_package_id: int,
    review_input_hash: str,
    activation_decision_id: int,
    decision_input_hash: str,
    target_market_type: str,
    target_broker_code: str,
    target_account_kind: str,
    target_user_broker_account_id: int | None,
    execution_mode: str,
    runtime_scope_hash: str,
    risk_snapshot_hash: str,
    account_snapshot_hash: str,
    credential_snapshot_hash: str,
    previous_promotion_status: str,
    committed_promotion_status: str,
    committed_by: str,
    committed_at: datetime,
    confirmation_hash: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "definition_version": definition_version,
        "definition_hash": definition_hash,
        "executable_hash": executable_hash,
        "promotion_commit_id": promotion_commit_id,
        "promotion_commit_hash": promotion_commit_hash,
        "activation_review_package_id": activation_review_package_id,
        "review_input_hash": review_input_hash,
        "activation_decision_id": activation_decision_id,
        "decision_input_hash": decision_input_hash,
        "target_market_type": target_market_type,
        "target_broker_code": target_broker_code,
        "target_account_kind": target_account_kind,
        "target_user_broker_account_id": target_user_broker_account_id,
        "execution_mode": execution_mode,
        "runtime_scope_hash": runtime_scope_hash,
        "risk_snapshot_hash": risk_snapshot_hash,
        "account_snapshot_hash": account_snapshot_hash,
        "credential_snapshot_hash": credential_snapshot_hash,
        "previous_promotion_status": previous_promotion_status,
        "committed_promotion_status": committed_promotion_status,
        "committed_by": committed_by,
        "committed_at": committed_at.isoformat(),
        "confirmation_hash": confirmation_hash,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


# ---------------------------------------------------------------------------
# Checklist Template — 공통 + PAPER/LIVE 추가(§ 명세 "Activation Checklist").
# ---------------------------------------------------------------------------


def build_activation_checklist_template(execution_mode: str) -> list[dict[str, Any]]:
    items = [
        {"checklist_code": "PROMOTION_COMMIT_CONFIRMED", "required": True, "question": "Promotion Commit을 확인했는가"},
        {"checklist_code": "DEFINITION_VERSION_CONFIRMED", "required": True, "question": "Strategy Definition Version을 확인했는가"},
        {"checklist_code": "EXECUTABLE_HASH_CONFIRMED", "required": True, "question": "Executable Hash를 확인했는가"},
        {"checklist_code": "MARKET_BROKER_COMPATIBILITY_CONFIRMED", "required": True, "question": "Market/Broker 조합을 확인했는가"},
        {"checklist_code": "ACCOUNT_OWNERSHIP_CONFIRMED", "required": True, "question": "Account 소유권을 확인했는가"},
        {"checklist_code": "ACCOUNT_STATUS_CONFIRMED", "required": True, "question": "Account 상태를 확인했는가"},
        {"checklist_code": "EFFECTIVE_RISK_SETTING_CONFIRMED", "required": True, "question": "Effective Risk Setting을 확인했는가"},
        {"checklist_code": "KILL_SWITCH_INACTIVE_CONFIRMED", "required": True, "question": "Kill Switch 비활성을 확인했는가"},
        {"checklist_code": "TRADING_FLAG_CONFIRMED", "required": True, "question": "Trading Flag를 확인했는가"},
        {"checklist_code": "ACCOUNT_PAUSE_CONFIRMED", "required": True, "question": "Account Pause 여부를 확인했는가"},
        {"checklist_code": "RECOVERY_CONFLICT_CONFIRMED", "required": True, "question": "Recovery Conflict 여부를 확인했는가"},
        {"checklist_code": "RUNTIME_SCOPE_CONFIRMED", "required": True, "question": "Runtime Scope를 확인했는가"},
        {"checklist_code": "NO_EXISTING_RUNTIME_DEPLOYMENT_CONFIRMED", "required": True, "question": "기존 Runtime/Deployment가 없음을 확인했는가"},
        {"checklist_code": "ACTIVATION_NOT_RUNTIME_START_CONFIRMED", "required": True, "question": "Activation이 Runtime 시작이 아님을 확인했는가"},
        {"checklist_code": "ACTIVATION_NOT_ORDER_EXECUTION_CONFIRMED", "required": True, "question": "실제 주문 실행이 아님을 확인했는가"},
    ]
    if execution_mode == EXECUTION_MODE_LIVE:
        items.extend(
            [
                {"checklist_code": "LIVE_ACCOUNT_CONFIRMED", "required": True, "question": "LIVE 계좌를 확인했는가"},
                {"checklist_code": "CREDENTIAL_METADATA_CONFIRMED", "required": True, "question": "Credential Metadata를 확인했는가"},
                {"checklist_code": "CREDENTIAL_VERIFIED_CONFIRMED", "required": True, "question": "Credential Verified 상태를 확인했는가"},
                {"checklist_code": "LIVE_TRADING_ENABLED_CONFIRMED", "required": True, "question": "Live Trading Enabled를 확인했는가"},
                {"checklist_code": "LIVE_ORDER_ENABLED_CONFIRMED", "required": True, "question": "Live Order Enabled를 확인했는가"},
                {"checklist_code": "INVESTMENT_LIMIT_CONFIRMED", "required": True, "question": "투자 한도를 확인했는가"},
                {"checklist_code": "LOSS_LIMIT_CONFIRMED", "required": True, "question": "손실 한도를 확인했는가"},
                {"checklist_code": "SAME_ACTOR_WARNING_CONFIRMED", "required": False, "question": "Same Actor Warning을 확인했는가(해당 시)"},
                {"checklist_code": "LIVE_CAPITAL_RISK_ACKNOWLEDGED", "required": True, "question": "실제 자금 위험을 인지했는가"},
            ]
        )
    elif execution_mode == EXECUTION_MODE_PAPER:
        items.extend(
            [
                {"checklist_code": "PAPER_ACCOUNT_CONFIRMED", "required": True, "question": "Paper Account를 확인했는가"},
                {"checklist_code": "NO_LIVE_ORDER_CONFIRMED", "required": True, "question": "실계좌 주문이 발생하지 않음을 확인했는가"},
                {"checklist_code": "PAPER_RUNTIME_NOT_STARTED_CONFIRMED", "required": True, "question": "Paper Runtime이 아직 시작되지 않음을 확인했는가"},
            ]
        )
    return items


# ---------------------------------------------------------------------------
# Validation — Market/Broker/Account/Credential/Risk/Runtime Scope/Conflict.
# 전부 읽기 전용, Broker API 호출 없음, Credential 복호화 없음.
# ---------------------------------------------------------------------------


def _market_family(market_type: str) -> str:
    """`StrategyDefinitionEntity.market_type`은 "KR_STOCK"(AI Draft 유래)
    또는 "STOCK"(직접 생성 유래) 등 세부 표기가 다를 수 있다(§
    `ai/strategy_draft_generation/constants.py`의 `ALLOWED_MARKET_TYPES`
    vs `strategy_deployment/ownership.py`의 `{"STOCK","CRYPTO","ALL"}`).
    Activation Review는 실제 세부 코드가 아니라 "주식류/암호화폐류"
    Family만 비교한다(`runtime_bootstrap.py`가 이미 사용하는 것과 동일한
    "CRYPTO가 아니면 STOCK" 관례를 재사용)."""
    return "CRYPTO" if (market_type or "").upper() == "CRYPTO" else "STOCK"


def _validate_market_broker(
    *, strategy_market_type: str, target_market_type: str, target_broker_code: str, target_account_kind: str
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    smt_family = _market_family(strategy_market_type)
    tmt_family = _market_family(target_market_type)
    broker = (target_broker_code or "").upper()

    if (strategy_market_type or "").upper() != "ALL" and tmt_family != smt_family:
        blocking.append("UNSUPPORTED_MARKET")
    if broker not in {"KIWOOM", "UPBIT", "PAPER"}:
        blocking.append("UNSUPPORTED_BROKER")
    if target_account_kind == ACCOUNT_KIND_PAPER and broker != "PAPER":
        blocking.append("ACCOUNT_KIND_MISMATCH")
    if target_account_kind == ACCOUNT_KIND_USER_BROKER and broker not in {"KIWOOM", "UPBIT"}:
        blocking.append("ACCOUNT_KIND_MISMATCH")
    if "UNSUPPORTED_MARKET" not in blocking and "UNSUPPORTED_BROKER" not in blocking:
        if not market_compatible(market_type=tmt_family, account_broker=broker):
            blocking.append("MARKET_BROKER_MISMATCH")
    return blocking, []


def _resolve_account(
    session: Session, *, target_account_kind: str, target_user_broker_account_id: int | None,
    target_paper_account_id: int | None,
) -> tuple[UserBrokerAccount | PaperAccount | None, list[str]]:
    blocking: list[str] = []
    if target_account_kind == ACCOUNT_KIND_USER_BROKER:
        if target_user_broker_account_id is None:
            blocking.append("ACCOUNT_NOT_FOUND")
            return None, blocking
        account = session.get(UserBrokerAccount, target_user_broker_account_id)
        if account is None:
            blocking.append("ACCOUNT_NOT_FOUND")
            return None, blocking
        if account.deleted_at is not None or not bool(account.is_active):
            blocking.append("ACCOUNT_INACTIVE")
        return account, blocking
    if target_account_kind == ACCOUNT_KIND_PAPER:
        if target_paper_account_id is None:
            blocking.append("ACCOUNT_NOT_FOUND")
            return None, blocking
        account = session.get(PaperAccount, target_paper_account_id)
        if account is None:
            blocking.append("ACCOUNT_NOT_FOUND")
            return None, blocking
        if account.deleted_at is not None or not bool(account.is_active):
            blocking.append("ACCOUNT_INACTIVE")
        return account, blocking
    blocking.append("ACCOUNT_NOT_FOUND")
    return None, blocking


def _account_snapshot_payload(account: UserBrokerAccount | PaperAccount | None, *, kind: str) -> dict[str, Any]:
    if account is None:
        return {"kind": kind, "found": False}
    if isinstance(account, UserBrokerAccount):
        return {
            "kind": kind,
            "found": True,
            "user_broker_account_id": int(account.user_broker_account_id),
            "user_id": int(account.user_id),
            "broker_code": account.broker_code,
            "is_active": bool(account.is_active),
            "live_order_enabled": bool(account.live_order_enabled),
            "live_armed": bool(account.live_armed),
            "connection_status": account.connection_status,
        }
    return {
        "kind": kind,
        "found": True,
        "paper_account_id": int(account.account_id),
        "user_id": account.user_id,
        "is_active": bool(account.is_active),
    }


def _broker_snapshot_payload(
    session: Session, *, account: UserBrokerAccount | PaperAccount | None, target_account_kind: str,
    requested_execution_mode: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Credential 상태(§ 복호화 금지, metadata만) — LIVE(USER_BROKER)만
    해당한다. PAPER는 Live Credential이 불필요하다(§ 명세 PAPER 정책)."""
    blocking: list[str] = []
    warning: list[str] = []
    if target_account_kind != ACCOUNT_KIND_USER_BROKER or not isinstance(account, UserBrokerAccount):
        return {"applicable": False}, blocking, warning
    view = BrokerCredentialVaultService(session).status(int(account.user_broker_account_id))
    payload = view.as_dict()
    payload["applicable"] = True
    if requested_execution_mode == EXECUTION_MODE_LIVE:
        if not view.connected or view.verification_status in (None, "PENDING", "FAILED"):
            blocking.append("CREDENTIAL_NOT_FOUND")
        elif view.verification_status == "REVOKED":
            blocking.append("CREDENTIAL_REVOKED")
        elif view.verification_status != "VERIFIED":
            warning.append("CREDENTIAL_NOT_VERIFIED")
    return payload, blocking, warning


RISK_SOURCE_EXPLICIT = "EXPLICIT_SYSTEM"
RISK_SOURCE_SAFE_PAPER_DEFAULT = "SAFE_PAPER_DEFAULT"
RISK_SOURCE_CODE_FALLBACK = "CODE_FALLBACK"

# § STEP12-17 제한사항 보완(1) — LIVE Risk Fail Closed. `SystemRiskSetting`
# 행이 실제로 없는데도 Resolver가 코드 하드코딩 기본값을 permissive하게
# 반환하면 LIVE 등록을 절대 허용하지 않는다. PAPER는 명시적 설정이
# 없으면 이 보수적 고정값으로 안전하게 대체한다(source=SAFE_PAPER_DEFAULT
# 로 기록 — 실제 Resolver 값을 그대로 쓰지 않는다).
_SAFE_PAPER_DEFAULT_OVERLAY: dict[str, str] = {
    "max_order_amount": "100000",
    "daily_max_order_amount": "300000",
    "max_total_investment_amount": "1000000",
    "max_position_amount": "300000",
    "daily_max_loss_amount": "50000",
    "daily_max_loss_rate": "0.02",
}


def _is_risk_explicit(source_layers: tuple[str, ...]) -> bool:
    """`ResolvedRiskPolicyResolver.resolve()`가 반환하는 `source_layers`에
    `"system"`이 있으면 실제 `trading.system_risk_setting` 행이 존재한다는
    뜻이다(Resolver 자체 코드: 행이 없으면 `"code_fallback"`만 남는다).
    이것이 "명시적 System Risk Setting 존재"의 유일한 신뢰 가능한 판정
    기준이다."""
    return "system" in source_layers


def _risk_snapshot_payload(
    session: Session, *, account: UserBrokerAccount | PaperAccount | None, target_account_kind: str,
    requested_execution_mode: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    blocking: list[str] = []
    warning: list[str] = []
    if account is None:
        return {}, blocking, warning
    resolver = ResolvedRiskPolicyResolver(session)
    if target_account_kind == ACCOUNT_KIND_USER_BROKER and isinstance(account, UserBrokerAccount):
        policy = resolver.resolve(user_id=int(account.user_id), user_broker_account_id=int(account.user_broker_account_id))
    else:
        policy = resolver.resolve(user_id=account.user_id if account.user_id is not None else None)
    payload = policy.as_dict()
    explicit = _is_risk_explicit(policy.source_layers)

    if requested_execution_mode == EXECUTION_MODE_LIVE:
        if not explicit:
            blocking.append("RISK_SETTING_NOT_FOUND")
        payload["risk_source"] = RISK_SOURCE_EXPLICIT if explicit else RISK_SOURCE_CODE_FALLBACK
        payload["effective_risk_explicit"] = explicit
    else:
        if explicit:
            payload["risk_source"] = RISK_SOURCE_EXPLICIT
            payload["effective_risk_explicit"] = True
        else:
            payload.update(_SAFE_PAPER_DEFAULT_OVERLAY)
            payload["risk_source"] = RISK_SOURCE_SAFE_PAPER_DEFAULT
            payload["effective_risk_explicit"] = False

    if policy.account_paused:
        blocking.append("ACCOUNT_PAUSED")
    if not policy.auto_trading_enabled:
        blocking.append("TRADING_DISABLED")
    if not policy.buy_enabled:
        warning.append("BUY_DISABLED")
    # Strategy lifecycle activation은 UBA `live_order_enabled`와 분리한다.
    # LIVE OFF 상태에서도 Activation Review/Commit은 가능하며, 실주문은
    # order/live_safety/autotrading gate에서 계속 차단된다.
    if requested_execution_mode == EXECUTION_MODE_LIVE and isinstance(account, UserBrokerAccount):
        if not bool(account.live_order_enabled):
            warning.append("LIVE_ORDER_DISABLED")
    return payload, blocking, warning


def _operational_snapshot_payload(
    session: Session, *, strategy_definition_id: int, account: UserBrokerAccount | PaperAccount | None,
    target_account_kind: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    blocking: list[str] = []
    warning: list[str] = []

    scope_codes: list[str] = []
    recovery_paused = False
    if account is not None:
        if target_account_kind == ACCOUNT_KIND_USER_BROKER and isinstance(account, UserBrokerAccount):
            scope_codes.append(uba_kill_switch_scope(int(account.user_broker_account_id)))
            recovery_paused = RecoveryAccountLockService(session).is_trading_paused(
                user_broker_account_id=int(account.user_broker_account_id), broker_code=account.broker_code,
            )
        elif target_account_kind == ACCOUNT_KIND_PAPER and isinstance(account, PaperAccount):
            scope_codes.append(paper_kill_switch_scope(int(account.account_id)))
            recovery_paused = RecoveryAccountLockService(session).is_trading_paused(
                paper_account_id=int(account.account_id),
            )
    kill_switch_active = KillSwitchService(session).is_active_for_scopes(scope_codes)
    if kill_switch_active:
        blocking.append("KILL_SWITCH_ACTIVE")
    if recovery_paused:
        blocking.append("RECOVERY_CONFLICT")

    matching_active_link = False
    conflicting_active_link = False
    if account is not None:
        stmt = select(AccountStrategyLinkEntity).where(AccountStrategyLinkEntity.is_active.is_(True))
        if target_account_kind == ACCOUNT_KIND_USER_BROKER and isinstance(account, UserBrokerAccount):
            stmt = stmt.where(AccountStrategyLinkEntity.user_broker_account_id == int(account.user_broker_account_id))
        elif isinstance(account, PaperAccount):
            stmt = stmt.where(AccountStrategyLinkEntity.paper_account_id == int(account.account_id))
        for active_link in session.scalars(stmt):
            if int(active_link.strategy_id) == int(strategy_definition_id):
                matching_active_link = True
            else:
                conflicting_active_link = True
    # § STEP12-17 — 동일 Strategy+Account의 활성 Link는 Activation 전제조건
    # (positive evidence). 다른 Strategy가 같은 Account에 이미 활성 Link로
    # 묶여 있을 때만 ACCOUNT_STRATEGY_LINK_CONFLICT로 차단한다.
    if conflicting_active_link:
        blocking.append("ACCOUNT_STRATEGY_LINK_CONFLICT")

    deployment_exists = session.scalar(
        select(StrategyDeploymentEntity)
        .where(
            StrategyDeploymentEntity.strategy_id == strategy_definition_id,
            StrategyDeploymentEntity.status_code == "ACTIVE",
        )
        .limit(1)
    ) is not None
    if deployment_exists:
        blocking.append("DEPLOYMENT_ALREADY_EXISTS")

    payload = {
        "kill_switch_active": kill_switch_active,
        "recovery_paused": recovery_paused,
        "existing_runtime_link": matching_active_link,
        "conflicting_active_link": conflicting_active_link,
        "existing_deployment": deployment_exists,
        "kill_switch_scope_codes": scope_codes,
    }
    return payload, blocking, warning


def _run_activation_validations(
    session: Session,
    *,
    definition: StrategyDefinitionEntity,
    strategy_definition_id: int,
    target_market_type: str,
    target_broker_code: str,
    target_account_kind: str,
    target_user_broker_account_id: int | None,
    target_paper_account_id: int | None,
    requested_execution_mode: str,
) -> dict[str, Any]:
    """읽기 전용 종합 검증 — Broker API 호출/Credential 복호화/재계산
    없음. Package 생성 시점과 Stale 재검증 시점(Commit 직전)에 동일하게
    재사용된다(로직 중복 없음)."""
    blocking: list[str] = []
    warning: list[str] = []
    missing: list[str] = []

    if requested_execution_mode not in EXECUTION_MODE_VALUES:
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

    # § STEP12-17 제한사항 보완(4) — Account Ownership 관계 검증. 관리자
    # 자신이 계좌 소유자일 필요는 없지만, USER 소유 Strategy는 반드시 그
    # user_id의 계좌만 대상으로 할 수 있다(다른 사용자의 계좌로 Cross-user
    # 등록하는 것을 차단). SYSTEM 소유(공용) Strategy는 임의 사용자의
    # 계좌를 대상으로 할 수 있으므로 이 검사를 적용하지 않는다.
    if (
        account is not None
        and definition.owner_type == "USER"
        and definition.user_id is not None
        and account.user_id is not None
        and int(account.user_id) != int(definition.user_id)
    ):
        blocking.append("ACCOUNT_OWNERSHIP_MISMATCH")

    broker_snapshot, broker_blocking, broker_warning = _broker_snapshot_payload(
        session, account=account, target_account_kind=target_account_kind,
        requested_execution_mode=requested_execution_mode,
    )
    blocking.extend(broker_blocking)
    warning.extend(broker_warning)

    risk_snapshot, risk_blocking, risk_warning = _risk_snapshot_payload(
        session, account=account, target_account_kind=target_account_kind,
        requested_execution_mode=requested_execution_mode,
    )
    blocking.extend(risk_blocking)
    warning.extend(risk_warning)

    operational_snapshot, op_blocking, op_warning = _operational_snapshot_payload(
        session, strategy_definition_id=strategy_definition_id, account=account,
        target_account_kind=target_account_kind,
    )
    blocking.extend(op_blocking)
    warning.extend(op_warning)

    if requested_execution_mode == EXECUTION_MODE_LIVE and target_account_kind != ACCOUNT_KIND_USER_BROKER:
        blocking.append("LIVE_TRADING_NOT_ALLOWED")
    if requested_execution_mode == EXECUTION_MODE_PAPER and target_account_kind != ACCOUNT_KIND_PAPER:
        blocking.append("ACCOUNT_KIND_MISMATCH")

    return {
        "blocking": sorted(set(blocking)),
        "warning": sorted(set(warning) - set(blocking)),
        "missing": sorted(set(missing)),
        "account": account,
        "account_snapshot_payload": _account_snapshot_payload(account, kind=target_account_kind),
        "broker_snapshot_payload": broker_snapshot,
        "effective_risk_snapshot_payload": risk_snapshot,
        "operational_snapshot_payload": operational_snapshot,
    }


# ---------------------------------------------------------------------------
# Activation Review Package.
# ---------------------------------------------------------------------------


def run_create_activation_review_package(
    session: Session,
    strategy_definition_id: int,
    *,
    promotion_commit_id: int,
    target_market_type: str,
    target_broker_code: str,
    target_account_kind: str,
    target_user_broker_account_id: int | None = None,
    target_paper_account_id: int | None = None,
    requested_execution_mode: str,
    requested_runtime_scope: dict[str, Any] | None = None,
    requested_capital_limit: str | None = None,
    review_note: str | None = None,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    definition = session.scalar(
        select(StrategyDefinitionEntity)
        .where(StrategyDefinitionEntity.strategy_id == strategy_definition_id)
        .with_for_update()
    )
    if definition is None or definition.deleted_at is not None:
        raise ActivationError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    promotion_state = _ensure_and_lock_promotion_state(session, strategy_definition_id, actor=actor)

    # § Idempotency — 이 Key로 이미 저장된 Package가 있으면(Replay든
    # Conflict든) 현재 Promotion State가 이미 ACTIVATION_REVIEW/ACTIVATED로
    # 전이돼 있어도(즉, "이 요청 자체가 그 전이를 만든 원본"이었어도)
    # 아래 상태 게이팅보다 먼저 판단해야 한다 — 그렇지 않으면 원본 요청을
    # 그대로 재전송한 정상적인 Replay가 ALREADY_UNDER_REVIEW로 잘못
    # 차단된다. 원본 요청 필드(계산된 Snapshot Hash가 아니라 호출자가
    # 넘긴 값 자체)를 직접 비교한다.
    if idempotency_key:
        existing = session.scalar(
            select(StrategyActivationReviewPackageEntity).where(
                StrategyActivationReviewPackageEntity.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            same_request = (
                existing.strategy_definition_id == strategy_definition_id
                and existing.promotion_commit_id == promotion_commit_id
                and existing.requested_market_type == target_market_type
                and existing.requested_broker_code == target_broker_code
                and existing.requested_account_kind == target_account_kind
                and existing.requested_user_broker_account_id == target_user_broker_account_id
                and existing.requested_paper_account_id == target_paper_account_id
                and existing.requested_execution_mode == requested_execution_mode
                and existing.requested_capital_limit == requested_capital_limit
            )
            if same_request:
                return _to_package_dict(existing, idempotent_replay=True)
            raise ActivationError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다.")

    commit = session.get(StrategyPromotionCommitEntity, promotion_commit_id)
    if commit is None:
        raise ActivationError("PROMOTION_NOT_COMMITTED", f"Promotion Commit not found: {promotion_commit_id}")
    if commit.strategy_definition_id != strategy_definition_id:
        raise ActivationError(
            "OWNERSHIP_MISMATCH", f"Promotion Commit #{promotion_commit_id}은 이 Strategy의 Commit이 아닙니다."
        )
    if promotion_state.current_status != PROMOTION_STATE_PROMOTION_COMMITTED:
        if promotion_state.current_status in (PROMOTION_STATE_ACTIVATION_REVIEW, PROMOTION_STATE_ACTIVATED):
            raise ActivationError(
                "ALREADY_ACTIVATED" if promotion_state.current_status == PROMOTION_STATE_ACTIVATED else "ALREADY_UNDER_REVIEW",
                f"Strategy Promotion State가 이미 {promotion_state.current_status}입니다.",
            )
        raise ActivationError(
            "PROMOTION_NOT_COMMITTED", f"Strategy Promotion State가 PROMOTION_COMMITTED가 아닙니다(현재: {promotion_state.current_status})."
        )

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            raise ActivationError(
                "STRATEGY_NOT_ELIGIBLE", f"Candidate Lifecycle 상태가 Activation 불가 상태입니다: {lifecycle.lifecycle_status}"
            )

    validation = _run_activation_validations(
        session, definition=definition, strategy_definition_id=strategy_definition_id,
        target_market_type=target_market_type, target_broker_code=target_broker_code,
        target_account_kind=target_account_kind, target_user_broker_account_id=target_user_broker_account_id,
        target_paper_account_id=target_paper_account_id, requested_execution_mode=requested_execution_mode,
    )

    runtime_scope_payload = dict(requested_runtime_scope or {})
    runtime_scope_payload.setdefault("strategy_id", strategy_definition_id)
    runtime_scope_payload.setdefault("market_type", target_market_type)
    runtime_scope_payload.setdefault("broker_code", target_broker_code)

    review_input_hash = compute_activation_review_input_hash(
        strategy_definition_id=strategy_definition_id, promotion_commit_id=promotion_commit_id,
        target_market_type=target_market_type, target_broker_code=target_broker_code,
        target_account_kind=target_account_kind, target_user_broker_account_id=target_user_broker_account_id,
        target_paper_account_id=target_paper_account_id, requested_execution_mode=requested_execution_mode,
        requested_runtime_scope_payload=runtime_scope_payload, requested_capital_limit=requested_capital_limit,
        effective_risk_snapshot_payload=validation["effective_risk_snapshot_payload"],
        account_snapshot_payload=validation["account_snapshot_payload"],
        broker_snapshot_payload=validation["broker_snapshot_payload"],
        operational_snapshot_payload=validation["operational_snapshot_payload"],
        blocking_reason_codes=validation["blocking"], warning_reason_codes=validation["warning"],
        missing_requirement_codes=validation["missing"], algorithm_version=ALGORITHM_VERSION,
    )

    readiness_status = ACTIVATION_READINESS_BLOCKED if validation["blocking"] else ACTIVATION_READINESS_READY
    created_at = datetime.now(timezone.utc)

    # § 존재하지 않는 계좌 ID는 FK 컬럼에 그대로 저장하지 않는다(Fail
    # Closed — 존재하지 않는 참조를 조작해 저장하면 FK Violation이 발생할
    # 뿐 아니라, 검증되지 않은 값을 불변 기록에 남기는 것 자체가 부적절
    # 하다). "요청은 했으나 찾을 수 없었다"는 사실은 이미 blocking_reason
    # _codes의 ACCOUNT_NOT_FOUND로 충분히 기록된다.
    account_found = validation["account"] is not None
    package_uba_id = target_user_broker_account_id if (account_found and target_account_kind == ACCOUNT_KIND_USER_BROKER) else None
    package_paper_id = target_paper_account_id if (account_found and target_account_kind == ACCOUNT_KIND_PAPER) else None

    package = StrategyActivationReviewPackageEntity(
        strategy_definition_id=strategy_definition_id,
        promotion_commit_id=promotion_commit_id,
        requested_market_type=target_market_type,
        requested_broker_code=target_broker_code,
        requested_account_kind=target_account_kind,
        requested_user_broker_account_id=package_uba_id,
        requested_paper_account_id=package_paper_id,
        requested_execution_mode=requested_execution_mode,
        requested_runtime_scope_payload=runtime_scope_payload,
        requested_capital_limit=requested_capital_limit,
        review_note=review_note,
        effective_risk_snapshot_payload=validation["effective_risk_snapshot_payload"],
        account_snapshot_payload=validation["account_snapshot_payload"],
        broker_snapshot_payload=validation["broker_snapshot_payload"],
        operational_snapshot_payload=validation["operational_snapshot_payload"],
        readiness_status=readiness_status,
        blocking_reason_codes=validation["blocking"],
        warning_reason_codes=validation["warning"],
        missing_requirement_codes=validation["missing"],
        review_input_hash=review_input_hash,
        created_by=actor,
        created_at=created_at,
        idempotency_key=(idempotency_key or None),
        algorithm_version=ALGORITHM_VERSION,
    )

    try:
        session.add(package)
        session.flush()

        # Activation Review Package 생성 자체가 ACTIVATION_REVIEW 진입을
        # 의미한다 — readiness가 BLOCKED여도 human review/decision 경로는
        # 열린다(실제 Commit 직전에 current validation으로 재검증).
        previous_status = promotion_state.current_status
        if previous_status == PROMOTION_STATE_PROMOTION_COMMITTED:
            new_status = PROMOTION_STATE_ACTIVATION_REVIEW
            if not _can_transition_activation_state(previous_status, new_status):
                raise ActivationError(
                    "INVALID_PROMOTION_STATE_TRANSITION", f"{previous_status} -> {new_status} 전이는 허용되지 않습니다."
                )
            new_version = promotion_state.status_version + 1
            state_hash = compute_promotion_state_hash(
                strategy_definition_id=strategy_definition_id, current_status=new_status,
                status_version=new_version, current_promotion_commit_id=promotion_state.current_promotion_commit_id,
                previous_event_hash=None, transitioned_at=created_at, algorithm_version=ALGORITHM_VERSION,
            )
            promotion_state.current_status = new_status
            promotion_state.status_version = new_version
            promotion_state.state_hash = state_hash
            promotion_state.updated_by = actor

            event_hash = compute_promotion_state_event_hash(
                strategy_definition_id=strategy_definition_id, promotion_commit_id=int(commit.promotion_commit_id),
                previous_status=previous_status, new_status=new_status, human_decision_id=commit.human_decision_id,
                decision_package_id=commit.decision_package_id, actor=actor, occurred_at=created_at,
                transition_reason=(review_note or "Activation Review Package created"), algorithm_version=ALGORITHM_VERSION,
            )
            history_entity = StrategyPromotionHistoryEntity(
                strategy_definition_id=strategy_definition_id, promotion_commit_id=int(commit.promotion_commit_id),
                previous_status=previous_status, new_status=new_status,
                transition_reason=(review_note or "Activation Review Package created"),
                human_decision_id=commit.human_decision_id, decision_package_id=commit.decision_package_id,
                actor=actor, event_hash=event_hash, occurred_at=created_at, algorithm_version=ALGORITHM_VERSION,
                metadata_payload={
                    "activation_review_package_id": int(package.activation_review_package_id),
                    "readiness_status": readiness_status,
                },
            )
            session.add(history_entity)

        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = None
        if idempotency_key:
            conflict = session.scalar(
                select(StrategyActivationReviewPackageEntity).where(
                    StrategyActivationReviewPackageEntity.idempotency_key == idempotency_key
                )
            )
        if conflict is not None:
            return _to_package_dict(conflict, idempotent_replay=True)
        raise ActivationError("DUPLICATE_ACTIVATION_REVIEW", "동일 Package/전이 저장 중 충돌이 발생했습니다.") from None

    session.refresh(package)
    return _to_package_dict(package, idempotent_replay=False)


def _to_package_dict(package: StrategyActivationReviewPackageEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "activation_review_package_id": int(package.activation_review_package_id),
        "strategy_definition_id": package.strategy_definition_id,
        "promotion_commit_id": package.promotion_commit_id,
        "requested_market_type": package.requested_market_type,
        "requested_broker_code": package.requested_broker_code,
        "requested_account_kind": package.requested_account_kind,
        "requested_user_broker_account_id": package.requested_user_broker_account_id,
        "requested_paper_account_id": package.requested_paper_account_id,
        "requested_execution_mode": package.requested_execution_mode,
        "requested_runtime_scope_payload": package.requested_runtime_scope_payload,
        "requested_capital_limit": package.requested_capital_limit,
        "review_note": package.review_note,
        "effective_risk_snapshot_payload": package.effective_risk_snapshot_payload,
        "account_snapshot_payload": package.account_snapshot_payload,
        "broker_snapshot_payload": package.broker_snapshot_payload,
        "operational_snapshot_payload": package.operational_snapshot_payload,
        "readiness_status": package.readiness_status,
        "blocking_reason_codes": package.blocking_reason_codes,
        "warning_reason_codes": package.warning_reason_codes,
        "missing_requirement_codes": package.missing_requirement_codes,
        "review_input_hash": package.review_input_hash,
        "created_by": package.created_by,
        "created_at": package.created_at,
        "idempotency_key": package.idempotency_key,
        "algorithm_version": package.algorithm_version,
        "idempotent_replay": idempotent_replay,
    }


def check_activation_package_staleness(
    session: Session, package: StrategyActivationReviewPackageEntity
) -> tuple[bool, list[str]]:
    """Package 생성 시점 Snapshot과 현재 상태를 비교한다(§ 명세 "Stale
    Detection") — 관계없는 새 Report 추가는 Stale이 아니다."""
    reasons: list[str] = []
    definition = session.get(StrategyDefinitionEntity, package.strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        return True, ["DEFINITION_MISSING"]

    commit = session.get(StrategyPromotionCommitEntity, package.promotion_commit_id)
    if commit is None:
        return True, ["PROMOTION_COMMIT_MISSING"]
    if commit.definition_hash and commit.definition_hash != definition.definition_hash:
        reasons.append("EXECUTABLE_HASH_CHANGED")

    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None and lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
            reasons.append(f"LIFECYCLE_{lifecycle.lifecycle_status}")

    validation = _run_activation_validations(
        session, definition=definition, strategy_definition_id=package.strategy_definition_id,
        target_market_type=package.requested_market_type, target_broker_code=package.requested_broker_code,
        target_account_kind=package.requested_account_kind,
        target_user_broker_account_id=package.requested_user_broker_account_id,
        target_paper_account_id=package.requested_paper_account_id,
        requested_execution_mode=package.requested_execution_mode,
    )
    if validation["account_snapshot_payload"] != package.account_snapshot_payload:
        reasons.append("ACCOUNT_SNAPSHOT_CHANGED")
    if validation["broker_snapshot_payload"].get("verification_status") != package.broker_snapshot_payload.get("verification_status"):
        reasons.append("CREDENTIAL_SNAPSHOT_CHANGED")
    if validation["effective_risk_snapshot_payload"] != package.effective_risk_snapshot_payload:
        reasons.append("RISK_SNAPSHOT_CHANGED")
    stored_op = package.operational_snapshot_payload or {}
    current_op = validation["operational_snapshot_payload"] or {}
    if stored_op != current_op:
        # legacy package에 informational field만 추가된 경우(예:
        # conflicting_active_link)는 stale로 보지 않는다 — 저장된 키 값이
        # 모두 동일하면 material change 없음.
        material_op_changed = any(stored_op.get(k) != current_op.get(k) for k in stored_op)
        if material_op_changed:
            reasons.append("OPERATIONAL_SNAPSHOT_CHANGED")
    stored_blocking = sorted(package.blocking_reason_codes or [])
    current_blocking = sorted(validation["blocking"])
    if stored_blocking != current_blocking:
        # 생성 시점 BLOCKED → 현재 READY 로 개선된 경우는 stale 아님(Commit 진행 허용).
        if set(current_blocking) - set(stored_blocking) or current_blocking:
            reasons.append("READINESS_CHANGED")

    return len(reasons) > 0, reasons


# ---------------------------------------------------------------------------
# Human Activation Decision.
# ---------------------------------------------------------------------------


def run_record_activation_decision(
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
    package = session.get(StrategyActivationReviewPackageEntity, package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise ActivationError("PACKAGE_NOT_FOUND", f"Activation Review Package not found: {package_id}")
    definition = session.get(StrategyDefinitionEntity, package.strategy_definition_id)
    if definition is None or definition.deleted_at is not None:
        raise ActivationError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")
    if decision_type not in ACTIVATION_DECISION_TYPES:
        raise ActivationError("INVALID_DECISION_TYPE", f"알 수 없는 Decision Type: {decision_type}")
    if reason_code not in REASON_CODES_BY_ACTIVATION_DECISION_TYPE.get(decision_type, frozenset()):
        raise ActivationError("INVALID_REASON_CODE", f"{decision_type}에 허용되지 않는 reason_code입니다: {reason_code}")
    if not reason_text or not reason_text.strip():
        raise ActivationError("REASON_TEXT_REQUIRED", "reason_text는 필수입니다.")

    existing_decision = session.scalar(
        select(StrategyActivationDecisionEntity).where(
            StrategyActivationDecisionEntity.activation_review_package_id == package_id
        )
    )
    if existing_decision is not None:
        # § STEP12-17 제한사항 보완(3) — `decision_input_hash`는 `decided_at`
        # (호출마다 달라지는 현재 시각)을 포함하므로 Replay 판정에 그대로
        # 쓸 수 없다(재계산해도 항상 다른 값이 나온다). 대신 호출자가
        # 실제로 넘긴 입력 필드 자체를 기존 저장값과 직접 비교한다 — 같은
        # Key라도 입력이 다르면 IDEMPOTENCY_CONFLICT여야 한다.
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
            raise ActivationError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 입력으로 사용되었습니다."
            )
        raise ActivationError(
            "DUPLICATE_ACTIVATION_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다."
        )

    decided_at = datetime.now(timezone.utc)
    decision_input_hash = compute_activation_decision_input_hash(
        activation_review_package_id=package_id, decision_type=decision_type, reason_code=reason_code,
        reason_text=reason_text, checklist_payload=checklist_confirmations,
        acknowledged_warnings_payload=acknowledged_warnings, decided_by=actor, decided_at=decided_at,
        algorithm_version=ALGORITHM_VERSION,
    )

    stale, stale_reasons = check_activation_package_staleness(session, package)
    if stale:
        raise ActivationError("STALE_ACTIVATION_PACKAGE", f"Activation Review Package가 Stale 상태입니다: {', '.join(stale_reasons)}")

    activation_ready = False
    if decision_type == ACTIVATION_DECISION_APPROVE:
        current_validation = _run_activation_validations(
            session,
            definition=definition,
            strategy_definition_id=package.strategy_definition_id,
            target_market_type=package.requested_market_type,
            target_broker_code=package.requested_broker_code,
            target_account_kind=package.requested_account_kind,
            target_user_broker_account_id=package.requested_user_broker_account_id,
            target_paper_account_id=package.requested_paper_account_id,
            requested_execution_mode=package.requested_execution_mode,
        )
        if current_validation["blocking"]:
            raise ActivationError(
                "PACKAGE_NOT_READY",
                "현재 Activation Readiness가 차단 상태입니다: "
                f"{', '.join(current_validation['blocking'])}",
            )
        required_codes = {
            c["checklist_code"] for c in build_activation_checklist_template(package.requested_execution_mode) if c["required"]
        }
        missing_confirmations = [c for c in required_codes if not checklist_confirmations.get(c)]
        if missing_confirmations:
            raise ActivationError(
                "INCOMPLETE_CHECKLIST", f"필수 Checklist 미확인 항목이 있습니다: {', '.join(sorted(missing_confirmations))}"
            )
        effective_warnings = sorted(set(current_validation["warning"]))
        if effective_warnings and set(effective_warnings) - set(acknowledged_warnings) - {"ALL"}:
            if "ALL" not in acknowledged_warnings:
                raise ActivationError("WARNING_NOT_ACKNOWLEDGED", "모든 Warning을 확인(acknowledge)해야 합니다.")
        activation_ready = True

    same_actor_warning = actor == package.created_by

    decision = StrategyActivationDecisionEntity(
        activation_review_package_id=package_id, strategy_definition_id=strategy_definition_id,
        decision_type=decision_type, reason_code=reason_code, reason_text=reason_text,
        checklist_payload=checklist_confirmations, acknowledged_warnings_payload=acknowledged_warnings,
        same_actor_warning=same_actor_warning, decided_by=actor, decided_at=decided_at,
        decision_input_hash=decision_input_hash, activation_ready=activation_ready,
        idempotency_key=(idempotency_key or None), algorithm_version=ALGORITHM_VERSION,
    )
    try:
        session.add(decision)
        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = session.scalar(
            select(StrategyActivationDecisionEntity).where(
                StrategyActivationDecisionEntity.activation_review_package_id == package_id
            )
        )
        if conflict is not None:
            if idempotency_key and conflict.idempotency_key == idempotency_key:
                return _to_decision_dict(conflict, idempotent_replay=True)
            raise ActivationError("DUPLICATE_ACTIVATION_DECISION", f"Package #{package_id}에 대한 Decision이 이미 존재합니다.") from None
        raise
    session.refresh(decision)
    return _to_decision_dict(decision, idempotent_replay=False)


def _to_decision_dict(decision: StrategyActivationDecisionEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "activation_decision_id": int(decision.activation_decision_id),
        "activation_review_package_id": decision.activation_review_package_id,
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
        "activation_ready": decision.activation_ready,
        "idempotency_key": decision.idempotency_key,
        "algorithm_version": decision.algorithm_version,
        "idempotent_replay": idempotent_replay,
    }


# ---------------------------------------------------------------------------
# Activation Commit.
# ---------------------------------------------------------------------------


def run_create_activation_commit(
    session: Session,
    strategy_definition_id: int,
    *,
    activation_review_package_id: int,
    activation_decision_id: int,
    activation_readiness_hash: str,
    commit_reason: str,
    confirmation_text: str,
    acknowledge_same_actor_warning: bool = False,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not commit_reason or not commit_reason.strip():
        raise ActivationError("COMMIT_REASON_REQUIRED", "commit_reason은 필수입니다.")
    if _normalize_confirmation_text(confirmation_text) != CONFIRMATION_TEXT_REQUIRED:
        raise ActivationError("INVALID_CONFIRMATION", f"확인값이 올바르지 않습니다('{CONFIRMATION_TEXT_REQUIRED}'를 입력하세요).")

    definition = session.scalar(
        select(StrategyDefinitionEntity)
        .where(StrategyDefinitionEntity.strategy_id == strategy_definition_id)
        .with_for_update()
    )
    if definition is None or definition.deleted_at is not None:
        raise ActivationError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    promotion_state = _ensure_and_lock_promotion_state(session, strategy_definition_id, actor=actor)

    package = session.get(StrategyActivationReviewPackageEntity, activation_review_package_id)
    if package is None or package.strategy_definition_id != strategy_definition_id:
        raise ActivationError("PACKAGE_NOT_FOUND", f"Activation Review Package not found: {activation_review_package_id}")

    decision = session.get(StrategyActivationDecisionEntity, activation_decision_id)
    if decision is None or decision.activation_review_package_id != activation_review_package_id:
        raise ActivationError("DECISION_NOT_FOUND", f"Activation Decision not found: {activation_decision_id}")
    if decision.decision_type != ACTIVATION_DECISION_APPROVE:
        raise ActivationError("DECISION_TYPE_MISMATCH", f"Decision Type이 APPROVE_ACTIVATION이 아닙니다(현재: {decision.decision_type}).")
    if not decision.activation_ready:
        raise ActivationError("ACTIVATION_NOT_READY", "이 Decision은 activation_ready=false입니다.")
    if decision.decision_input_hash != activation_readiness_hash and package.review_input_hash != activation_readiness_hash:
        raise ActivationError("READINESS_HASH_MISMATCH", "요청한 activation_readiness_hash가 일치하지 않습니다.")
    if decision.same_actor_warning and not acknowledge_same_actor_warning:
        raise ActivationError(
            "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED", "Package 생성자와 결정자가 동일합니다 — acknowledge_same_actor_warning=true가 필요합니다."
        )

    existing_for_strategy = session.scalar(
        select(StrategyActivationCommitEntity).where(
            StrategyActivationCommitEntity.strategy_definition_id == strategy_definition_id
        )
    )
    if existing_for_strategy is not None:
        if idempotency_key and existing_for_strategy.idempotency_key == idempotency_key:
            return _to_activation_commit_dict(session, existing_for_strategy, idempotent_replay=True)
        if idempotency_key:
            raise ActivationError("IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 Activation Commit에 사용되었습니다.")
        raise ActivationError("ALREADY_ACTIVATED", f"Strategy Definition #{strategy_definition_id}은 이미 Activation Commit이 존재합니다.")

    if promotion_state.current_status == PROMOTION_STATE_PROMOTION_COMMITTED:
        # legacy repair — BLOCKED package 생성 시 ACTIVATION_REVIEW 전이가
        # 누락된 경우, approved decision이 있으면 Commit 직전에 repair한다.
        if (
            decision.activation_ready
            and int(package.promotion_commit_id) == int(promotion_state.current_promotion_commit_id or 0)
        ):
            repair_at = datetime.now(timezone.utc)
            previous_status = promotion_state.current_status
            new_status = PROMOTION_STATE_ACTIVATION_REVIEW
            if not _can_transition_activation_state(previous_status, new_status):
                raise ActivationError(
                    "INVALID_PROMOTION_STATE_TRANSITION", f"{previous_status} -> {new_status} 전이는 허용되지 않습니다."
                )
            new_version = promotion_state.status_version + 1
            promotion_state.current_status = new_status
            promotion_state.status_version = new_version
            promotion_state.state_hash = compute_promotion_state_hash(
                strategy_definition_id=strategy_definition_id, current_status=new_status,
                status_version=new_version, current_promotion_commit_id=promotion_state.current_promotion_commit_id,
                previous_event_hash=None, transitioned_at=repair_at, algorithm_version=ALGORITHM_VERSION,
            )
            promotion_state.updated_by = actor
            commit_entity = session.get(StrategyPromotionCommitEntity, package.promotion_commit_id)
            session.add(
                StrategyPromotionHistoryEntity(
                    strategy_definition_id=strategy_definition_id,
                    promotion_commit_id=int(package.promotion_commit_id),
                    previous_status=previous_status,
                    new_status=new_status,
                    transition_reason="Activation Review state repair before commit",
                    human_decision_id=commit_entity.human_decision_id if commit_entity else None,
                    decision_package_id=commit_entity.decision_package_id if commit_entity else None,
                    actor=actor,
                    event_hash=compute_promotion_state_event_hash(
                        strategy_definition_id=strategy_definition_id,
                        promotion_commit_id=int(package.promotion_commit_id),
                        previous_status=previous_status,
                        new_status=new_status,
                        human_decision_id=commit_entity.human_decision_id if commit_entity else None,
                        decision_package_id=commit_entity.decision_package_id if commit_entity else None,
                        actor=actor,
                        occurred_at=repair_at,
                        transition_reason="Activation Review state repair before commit",
                        algorithm_version=ALGORITHM_VERSION,
                    ),
                    occurred_at=repair_at,
                    algorithm_version=ALGORITHM_VERSION,
                    metadata_payload={
                        "activation_review_package_id": activation_review_package_id,
                        "activation_decision_id": activation_decision_id,
                        "repair": True,
                    },
                )
            )
        else:
            raise ActivationError(
                "PROMOTION_STATE_NOT_ELIGIBLE",
                f"Strategy Promotion State가 전이 불가 상태입니다(현재: {promotion_state.current_status}).",
            )
    elif promotion_state.current_status != PROMOTION_STATE_ACTIVATION_REVIEW:
        if promotion_state.current_status == PROMOTION_STATE_ACTIVATED:
            raise ActivationError("ALREADY_ACTIVATED", f"Strategy Promotion State가 이미 {PROMOTION_STATE_ACTIVATED}입니다.")
        raise ActivationError(
            "PROMOTION_STATE_NOT_ELIGIBLE", f"Strategy Promotion State가 전이 불가 상태입니다(현재: {promotion_state.current_status})."
        )

    stale, stale_reasons = check_activation_package_staleness(session, package)
    if stale:
        raise ActivationError("STALE_ACTIVATION_PACKAGE", f"Activation Review Package가 Stale 상태입니다: {', '.join(stale_reasons)}")

    commit = session.get(StrategyPromotionCommitEntity, package.promotion_commit_id)
    if commit is None:
        raise ActivationError("PROMOTION_NOT_COMMITTED", f"Promotion Commit not found: {package.promotion_commit_id}")

    committed_at = datetime.now(timezone.utc)
    confirmation_hash = _hash(_canonical_json({"confirmation_text": _normalize_confirmation_text(confirmation_text)}))

    account_snapshot_payload = package.account_snapshot_payload
    broker_snapshot_payload = package.broker_snapshot_payload
    risk_snapshot_payload = package.effective_risk_snapshot_payload
    runtime_scope_payload = package.requested_runtime_scope_payload

    activation_commit_hash = compute_activation_commit_hash(
        strategy_definition_id=strategy_definition_id, definition_version=definition.definition_version,
        definition_hash=definition.definition_hash, executable_hash=commit.executable_hash,
        promotion_commit_id=int(commit.promotion_commit_id), promotion_commit_hash=commit.promotion_commit_hash,
        activation_review_package_id=activation_review_package_id, review_input_hash=package.review_input_hash,
        activation_decision_id=activation_decision_id, decision_input_hash=decision.decision_input_hash,
        target_market_type=package.requested_market_type, target_broker_code=package.requested_broker_code,
        target_account_kind=package.requested_account_kind,
        target_user_broker_account_id=package.requested_user_broker_account_id,
        execution_mode=package.requested_execution_mode,
        runtime_scope_hash=_hash(_canonical_json(runtime_scope_payload)),
        risk_snapshot_hash=_hash(_canonical_json(risk_snapshot_payload)),
        account_snapshot_hash=_hash(_canonical_json(account_snapshot_payload)),
        credential_snapshot_hash=_hash(_canonical_json(broker_snapshot_payload)),
        previous_promotion_status=PROMOTION_STATE_ACTIVATION_REVIEW, committed_promotion_status=PROMOTION_STATE_ACTIVATED,
        committed_by=actor, committed_at=committed_at, confirmation_hash=confirmation_hash,
        algorithm_version=ALGORITHM_VERSION,
    )

    activation_commit = StrategyActivationCommitEntity(
        strategy_definition_id=strategy_definition_id, promotion_commit_id=int(commit.promotion_commit_id),
        activation_review_package_id=activation_review_package_id, activation_decision_id=activation_decision_id,
        target_market_type=package.requested_market_type, target_broker_code=package.requested_broker_code,
        target_account_kind=package.requested_account_kind,
        target_user_broker_account_id=package.requested_user_broker_account_id,
        target_paper_account_id=package.requested_paper_account_id,
        execution_mode=package.requested_execution_mode, runtime_scope_payload=runtime_scope_payload,
        risk_snapshot_payload=risk_snapshot_payload, account_snapshot_payload=account_snapshot_payload,
        credential_snapshot_payload=broker_snapshot_payload,
        previous_promotion_status=PROMOTION_STATE_ACTIVATION_REVIEW, committed_promotion_status=PROMOTION_STATE_ACTIVATED,
        review_input_hash=package.review_input_hash, decision_input_hash=decision.decision_input_hash,
        commit_reason=commit_reason, confirmation_hash=confirmation_hash, activation_commit_hash=activation_commit_hash,
        committed_by=actor, committed_at=committed_at, idempotency_key=(idempotency_key or None),
        algorithm_version=ALGORITHM_VERSION,
    )

    try:
        session.add(activation_commit)
        session.flush()

        previous_status = promotion_state.current_status
        new_status = PROMOTION_STATE_ACTIVATED
        if not _can_transition_activation_state(previous_status, new_status):
            raise ActivationError("INVALID_PROMOTION_STATE_TRANSITION", f"{previous_status} -> {new_status} 전이는 허용되지 않습니다.")

        new_version = promotion_state.status_version + 1
        state_hash = compute_promotion_state_hash(
            strategy_definition_id=strategy_definition_id, current_status=new_status, status_version=new_version,
            current_promotion_commit_id=promotion_state.current_promotion_commit_id, previous_event_hash=None,
            transitioned_at=committed_at, algorithm_version=ALGORITHM_VERSION,
        )
        promotion_state.current_status = new_status
        promotion_state.status_version = new_version
        promotion_state.state_hash = state_hash
        promotion_state.updated_by = actor

        event_hash = compute_promotion_state_event_hash(
            strategy_definition_id=strategy_definition_id, promotion_commit_id=int(commit.promotion_commit_id),
            previous_status=previous_status, new_status=new_status, human_decision_id=commit.human_decision_id,
            decision_package_id=commit.decision_package_id, actor=actor, occurred_at=committed_at,
            transition_reason=commit_reason, algorithm_version=ALGORITHM_VERSION,
        )
        history_entity = StrategyPromotionHistoryEntity(
            strategy_definition_id=strategy_definition_id, promotion_commit_id=int(commit.promotion_commit_id),
            previous_status=previous_status, new_status=new_status, transition_reason=commit_reason,
            human_decision_id=commit.human_decision_id, decision_package_id=commit.decision_package_id,
            actor=actor, event_hash=event_hash, occurred_at=committed_at, algorithm_version=ALGORITHM_VERSION,
            metadata_payload={
                "activation_review_package_id": activation_review_package_id,
                "activation_decision_id": activation_decision_id,
                "target_market_type": package.requested_market_type,
                "target_broker_code": package.requested_broker_code,
                "execution_mode": package.requested_execution_mode,
            },
        )
        session.add(history_entity)
        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict = session.scalar(
            select(StrategyActivationCommitEntity).where(
                StrategyActivationCommitEntity.strategy_definition_id == strategy_definition_id
            )
        )
        if conflict is not None:
            if idempotency_key and conflict.idempotency_key == idempotency_key:
                return _to_activation_commit_dict(session, conflict, idempotent_replay=True)
            raise ActivationError("ALREADY_ACTIVATED", f"Strategy Definition #{strategy_definition_id}은 이미 Activation Commit이 존재합니다.") from None
        decision_conflict = session.scalar(
            select(StrategyActivationCommitEntity).where(
                StrategyActivationCommitEntity.activation_decision_id == activation_decision_id
            )
        )
        if decision_conflict is not None:
            raise ActivationError("DUPLICATE_ACTIVATION_COMMIT", f"Activation Decision #{activation_decision_id}에 대한 Commit이 이미 존재합니다.") from None
        raise ActivationError("DUPLICATE_ACTIVATION_HISTORY", "동일 Promotion Commit에 대한 전이 History가 이미 존재합니다.") from None

    session.refresh(activation_commit)
    return _to_activation_commit_dict(session, activation_commit, idempotent_replay=False)


def _to_activation_commit_dict(
    session: Session, commit: StrategyActivationCommitEntity, *, idempotent_replay: bool
) -> dict[str, Any]:
    promotion_state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == commit.strategy_definition_id
        )
    )
    candidate_lifecycle_status: str | None = None
    definition = session.get(StrategyDefinitionEntity, commit.strategy_definition_id)
    if definition is not None and definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None:
            candidate_lifecycle_status = lifecycle.lifecycle_status

    return {
        "activation_commit_id": int(commit.activation_commit_id),
        "strategy_definition_id": commit.strategy_definition_id,
        "promotion_commit_id": commit.promotion_commit_id,
        "activation_review_package_id": commit.activation_review_package_id,
        "activation_decision_id": commit.activation_decision_id,
        "activation_committed": True,
        "strategy_promotion_status": promotion_state.current_status if promotion_state else None,
        "candidate_lifecycle_status": candidate_lifecycle_status,
        "previous_promotion_status": commit.previous_promotion_status,
        "current_promotion_status": commit.committed_promotion_status,
        "promotion_state_version": promotion_state.status_version if promotion_state else None,
        "activation_commit_hash": commit.activation_commit_hash,
        "target_market_type": commit.target_market_type,
        "target_broker_code": commit.target_broker_code,
        "target_account_kind": commit.target_account_kind,
        "target_user_broker_account_id": commit.target_user_broker_account_id,
        "execution_mode": commit.execution_mode,
        "committed_by": commit.committed_by,
        "committed_at": commit.committed_at,
        "deployment_status": FIXED_DEPLOYMENT_STATUS,
        "runtime_status": FIXED_RUNTIME_STATUS,
        "scheduler_status": FIXED_SCHEDULER_STATUS,
        "broker_connection_status": FIXED_BROKER_CONNECTION_STATUS,
        "order_execution_status": FIXED_ORDER_EXECUTION_STATUS,
        "idempotent_replay": idempotent_replay,
        "next_action": FIXED_NEXT_ACTION,
    }


# ---------------------------------------------------------------------------
# Query helpers.
# ---------------------------------------------------------------------------


def _compute_effective_package_status(session: Session, package: StrategyActivationReviewPackageEntity) -> dict[str, Any]:
    """§ STEP12-17 제한사항 보완(7) — Package 상태 의미 분리. Package
    자체는 불변(readiness_status는 생성 시점 값 그대로)이지만, API는
    "생성 시점에 어떤 상태였는가"(created_readiness_status)와 "지금 이
    Package를 어떻게 취급해야 하는가"(current_effective_status)를 분리해
    노출해야 한다. Package 생성이 유발한 PROMOTION_COMMITTED ->
    ACTIVATION_REVIEW 전이 자체는 Stale 조건에 전혀 포함되지 않으므로
    (§ check_activation_package_staleness는 Definition/Account/Credential/
    Risk/운영 Snapshot만 비교), Package 생성 직후에는 이 전이만으로
    STALE이 되지 않는다."""
    commit = session.scalar(
        select(StrategyActivationCommitEntity).where(
            StrategyActivationCommitEntity.activation_review_package_id == package.activation_review_package_id
        )
    )
    decision = session.scalar(
        select(StrategyActivationDecisionEntity).where(
            StrategyActivationDecisionEntity.activation_review_package_id == package.activation_review_package_id
        )
    )
    stale, stale_reasons = check_activation_package_staleness(session, package)
    if commit is not None:
        current_effective_status = "ACTIVATION_COMMITTED"
    elif stale:
        current_effective_status = "STALE"
    elif decision is not None:
        current_effective_status = "DECIDED"
    else:
        current_effective_status = package.readiness_status
    return {
        "created_readiness_status": package.readiness_status,
        "current_effective_status": current_effective_status,
        "stale": stale,
        "stale_reasons": stale_reasons,
        "decided": decision is not None,
        "activation_committed": commit is not None,
    }


def get_activation_review_package(
    session: Session, package_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    package = session.get(StrategyActivationReviewPackageEntity, package_id)
    if package is None:
        raise ActivationError("NOT_FOUND", f"Activation Review Package not found: {package_id}")
    if strategy_definition_id is not None and package.strategy_definition_id != strategy_definition_id:
        raise ActivationError("NOT_FOUND", f"Activation Review Package not found: {package_id}")
    result = _to_package_dict(package, idempotent_replay=False)
    result.update(_compute_effective_package_status(session, package))
    return result


def list_activation_review_packages(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyActivationReviewPackageEntity)
        .where(StrategyActivationReviewPackageEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyActivationReviewPackageEntity.activation_review_package_id.desc())
    )
    return [_to_package_dict(r, idempotent_replay=False) for r in rows]


def get_activation_review_package_checklist(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyActivationReviewPackageEntity, package_id)
    if package is None:
        raise ActivationError("NOT_FOUND", f"Activation Review Package not found: {package_id}")
    decision = session.scalar(
        select(StrategyActivationDecisionEntity).where(
            StrategyActivationDecisionEntity.activation_review_package_id == package_id
        )
    )
    confirmations = decision.checklist_payload if decision is not None else {}
    return {
        "activation_review_package_id": package_id,
        "checklist_template": build_activation_checklist_template(package.requested_execution_mode),
        "checklist_confirmations": confirmations,
    }


def get_activation_review_package_staleness(session: Session, package_id: int) -> dict[str, Any]:
    package = session.get(StrategyActivationReviewPackageEntity, package_id)
    if package is None:
        raise ActivationError("NOT_FOUND", f"Activation Review Package not found: {package_id}")
    stale, reasons = check_activation_package_staleness(session, package)
    return {"activation_review_package_id": package_id, "stale": stale, "reasons": reasons}


def get_activation_decision(session: Session, package_id: int) -> dict[str, Any] | None:
    decision = session.scalar(
        select(StrategyActivationDecisionEntity).where(
            StrategyActivationDecisionEntity.activation_review_package_id == package_id
        )
    )
    if decision is None:
        return None
    return _to_decision_dict(decision, idempotent_replay=False)


def get_activation_commit(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyActivationCommitEntity, commit_id)
    if commit is None:
        raise ActivationError("NOT_FOUND", f"Activation Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise ActivationError("NOT_FOUND", f"Activation Commit not found: {commit_id}")
    return _to_activation_commit_dict(session, commit, idempotent_replay=False)


def list_activation_commits(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyActivationCommitEntity)
        .where(StrategyActivationCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyActivationCommitEntity.activation_commit_id.desc())
    )
    return [_to_activation_commit_dict(session, r, idempotent_replay=False) for r in rows]


def get_activation_commit_provenance(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyActivationCommitEntity, commit_id)
    if commit is None:
        raise ActivationError("NOT_FOUND", f"Activation Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise ActivationError("NOT_FOUND", f"Activation Commit not found: {commit_id}")
    return {
        "activation_commit_id": int(commit.activation_commit_id),
        "runtime_scope_payload": commit.runtime_scope_payload,
        "risk_snapshot_payload": commit.risk_snapshot_payload,
        "account_snapshot_payload": commit.account_snapshot_payload,
        "credential_snapshot_payload": commit.credential_snapshot_payload,
        "activation_commit_hash": commit.activation_commit_hash,
    }


def get_activation_status(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    from stock_platform.ai.strategy_draft_approval.promotion_commit import get_promotion_state

    state = get_promotion_state(session, strategy_definition_id)
    commit = session.scalar(
        select(StrategyActivationCommitEntity).where(
            StrategyActivationCommitEntity.strategy_definition_id == strategy_definition_id
        )
    )
    definition = session.get(StrategyDefinitionEntity, strategy_definition_id)
    candidate_lifecycle_status: str | None = None
    if definition is not None and definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None:
            candidate_lifecycle_status = lifecycle.lifecycle_status

    return {
        "strategy_definition_id": strategy_definition_id,
        "activation_committed": commit is not None,
        "activation_commit_id": int(commit.activation_commit_id) if commit is not None else None,
        "strategy_promotion_status": state["current_status"],
        "candidate_lifecycle_status": candidate_lifecycle_status,
        "promotion_state_version": state["status_version"],
        "deployment_status": FIXED_DEPLOYMENT_STATUS,
        "runtime_status": FIXED_RUNTIME_STATUS,
        "scheduler_status": FIXED_SCHEDULER_STATUS,
        "broker_connection_status": FIXED_BROKER_CONNECTION_STATUS,
        "order_execution_status": FIXED_ORDER_EXECUTION_STATUS,
        "next_action": FIXED_NEXT_ACTION if commit is not None else "REVIEW_ACTIVATION",
    }
