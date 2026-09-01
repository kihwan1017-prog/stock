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

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
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
    ARM_OFF,
    ARM_ON,
    LIVE_ARM_EXPIRED,
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
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

LIVE_ARM = ARM_ON
LIVE_DISARM = ARM_OFF
# LIVE_ARM_EXPIRED 는 live_safety_audit 에서 import
DEFAULT_ARM_TTL_SECONDS = 300
# force_renew 시 이 미만 연장은 NOOP (15초 스캔 spam 방지)
MIN_MEANINGFUL_ARM_EXTENSION_SECONDS = 60

logger = structlog.get_logger(__name__)


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
        self,
        user_broker_account_id: int,
        *,
        allow_auto_protective_open_orders: bool = False,
        allow_known_auto_entry_buys: bool = False,
        require_scheduler_paused: bool = True,
        require_stable_runtime: bool = True,
    ) -> dict[str, Any]:
        """ARM ON 사전조건 — LIVE/Scheduler/Runtime은 변경하지 않음.

        allow_auto_protective_open_orders:
          Unattended renew/restore — AUTO SELL open은 허용, UNKNOWN는 fail-closed.
        allow_known_auto_entry_buys:
          ACTIVE ARM force_renew 전용 — broker-confirmed AUTO ENTRY BUY 는 renew 차단 제외.
          initial ARM ON (force_renew=False) 에서는 항상 False.
        require_scheduler_paused:
          Manual ARM ON requires Scheduler PAUSED.
          Unattended force_renew allows RUNNING scheduler.
        require_stable_runtime:
          initial ARM ON 은 production/no-reload 필수.
          force_renew(이미 ARM)는 TTL 유지용으로 스킵 가능.
        """
        uba_id = int(user_broker_account_id)
        uba = self._require_uba(uba_id)
        if not bool(uba.is_active):
            raise LiveArmError("uba_inactive", "Account inactive")
        if require_stable_runtime:
            try:
                from stock_platform.operation.runtime_process_stability import (
                    RealRuntimeUnstableError,
                    assert_stable_runtime_for_real_trading,
                )

                assert_stable_runtime_for_real_trading(context="ARM_ENABLE")
            except RealRuntimeUnstableError as exc:
                raise LiveArmError(exc.code, exc.message) from exc
        if not bool(uba.live_order_enabled):
            raise LiveArmError(
                "live_required",
                "LIVE must be ON before ARM enable",
            )
        self._require_session_activation(uba)
        assert_uba_connection_ready(
            uba,
            raise_error=lambda c, m: LiveArmError(c, m),
        )
        recovery = assert_recovery_ready(
            self._session,
            uba_id,
            raise_error=lambda c, m: LiveArmError(c, m),
        )
        risk = assert_risk_account_not_paused(
            self._session,
            uba,
            raise_error=lambda c, m: LiveArmError(c, m),
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
        ).count_blocking_orders_for_uba(
            uba_id,
            exclude_auto_protective_exits=bool(
                allow_auto_protective_open_orders
            ),
            exclude_known_auto_entry_buys=bool(allow_known_auto_entry_buys),
            verify_upbit_broker_for_entry_buys=bool(
                allow_known_auto_entry_buys
            ),
        )
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
        if require_scheduler_paused:
            # 수동 ARM ON: 운영자가 Scheduler를 멈춘 뒤에만 무장
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
            "require_scheduler_paused": bool(require_scheduler_paused),
            "live_order_enabled": bool(uba.live_order_enabled),
            "health_status": health.get("status"),
            "recovery_status": recovery.get("recovery_status"),
            "account_paused": risk.get("account_paused"),
            "arm_ttl_seconds": risk.get("arm_ttl_seconds"),
            "allow_known_auto_entry_buys": bool(allow_known_auto_entry_buys),
            "open_order_class_counts": blocking.get("open_order_class_counts"),
            "ARM_RENEW_BLOCK_REASON": blocking.get("arm_renew_block_reason"),
        }

    def _require_session_activation(self, uba: UserBrokerAccount):
        """effective ACCOUNT/broker Activation. 없으면 ACTIVATION_INACTIVE."""

        from stock_platform.broker.live_transition_service import (
            LiveTradingTransitionService,
        )

        entity = LiveTradingTransitionService(self._session).peek_active(
            broker_code=str(uba.broker_code),
            user_broker_account_id=int(uba.user_broker_account_id),
        )
        if entity is None:
            raise LiveArmError(
                "ACTIVATION_INACTIVE",
                "No active live trading transition approval",
            )
        return entity

    def _clamp_arm_ttl(
        self,
        uba: UserBrokerAccount,
        requested_ttl: int | None,
        policy_ttl: int,
        *,
        now: datetime | None = None,
    ) -> tuple[int, datetime, Any]:
        """effective ARM TTL = min(요청, 잔여 Activation).

        무제한 ARM 금지. 절대 상한은 Activation 최대 창(시간×3600).
        """

        from stock_platform.common.settings import (
            LIVE_ACTIVATION_TTL_HOURS_MAX,
        )
        from stock_platform.trading.live_session_expiry import (
            activation_remaining_seconds,
            aware_utc,
        )

        current = now or datetime.now(timezone.utc)
        activation = self._require_session_activation(uba)
        remaining = activation_remaining_seconds(
            activation, now=current
        )
        if remaining <= 0:
            raise LiveArmError(
                "ACTIVATION_INACTIVE",
                "No active live trading transition approval",
            )
        if requested_ttl is not None:
            requested = int(requested_ttl)
        else:
            requested = int(policy_ttl)
        if requested <= 0:
            raise LiveArmError(
                "invalid_ttl", "arm_ttl_seconds must be > 0"
            )
        absolute_max = int(LIVE_ACTIVATION_TTL_HOURS_MAX) * 3600
        requested = min(requested, absolute_max)
        effective = min(requested, remaining)
        expires = current + timedelta(seconds=effective)
        act_exp = aware_utc(activation.expires_at)
        if act_exp is not None and expires > act_exp:
            expires = act_exp
            effective = max(1, remaining)
        return effective, expires, activation

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
        force_renew: bool = False,
        allow_auto_protective_open_orders: bool = False,
    ) -> dict[str, Any]:
        """ARM만 ON. LIVE·Scheduler·Runtime은 변경하지 않는다.

        force_renew: unattended renewal 전용 — 이미 ARM이어도 TTL/토큰 재발급.
        allow_auto_protective_open_orders: unattended — AUTO SELL open 허용.
        """
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
            # force_renew=True 이면 unattended lease 갱신 경로에서 TTL 재발급
            if (
                before_arm
                and uba.arm_expires_at is not None
                and not force_renew
            ):
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
            # force_renew=이미 무장된 unattended 세션 TTL 연장 — Scheduler RUNNING 허용
            self.assert_arm_enable_preconditions(
                int(user_broker_account_id),
                allow_auto_protective_open_orders=bool(
                    allow_auto_protective_open_orders
                ),
                allow_known_auto_entry_buys=bool(
                    force_renew and allow_auto_protective_open_orders
                ),
                require_scheduler_paused=not bool(force_renew),
                require_stable_runtime=not bool(force_renew),
            )
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
        now = datetime.now(timezone.utc)
        requested = (
            int(ttl_seconds)
            if ttl_seconds is not None
            else int(
                getattr(
                    policy, "arm_ttl_seconds", DEFAULT_ARM_TTL_SECONDS
                )
            )
        )
        ttl, expires, activation = self._clamp_arm_ttl(
            uba,
            ttl_seconds,
            int(
                getattr(
                    policy, "arm_ttl_seconds", DEFAULT_ARM_TTL_SECONDS
                )
            ),
            now=now,
        )
        act_exp = getattr(activation, "expires_at", None)
        clamp_meta = {
            "requested_ttl_seconds": requested,
            "effective_ttl_seconds": ttl,
            "clamped_to_activation": ttl < requested,
            "activation_id": getattr(
                activation, "live_trading_transition_id", None
            ),
            "activation_expires_at": (
                act_exp.isoformat() if act_exp is not None else None
            ),
        }

        # force_renew여도 의미 있는 TTL 연장이 없으면 NOOP (Telegram spam 방지)
        if force_renew and before_arm and uba.arm_expires_at is not None:
            current_exp = uba.arm_expires_at
            if current_exp.tzinfo is None:
                current_exp = current_exp.replace(tzinfo=timezone.utc)
            extension_seconds = (expires - current_exp).total_seconds()
            if extension_seconds < float(MIN_MEANINGFUL_ARM_EXTENSION_SECONDS):
                status = self.get_arm_status(int(user_broker_account_id))
                status.update(
                    {
                        "already_armed": True,
                        "arm_changed": False,
                        "live_unchanged": True,
                        "live_order_enabled": before_live,
                        "previous_arm": True,
                        "new_arm": True,
                        "reason": (reason or "")[:2000] or None,
                        "correlation_id": (
                            (correlation_id or "").strip()[:128] or None
                        ),
                        "actor": actor,
                        "skipped_reason": "NO_MEANINGFUL_EXTENSION",
                        "extension_seconds": extension_seconds,
                        **clamp_meta,
                    }
                )
                return status

        token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(token)

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
                    **clamp_meta,
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
                **clamp_meta,
            },
            commit=False,
        )
        # Telegram: 실제 mutation 경로만 (heartbeat/동일 expiry 금지)
        emit_live_order_telegram(
            event_type=LIVE_ARM,
            title="LIVE ARM",
            message=(
                f"UBA {uba.user_broker_account_id} armed by {actor} "
                f"until {expires.isoformat()}"
            ),
            detail={
                "user_broker_account_id": int(uba.user_broker_account_id),
                "broker_code": str(uba.broker_code or "").upper(),
                "expires_at": expires.isoformat(),
                "actor": actor,
                "previous_arm": before_arm,
                "arm_changed": True,
                "live": bool(uba.live_order_enabled),
                "new_arm": True,
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
                **clamp_meta,
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
        # 역순: Scheduler PAUSE 후에만 DISARM
        trading_gate = collect_scheduler_readiness()
        if trading_gate.trading_scheduler_actual_state != "PAUSED":
            raise LiveArmError(
                "trading_scheduler_not_paused",
                "Trading Scheduler must be PAUSED before DISARM",
            )
        if trading_gate.trading_scheduler_desired_state != "PAUSE":
            raise LiveArmError(
                "trading_scheduler_desired_not_pause",
                "Trading Scheduler desired must be PAUSE before DISARM",
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
                "broker_code": str(uba.broker_code or "").upper(),
                "reason": reason,
                "actor": actor,
                "previous_arm": before_arm,
                "new_arm": False,
                "live": bool(uba.live_order_enabled),
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

    def validate_arm_authorization(
        self,
        user_broker_account_id: int,
        *,
        arm_token: str | None = None,
        require_token_challenge: bool = False,
    ) -> tuple[bool, str]:
        """주문 직전 ARM 권한 검증. 만료 시 LIVE OFF.

        Design A — 인증된 서버 경로에서는 원문 token 없이
        UBA의 LIVE ON + ARM ON + TTL + hash 존재로 검증한다.
        arm_token이 전달되거나 require_token_challenge=True이면
        기존 challenge(원문↔hash)도 강제한다.
        """

        uba = self._require_uba(user_broker_account_id)
        if self._expire_if_needed(uba, actor="SYSTEM", commit=False):
            return False, "LIVE_ARM_EXPIRED"
        if not bool(uba.live_order_enabled):
            return False, "LIVE_ORDER_DISABLED"
        if not bool(uba.live_armed) or not uba.arm_token_hash:
            return False, "LIVE_NOT_ARMED"
        token = (arm_token or "").strip()
        if require_token_challenge or token:
            if not token:
                return False, "ARM_TOKEN_MISSING"
            if not secrets.compare_digest(
                uba.arm_token_hash, self.hash_token(token)
            ):
                return False, "ARM_TOKEN_MISMATCH"
        return True, "ARM_OK"

    def validate_arm_token(
        self,
        user_broker_account_id: int,
        arm_token: str | None,
    ) -> tuple[bool, str]:
        """레거시 challenge — 원문 token 필수."""

        return self.validate_arm_authorization(
            user_broker_account_id,
            arm_token=arm_token,
            require_token_challenge=True,
        )

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
        # Fail Closed: Scheduler RUN이면 LIVE OFF 전에 자동 PAUSE
        scheduler_auto_paused = False
        try:
            from stock_platform.trading.trading_scheduler_control_service import (
                TradingSchedulerControlService,
            )

            pause_out = TradingSchedulerControlService(self._session).pause(
                actor=actor or "SYSTEM",
                reason="ARM_EXPIRED:auto_pause_before_live_off",
                correlation_id=f"arm-expire-pause-{int(uba.user_broker_account_id)}",
                user_broker_account_id=int(uba.user_broker_account_id),
                require_correlation_id=False,
            )
            scheduler_auto_paused = True
            _ = pause_out
        except Exception:  # noqa: BLE001
            # pause 실패해도 ARM/LIVE OFF는 진행 (주문 경로 차단 우선)
            scheduler_auto_paused = False

        self._clear_arm(uba)
        # ARM 만료 시 LIVE OFF로 되돌림 (Fail Closed)
        uba.live_order_enabled = False
        uba.live_approved_at = None
        uba.live_approved_by = None

        # UPBIT: outage epoch + ACTIVE lease면 LIVE/ARM+stack 즉시 복구 스케줄
        try:
            if str(uba.broker_code or "").upper() == "UPBIT":
                from stock_platform.trading.upbit_execution_restore_epoch import (
                    upbit_execution_restore_epoch,
                )

                upbit_execution_restore_epoch.mark_outage("LIVE_ARM_EXPIRED")
                from stock_platform.trading.live_unattended_authorization_service import (
                    LiveUnattendedAuthorizationService,
                    STATUS_ACTIVE,
                )

                unattended = LiveUnattendedAuthorizationService(self._session)
                lease = unattended.get_active(int(uba.user_broker_account_id))
                if (
                    lease is not None
                    and str(lease.status_code or "").upper() == STATUS_ACTIVE
                ):
                    _schedule_upbit_lease_restore_after_arm_expiry(
                        int(uba.user_broker_account_id),
                        actor="SYSTEM_ARM_EXPIRED_LEASE_RESTORE",
                    )
        except Exception:  # noqa: BLE001
            pass

        self._session.add(
            LiveArmEvent(
                user_broker_account_id=int(uba.user_broker_account_id),
                event_type=LIVE_ARM_EXPIRED,
                arm_token_hash=None,
                actor=actor,
                expires_at=None,
                detail_json={
                    "action": "LIVE_OFF",
                    "scheduler_auto_paused": scheduler_auto_paused,
                },
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
            detail={
                "action": "LIVE_OFF",
                "scheduler_auto_paused": scheduler_auto_paused,
            },
            commit=False,
        )
        broker = str(getattr(uba, "broker_code", "") or "").upper()
        broker_ko = {
            "KIWOOM": "키움증권",
            "UPBIT": "업비트",
        }.get(broker, broker or "계좌")
        pause_note = "Scheduler: 일시정지" if scheduler_auto_paused else "Scheduler: 유지"
        emit_live_order_telegram(
            event_type=LIVE_ARM_EXPIRED,
            title="⚠️ 자동매매 승인 만료",
            message=(
                f"계좌: {broker_ko}\n"
                f"상태: ARM 승인 시간이 만료되어 실거래가 안전하게 중지되었습니다.\n"
                f"LIVE: 꺼짐\n"
                f"ARM: 만료\n"
                f"{pause_note}\n"
                f"UBA: {int(uba.user_broker_account_id)}"
            ),
            detail={
                "user_broker_account_id": int(uba.user_broker_account_id),
                "broker_code": broker,
                "scheduler_auto_paused": scheduler_auto_paused,
                "reason_ko": "ARM 승인 시간 만료로 LIVE가 안전하게 중지됨",
                "account_display": f"{broker_ko} UBA {int(uba.user_broker_account_id)}",
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


def _schedule_upbit_lease_restore_after_arm_expiry(
    user_broker_account_id: int,
    *,
    actor: str,
) -> None:
    """ARM TTL 만료 직후 ACTIVE lease면 LIVE/ARM+stack 복구를 비동기 스케줄.

    expire 트랜잭션 commit 이후에 동작하도록 짧게 delay한다.
    """

    import asyncio
    import threading
    import time

    uba_id = int(user_broker_account_id)

    async def _run() -> None:
        # expire commit 플러시 대기
        await asyncio.sleep(0.35)
        from stock_platform.database.session import get_session_factory
        from stock_platform.trading.live_unattended_authorization_service import (
            LiveUnattendedAuthorizationService,
        )

        sf = get_session_factory()
        session = sf()
        try:
            result = LiveUnattendedAuthorizationService(
                session
            ).restore_from_active_lease(
                uba_id,
                actor=actor,
                restore_stack=True,
            )
            session.commit()
            logger.info(
                "upbit_arm_expired_lease_restore",
                uba_id=uba_id,
                restored=result.get("restored"),
                reason=result.get("reason"),
            )
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.exception(
                "upbit_arm_expired_lease_restore_failed", uba_id=uba_id
            )
        finally:
            session.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        def _thread_main() -> None:
            time.sleep(0.35)
            asyncio.run(_run())

        threading.Thread(
            target=_thread_main,
            name=f"arm-expire-restore-{uba_id}",
            daemon=True,
        ).start()
        return

    loop.create_task(_run(), name=f"arm-expire-restore-{uba_id}")
