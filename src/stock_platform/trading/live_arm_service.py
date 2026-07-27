"""STEP 8-8 / 9-4 — LIVE ARM (2단계 승인) 서비스.

LIVE ON 승인 후 관리자가 ARM 해야 주문 가능.
ARM Enable은 LIVE·Scheduler·Runtime을 변경하지 않는다.
ARM 만료 시 LIVE OFF + DISARM (Fail Closed).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.operation.live_health_gate import (
    evaluate_live_order_health,
)
from stock_platform.order.live_safety_audit import (
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_entities import LiveArmEvent
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

LIVE_ARM = "LIVE_ARM"
LIVE_DISARM = "LIVE_DISARM"
LIVE_ARM_EXPIRED = "LIVE_ARM_EXPIRED"
DEFAULT_ARM_TTL_SECONDS = 300


class LiveArmError(ValueError):
    """ARM 실패."""

    def __init__(self, code: str, message: str | None = None) -> None:
        msg = message or code
        super().__init__(msg)
        self.code = code
        self.message = msg


class LiveArmService:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def get_arm_status(self, user_broker_account_id: int) -> dict[str, Any]:
        uba = self._require_uba(user_broker_account_id)
        now = datetime.now(timezone.utc)
        expired = self._expire_if_needed(uba, actor="SYSTEM", commit=False)
        armed = bool(uba.live_armed) and not expired
        remaining = None
        if armed and uba.arm_expires_at is not None:
            remaining = max(
                0,
                int((uba.arm_expires_at - now).total_seconds()),
            )
        return {
            "user_broker_account_id": int(uba.user_broker_account_id),
            "user_id": int(uba.user_id),
            "broker_code": uba.broker_code.upper(),
            "live_order_enabled": bool(uba.live_order_enabled),
            "live_armed": armed,
            "arm_expires_at": (
                uba.arm_expires_at.isoformat()
                if uba.arm_expires_at
                else None
            ),
            "arm_armed_by": uba.arm_armed_by,
            "arm_armed_at": (
                uba.arm_armed_at.isoformat() if uba.arm_armed_at else None
            ),
            "arm_remaining_seconds": remaining,
            "arm_token_present": bool(uba.arm_token_hash),
        }

    def assert_arm_enable_preconditions(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """ARM ON 사전조건 — LIVE/Scheduler/Runtime은 변경하지 않음."""
        uba_id = int(user_broker_account_id)
        uba = self._require_uba(uba_id)
        if not bool(uba.is_active):
            raise LiveArmError("uba_inactive", "Account inactive")
        if not bool(uba.live_order_enabled):
            raise LiveArmError(
                "live_required",
                "LIVE must be ON before ARM enable",
            )
        pause = self._session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == uba_id
            )
        )
        if pause is not None and bool(pause.trading_paused):
            raise LiveArmError(
                "trading_paused", "Account trading is paused"
            )

        active = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == uba_id,
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    ),
                )
            )
            or 0
        )
        if active > 0:
            raise LiveArmError(
                "unresolved_conflicts",
                f"Unresolved conflicts remain: {active}",
            )
        pending = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == uba_id,
                    BrokerRecoveryConflictEntity.review_status
                    == "PENDING_REVIEW",
                )
            )
            or 0
        )
        if pending > 0:
            raise LiveArmError(
                "pending_review",
                f"PENDING_REVIEW remain: {pending}",
            )

        blocking = BrokerRecoveryConflictService(
            self._session
        ).count_blocking_orders_for_uba(uba_id)
        for key, code in (
            ("db_open", "db_open_orders"),
            ("submission_unknown", "submission_unknown"),
            ("cancel_pending", "cancel_pending"),
            ("replace_pending", "replace_pending"),
        ):
            if int(blocking.get(key) or 0) > 0:
                raise LiveArmError(code, f"{key} remain: {blocking[key]}")

        try:
            BrokerCredentialVaultService(
                self._session
            ).assert_live_order_allowed(
                uba_id, broker_code=str(uba.broker_code).upper()
            )
        except BrokerCredentialVaultError as exc:
            raise LiveArmError(exc.code, exc.message) from exc

        try:
            ks = KillSwitchService(self._session)
            scopes = [
                KillSwitchService.GLOBAL_SCOPE,
                uba_kill_switch_scope(uba_id),
                f"USER:{int(uba.user_id)}",
            ]
            if ks.is_active_for_scopes(scopes):
                raise LiveArmError(
                    "kill_switch_active",
                    "Kill switch is active (GLOBAL/USER/UBA)",
                )
        except LiveArmError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LiveArmError("kill_switch_unavailable", str(exc)) from exc

        health = evaluate_live_order_health(self._session)
        if not health.get("live_orders_allowed"):
            raise LiveArmError(
                "broker_unhealthy",
                f"Broker/system health not HEALTHY "
                f"(status={health.get('status')})",
            )

        trading = collect_scheduler_readiness()
        if trading.trading_scheduler_actual_state != "PAUSED":
            raise LiveArmError(
                "trading_scheduler_not_paused",
                f"Trading Scheduler must be PAUSED "
                f"(actual={trading.trading_scheduler_actual_state})",
            )
        if trading.trading_scheduler_desired_state != "PAUSE":
            raise LiveArmError(
                "trading_scheduler_desired_not_pause",
                f"Trading Scheduler desired must be PAUSE "
                f"(desired={trading.trading_scheduler_desired_state})",
            )
        return {
            "blocking": blocking,
            "active_review": active,
            "pending_review": pending,
            "trading_scheduler_actual": trading.trading_scheduler_actual_state,
            "live_order_enabled": bool(uba.live_order_enabled),
            "health_status": health.get("status"),
        }

    def arm(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        ttl_seconds: int | None = None,
        run_id: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
        enforce_gates: bool = False,
    ) -> dict[str, Any]:
        """ARM만 ON. LIVE·Scheduler·Runtime은 변경하지 않는다."""
        uba = self._require_uba(user_broker_account_id)
        before_live = bool(uba.live_order_enabled)
        before_arm = bool(uba.live_armed)

        if enforce_gates:
            if not (reason or "").strip():
                raise LiveArmError(
                    "reason_required", "Enable reason is required"
                )
            if not (correlation_id or "").strip():
                raise LiveArmError(
                    "correlation_id_required",
                    "correlation_id is required",
                )
            # 이미 ARM이면 idempotent (토큰 재발급·Audit 없음)
            if before_arm and uba.arm_expires_at is not None:
                now = datetime.now(timezone.utc)
                if uba.arm_expires_at > now:
                    status = self.get_arm_status(int(user_broker_account_id))
                    status.update(
                        {
                            "already_armed": True,
                            "arm_changed": False,
                            "live_unchanged": True,
                            "live_order_enabled": before_live,
                            "previous_arm": True,
                            "new_arm": True,
                            "reason": reason.strip()[:2000],
                            "correlation_id": correlation_id.strip()[:128],
                            "actor": actor,
                        }
                    )
                    # 원문 토큰은 재발급하지 않음
                    return status
            self.assert_arm_enable_preconditions(int(user_broker_account_id))
        else:
            # 레거시 경로 (내부/테스트)
            if not bool(uba.live_order_enabled):
                raise LiveArmError(
                    "LIVE_ORDER_DISABLED",
                    "LIVE_ORDER_DISABLED — enable LIVE before ARM",
                )
            if not bool(uba.is_active):
                raise LiveArmError("ACCOUNT_INACTIVE", "ACCOUNT_INACTIVE")

        policy = ResolvedRiskPolicyResolver(self._session).resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=int(user_broker_account_id),
        )
        ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else getattr(policy, "arm_ttl_seconds", DEFAULT_ARM_TTL_SECONDS)
        )
        if ttl <= 0:
            raise LiveArmError(
                "invalid_ttl", "arm_ttl_seconds must be > 0"
            )

        token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(token)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl)

        uba.live_armed = True
        uba.arm_token_hash = token_hash
        uba.arm_expires_at = expires
        uba.arm_armed_by = actor
        uba.arm_armed_at = now
        # LIVE 필드는 절대 변경하지 않음
        self._session.add(
            LiveArmEvent(
                user_broker_account_id=int(uba.user_broker_account_id),
                event_type=LIVE_ARM,
                arm_token_hash=token_hash,
                actor=actor,
                expires_at=expires,
                detail_json={
                    "ttl_seconds": ttl,
                    "run_id": run_id or correlation_id,
                    "reason": (reason or "")[:2000] or None,
                    "correlation_id": (correlation_id or "")[:128] or None,
                    "previous_arm": before_arm,
                    "new_arm": True,
                    "live": before_live,
                },
            )
        )
        self._session.flush()

        trading = collect_scheduler_readiness()
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ARM,
            actor=actor,
            run_id=run_id or correlation_id,
            user_id=int(uba.user_id),
            account_id=int(uba.user_broker_account_id),
            strategy_id=None,
            detail={
                "expires_at": expires.isoformat(),
                "ttl_seconds": ttl,
                "previous_arm": before_arm,
                "new_arm": True,
                "live": bool(uba.live_order_enabled),
                "broker_code": uba.broker_code.upper(),
                "reason": (reason or "")[:2000] or None,
                "correlation_id": (correlation_id or "")[:128] or None,
                "trading_scheduler_desired": (
                    trading.trading_scheduler_desired_state
                ),
                "trading_scheduler_actual": (
                    trading.trading_scheduler_actual_state
                ),
                "runtime_paused": True,
            },
            commit=False,
        )
        emit_live_order_telegram(
            event_type=LIVE_ARM,
            title="LIVE ARM",
            message=(
                f"UBA {uba.user_broker_account_id} armed by {actor} "
                f"until {expires.isoformat()}"
            ),
            detail={
                "user_broker_account_id": int(uba.user_broker_account_id),
                "expires_at": expires.isoformat(),
                "actor": actor,
            },
        )
        # 원문 토큰은 응답에만 1회 반환 (DB에는 해시만)
        status = self.get_arm_status(int(user_broker_account_id))
        status["arm_token"] = token
        status.update(
            {
                "already_armed": False,
                "arm_changed": True,
                "live_unchanged": before_live
                == bool(uba.live_order_enabled),
                "previous_arm": before_arm,
                "new_arm": True,
                "reason": (reason or "")[:2000] or None,
                "correlation_id": (correlation_id or "")[:128] or None,
                "actor": actor,
            }
        )
        return status

    def disarm(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        reason: str = "MANUAL",
        turn_live_off: bool = False,
        run_id: str | None = None,
        correlation_id: str | None = None,
        require_correlation_id: bool = False,
    ) -> dict[str, Any]:
        """ARM OFF. turn_live_off=False면 LIVE 유지. Scheduler/Runtime 미변경."""
        if not (reason or "").strip():
            raise LiveArmError(
                "reason_required", "Disarm reason is required"
            )
        if require_correlation_id and not (correlation_id or "").strip():
            raise LiveArmError(
                "correlation_id_required",
                "correlation_id is required",
            )
        uba = self._require_uba(user_broker_account_id)
        before_live = bool(uba.live_order_enabled)
        before_arm = bool(uba.live_armed)
        self._clear_arm(uba)
        if turn_live_off:
            uba.live_order_enabled = False
            uba.live_approved_at = None
            uba.live_approved_by = None
        self._session.add(
            LiveArmEvent(
                user_broker_account_id=int(uba.user_broker_account_id),
                event_type=LIVE_DISARM,
                arm_token_hash=None,
                actor=actor,
                expires_at=None,
                detail_json={
                    "reason": reason,
                    "turn_live_off": turn_live_off,
                    "run_id": run_id or correlation_id,
                    "correlation_id": (correlation_id or "")[:128] or None,
                    "previous_arm": before_arm,
                    "new_arm": False,
                    "live": bool(uba.live_order_enabled),
                },
            )
        )
        self._session.flush()
        trading = collect_scheduler_readiness()
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_DISARM,
            actor=actor,
            run_id=run_id or correlation_id,
            user_id=int(uba.user_id),
            account_id=int(uba.user_broker_account_id),
            strategy_id=None,
            detail={
                "reason": reason,
                "turn_live_off": turn_live_off,
                "previous_arm": before_arm,
                "new_arm": False,
                "live": bool(uba.live_order_enabled),
                "live_unchanged": (not turn_live_off)
                and before_live == bool(uba.live_order_enabled),
                "correlation_id": (correlation_id or "")[:128] or None,
                "trading_scheduler_desired": (
                    trading.trading_scheduler_desired_state
                ),
                "trading_scheduler_actual": (
                    trading.trading_scheduler_actual_state
                ),
            },
            commit=False,
        )
        emit_live_order_telegram(
            event_type=LIVE_DISARM,
            title="LIVE DISARM",
            message=(
                f"UBA {uba.user_broker_account_id} disarmed "
                f"({reason}) by {actor}"
            ),
            detail={
                "user_broker_account_id": int(uba.user_broker_account_id),
                "reason": reason,
                "actor": actor,
            },
        )
        status = self.get_arm_status(int(user_broker_account_id))
        status.update(
            {
                "arm_changed": before_arm != bool(uba.live_armed),
                "live_unchanged": before_live
                == bool(uba.live_order_enabled),
                "previous_arm": before_arm,
                "new_arm": False,
                "reason": reason,
                "correlation_id": (correlation_id or "")[:128] or None,
            }
        )
        return status

    def expire_if_needed(
        self,
        user_broker_account_id: int,
        *,
        actor: str = "SYSTEM",
    ) -> bool:
        uba = self._require_uba(user_broker_account_id)
        return self._expire_if_needed(uba, actor=actor, commit=False)

    def expire_all_due(self, *, actor: str = "SYSTEM") -> int:
        """만료된 ARM을 LIVE OFF로 되돌린다."""

        now = datetime.now(timezone.utc)
        rows = list(
            self._session.scalars(
                select(UserBrokerAccount).where(
                    UserBrokerAccount.live_armed.is_(True)
                )
            )
        )
        count = 0
        for uba in rows:
            if uba.arm_expires_at is None or uba.arm_expires_at <= now:
                self._expire_uba(uba, actor=actor)
                count += 1
        return count

    def validate_arm_token(
        self,
        user_broker_account_id: int,
        arm_token: str | None,
    ) -> tuple[bool, str]:
        """주문 직전 ARM 토큰 검증. 만료 시 LIVE OFF."""

        uba = self._require_uba(user_broker_account_id)
        if self._expire_if_needed(uba, actor="SYSTEM", commit=False):
            return False, "LIVE_ARM_EXPIRED"
        if not bool(uba.live_order_enabled):
            return False, "LIVE_ORDER_DISABLED"
        if not bool(uba.live_armed) or not uba.arm_token_hash:
            return False, "LIVE_NOT_ARMED"
        if not arm_token:
            return False, "ARM_TOKEN_MISSING"
        if not secrets.compare_digest(
            uba.arm_token_hash, self.hash_token(arm_token)
        ):
            return False, "ARM_TOKEN_MISMATCH"
        return True, "ARM_OK"

    def _expire_if_needed(
        self,
        uba: UserBrokerAccount,
        *,
        actor: str,
        commit: bool,
    ) -> bool:
        now = datetime.now(timezone.utc)
        if not bool(uba.live_armed):
            return False
        if uba.arm_expires_at is not None and uba.arm_expires_at > now:
            return False
        self._expire_uba(uba, actor=actor)
        if commit:
            self._session.commit()
        return True

    def _expire_uba(self, uba: UserBrokerAccount, *, actor: str) -> None:
        self._clear_arm(uba)
        # ARM 만료 시 LIVE OFF로 되돌림 (Fail Closed)
        uba.live_order_enabled = False
        uba.live_approved_at = None
        uba.live_approved_by = None
        self._session.add(
            LiveArmEvent(
                user_broker_account_id=int(uba.user_broker_account_id),
                event_type=LIVE_ARM_EXPIRED,
                arm_token_hash=None,
                actor=actor,
                expires_at=None,
                detail_json={"action": "LIVE_OFF"},
            )
        )
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ARM_EXPIRED,
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=int(uba.user_broker_account_id),
            strategy_id=None,
            detail={"action": "LIVE_OFF"},
            commit=False,
        )
        emit_live_order_telegram(
            event_type=LIVE_ARM_EXPIRED,
            title="LIVE ARM EXPIRED",
            message=(
                f"UBA {uba.user_broker_account_id} ARM expired → LIVE OFF"
            ),
            detail={
                "user_broker_account_id": int(uba.user_broker_account_id),
            },
        )

    @staticmethod
    def _clear_arm(uba: UserBrokerAccount) -> None:
        uba.live_armed = False
        uba.arm_token_hash = None
        uba.arm_expires_at = None
        uba.arm_armed_by = None
        uba.arm_armed_at = None

    def _require_uba(self, user_broker_account_id: int) -> UserBrokerAccount:
        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise LookupError("user broker account not found")
        return uba
