"""STEP 8-7 — UserBrokerAccount LIVE 승인 서비스."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
from stock_platform.order.live_safety_audit import (
    LIVE_OFF,
    LIVE_ON,
    emit_live_safety_audit,
)
from stock_platform.operation.live_health_gate import (
    evaluate_live_order_health,
)
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)


class LiveOrderApprovalError(ValueError):
    """LIVE 승인 변경 실패."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LiveOrderApprovalService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_status(self, user_broker_account_id: int) -> dict[str, Any]:
        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise LookupError("user broker account not found")
        policy = ResolvedRiskPolicyResolver(self._session).resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=int(user_broker_account_id),
        )
        return {
            "user_broker_account_id": int(uba.user_broker_account_id),
            "user_id": int(uba.user_id),
            "broker_code": uba.broker_code.upper(),
            "account_alias": uba.account_alias,
            "masked_account_number": uba.masked_account_number,
            "is_active": bool(uba.is_active),
            "live_order_enabled": bool(uba.live_order_enabled),
            "live_approved_at": (
                uba.live_approved_at.isoformat()
                if uba.live_approved_at
                else None
            ),
            "live_approved_by": uba.live_approved_by,
            "live_armed": bool(getattr(uba, "live_armed", False)),
            "arm_expires_at": (
                uba.arm_expires_at.isoformat()
                if getattr(uba, "arm_expires_at", None)
                else None
            ),
            "risk": {
                "max_order_amount": str(policy.max_order_amount),
                "max_order_quantity": str(policy.max_order_quantity),
                "daily_order_limit": int(policy.daily_order_limit),
                "daily_max_loss_amount": str(policy.daily_max_loss_amount),
                "duplicate_order_window_seconds": int(
                    policy.duplicate_order_window_seconds
                ),
                "max_open_orders": int(policy.max_open_orders),
                "max_slippage_rate": str(policy.max_slippage_rate),
                "anomaly_orders_per_minute": int(
                    policy.anomaly_orders_per_minute
                ),
                "arm_ttl_seconds": int(policy.arm_ttl_seconds),
            },
        }

    def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(UserBrokerAccount).where(
                    UserBrokerAccount.user_id == int(user_id)
                )
            )
        )
        return [
            self.get_status(int(r.user_broker_account_id)) for r in rows
        ]

    def assert_live_enable_preconditions(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """LIVE ON 사전조건 — ARM/Scheduler는 변경하지 않음."""
        uba_id = int(user_broker_account_id)
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None or not uba.is_active:
            raise LiveOrderApprovalError(
                "uba_inactive", "Account not found or inactive"
            )
        if bool(uba.live_armed):
            raise LiveOrderApprovalError(
                "arm_must_be_off",
                "ARM must be OFF before LIVE enable in STEP gate",
            )
        assert_uba_connection_ready(
            uba,
            raise_error=lambda c, m: LiveOrderApprovalError(c, m),
        )
        recovery = assert_recovery_ready(
            self._session,
            uba_id,
            raise_error=lambda c, m: LiveOrderApprovalError(c, m),
        )
        risk = assert_risk_account_not_paused(
            self._session,
            uba,
            raise_error=lambda c, m: LiveOrderApprovalError(c, m),
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
            raise LiveOrderApprovalError(
                "unresolved_conflicts",
                f"Unresolved conflicts remain: {active}",
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
                raise LiveOrderApprovalError(
                    code, f"{key} remain: {blocking[key]}"
                )
        try:
            BrokerCredentialVaultService(
                self._session
            ).assert_live_order_allowed(
                uba_id, broker_code=str(uba.broker_code).upper()
            )
        except BrokerCredentialVaultError as exc:
            raise LiveOrderApprovalError(exc.code, exc.message) from exc
        try:
            ks = KillSwitchService(self._session)
            scopes = [
                KillSwitchService.GLOBAL_SCOPE,
                uba_kill_switch_scope(uba_id),
                f"USER:{int(uba.user_id)}",
            ]
            if ks.is_active_for_scopes(scopes):
                raise LiveOrderApprovalError(
                    "kill_switch_active",
                    "Kill switch is active (GLOBAL/USER/UBA)",
                )
        except LiveOrderApprovalError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LiveOrderApprovalError(
                "kill_switch_unavailable", str(exc)
            ) from exc

        health = evaluate_live_order_health(self._session)
        if not health.get("live_orders_allowed"):
            raise LiveOrderApprovalError(
                "broker_unhealthy",
                f"Broker/system health not HEALTHY "
                f"(status={health.get('status')})",
            )

        trading = collect_scheduler_readiness()
        if trading.trading_scheduler_actual_state != "PAUSED":
            raise LiveOrderApprovalError(
                "trading_scheduler_not_paused",
                f"Trading Scheduler must be PAUSED "
                f"(actual={trading.trading_scheduler_actual_state})",
            )
        if trading.trading_scheduler_desired_state != "PAUSE":
            raise LiveOrderApprovalError(
                "trading_scheduler_desired_not_pause",
                f"Trading Scheduler desired must be PAUSE "
                f"(desired={trading.trading_scheduler_desired_state})",
            )
        return {
            "blocking": blocking,
            "active_review": active,
            "trading_scheduler_actual": trading.trading_scheduler_actual_state,
            "live_armed": bool(uba.live_armed),
            "health_status": health.get("status"),
            "recovery_status": recovery.get("recovery_status"),
            "account_paused": risk.get("account_paused"),
        }

    def set_live_enabled(
        self,
        user_broker_account_id: int,
        *,
        enabled: bool,
        actor: str,
        reason: str | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
        enforce_enable_gates: bool = True,
    ) -> dict[str, Any]:
        """LIVE 플래그 변경.

        LIVE OFF 시 Scheduler가 RUN이면 Fail Closed로 자동 PAUSE한다.
        ARM은 변경하지 않으며, LIVE OFF 전 ARM OFF는 계속 강제한다.
        """
        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise LookupError("user broker account not found")

        before = bool(uba.live_order_enabled)
        before_arm = bool(getattr(uba, "live_armed", False))
        scheduler_auto_paused = False

        if enabled:
            if not (reason or "").strip():
                raise LiveOrderApprovalError(
                    "reason_required", "Enable reason is required"
                )
            if not (correlation_id or "").strip():
                raise LiveOrderApprovalError(
                    "correlation_id_required",
                    "correlation_id is required",
                )
            if before:
                # Idempotent — ARM/상태 변경 없음
                status = self.get_status(int(user_broker_account_id))
                status.update(
                    {
                        "resumed": False,
                        "already_enabled": True,
                        "live_changed": False,
                        "arm_unchanged": True,
                        "arm": before_arm,
                        "reason": reason.strip()[:2000],
                        "correlation_id": correlation_id.strip()[:128],
                        "actor": actor,
                    }
                )
                return status
            if enforce_enable_gates:
                # 서버에서 Pre-flight 재계산 — 프론트 결과만 신뢰하지 않음
                from stock_platform.operation.runtime_preflight_service import (
                    RuntimePreflightService,
                )

                RuntimePreflightService(
                    self._session
                ).assert_ready_for_live_on(int(user_broker_account_id))
                self.assert_live_enable_preconditions(
                    int(user_broker_account_id)
                )
        else:
            # LIVE OFF — ARM OFF 필수, Scheduler RUN이면 자동 PAUSE (Fail Closed)
            if enforce_enable_gates:
                if bool(getattr(uba, "live_armed", False)):
                    raise LiveOrderApprovalError(
                        "arm_must_be_off",
                        "ARM must be OFF before LIVE disable",
                    )
                trading = collect_scheduler_readiness()
                needs_pause = (
                    trading.trading_scheduler_actual_state != "PAUSED"
                    or trading.trading_scheduler_desired_state != "PAUSE"
                )
                if needs_pause:
                    from stock_platform.trading.trading_scheduler_control_service import (
                        TradingSchedulerControlError,
                        TradingSchedulerControlService,
                    )

                    try:
                        TradingSchedulerControlService(self._session).pause(
                            actor=actor,
                            reason=(
                                (
                                    (reason or "LIVE_OFF").strip()[:1800]
                                    + ":auto_pause_before_live_off"
                                )[:2000]
                            ),
                            correlation_id=(
                                (correlation_id or "").strip()
                                or f"live-off-pause-{int(user_broker_account_id)}"
                            )[:128],
                            user_broker_account_id=int(
                                user_broker_account_id
                            ),
                            require_correlation_id=False,
                        )
                        scheduler_auto_paused = True
                    except TradingSchedulerControlError as exc:
                        raise LiveOrderApprovalError(
                            "trading_scheduler_pause_failed",
                            "Fail Closed: Scheduler PAUSE failed before "
                            f"LIVE OFF ({exc.code})",
                        ) from exc
                    trading = collect_scheduler_readiness()
                    if (
                        trading.trading_scheduler_actual_state != "PAUSED"
                        or trading.trading_scheduler_desired_state != "PAUSE"
                    ):
                        raise LiveOrderApprovalError(
                            "trading_scheduler_pause_failed",
                            "Fail Closed: Scheduler still not PAUSED "
                            "after auto-pause",
                        )

        uba.live_order_enabled = bool(enabled)
        if enabled:
            uba.live_approved_at = datetime.now(timezone.utc)
            uba.live_approved_by = actor
        else:
            uba.live_approved_at = None
            uba.live_approved_by = None
        # ARM 필드는 절대 변경하지 않음
        self._session.flush()

        event = LIVE_ON if enabled else LIVE_OFF
        emit_live_safety_audit(
            self._session,
            event_type=event,
            actor=actor,
            run_id=run_id or correlation_id,
            user_id=int(uba.user_id),
            account_id=int(uba.user_broker_account_id),
            strategy_id=None,
            detail={
                "action": "ENABLE" if enabled else "DISABLE",
                "before": before,
                "after": bool(enabled),
                "previous_live": before,
                "new_live": bool(enabled),
                "arm": bool(getattr(uba, "live_armed", False)),
                "broker_code": uba.broker_code.upper(),
                "reason": (reason or "")[:2000] or None,
                "correlation_id": (correlation_id or "")[:128] or None,
                "result": "SUCCESS",
                "admin_user_id": actor,
                "scheduler_auto_paused": scheduler_auto_paused,
                "previous_state": {"live": before, "arm": before_arm},
                "new_state": {
                    "live": bool(enabled),
                    "arm": bool(getattr(uba, "live_armed", False)),
                },
            },
            commit=False,
        )
        status = self.get_status(int(user_broker_account_id))
        status.update(
            {
                "resumed": True if enabled and not before else False,
                "already_enabled": False,
                "live_changed": before != bool(enabled),
                "arm_unchanged": before_arm
                == bool(getattr(uba, "live_armed", False)),
                "previous_live": before,
                "scheduler_auto_paused": scheduler_auto_paused,
                "reason": (reason or "")[:2000] or None,
                "correlation_id": (correlation_id or "")[:128] or None,
                "actor": actor,
            }
        )
        return status
