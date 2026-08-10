"""STEP 9-5 — Trading Scheduler Start/Pause 제어 (주문·Runner 미기동)."""

from __future__ import annotations

from datetime import datetime, timezone
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
    SCHEDULER_PAUSE,
    SCHEDULER_RUN,
    emit_live_safety_audit,
)
from stock_platform.realtime.live_runtime_control import (
    should_keep_upbit_on_krx_close,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)
from stock_platform.operation.runtime_control_repository import (
    RuntimeControlConflictError,
    RuntimeControlRepository,
)
from stock_platform.operation.startup_runtime_policy import (
    count_global_submission_unknown,
)
from stock_platform.trading.trading_scheduler_control import (
    get_trading_scheduler_control_meta,
    get_trading_scheduler_desired_state,
    hydrate_trading_scheduler_control,
    set_trading_scheduler_desired_state,
)


class TradingSchedulerControlError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# 관찰·게이트 여유 (초)
MIN_ARM_REMAINING_FOR_START = 120
DEFAULT_OBSERVE_SECONDS = 25


class TradingSchedulerControlService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def status(self) -> dict[str, Any]:
        running = bool(realtime_trading_scheduler.scheduler.running)
        jobs = []
        for job in realtime_trading_scheduler.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": getattr(job, "name", None),
                    "next_run_time": (
                        str(job.next_run_time) if job.next_run_time else None
                    ),
                }
            )
        meta = get_trading_scheduler_control_meta()
        row = RuntimeControlRepository(
            self._session
        ).get_trading_scheduler_row(create_if_missing=False)
        st = realtime_strategy_runner.status()
        ex = realtime_execution_runner.status()
        actual = "RUNNING" if running else "PAUSED"
        health = "HEALTHY" if running else "PAUSED"
        if row and row.blocked_reason and not running:
            health = "BLOCKED"
        return {
            "desired_state": get_trading_scheduler_desired_state(),
            "actual_state": actual,
            "health": health,
            "running": running,
            "heartbeat": {
                "last_tick_at": meta.get("last_tick_at"),
                "tick_count": meta.get("tick_count"),
                "last_heartbeat_at": (
                    row.last_heartbeat_at.isoformat()
                    if row and row.last_heartbeat_at
                    else None
                ),
            },
            "persisted": bool(row is not None),
            "restored_on_startup": bool(meta.get("restored_on_startup")),
            "blocked_reason": (
                row.blocked_reason if row else meta.get("blocked_reason")
            ),
            "updated_at": (
                row.updated_at.isoformat() if row and row.updated_at else None
            ),
            "requested_by": row.requested_by if row else meta.get("actor"),
            "requested_reason": (
                row.requested_reason if row else meta.get("reason")
            ),
            "correlation_id": (
                row.correlation_id if row else meta.get("correlation_id")
            ),
            "startup_restore_attempted": (
                bool(row.startup_restore_attempted) if row else False
            ),
            "startup_restore_result": (
                row.startup_restore_result if row else None
            ),
            "version": int(row.version) if row else meta.get("version"),
            "jobs": jobs,
            "job_count": len(jobs),
            "control": meta,
            "strategy_runner_running": bool(st.get("running")),
            "strategy_active_scopes": int(st.get("active_scopes") or 0),
            "execution_runner_running": bool(ex.get("running")),
            "order_path_idle": (
                int(st.get("active_scopes") or 0) == 0
                and not bool(ex.get("running"))
            ),
            "broker_market_hours": {
                "KRX": {
                    "applies_krx_session": True,
                    "policy": "SESSION_TIMELINE",
                },
                "UPBIT": {
                    "applies_krx_session": False,
                    "policy": "24/7_SUBJECT_TO_RECOVERY_KILL_ARM",
                    "keep_on_krx_close": should_keep_upbit_on_krx_close(),
                },
            },
        }

    def assert_start_preconditions(
        self,
        *,
        user_broker_account_id: int,
        min_arm_remaining_seconds: int = MIN_ARM_REMAINING_FOR_START,
    ) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None or not uba.is_active:
            raise TradingSchedulerControlError(
                "uba_inactive", "Account not found or inactive"
            )
        if not bool(uba.live_order_enabled):
            raise TradingSchedulerControlError(
                "live_required", "LIVE must be ON"
            )
        if not bool(uba.live_armed):
            raise TradingSchedulerControlError(
                "arm_required", "ARM must be ON"
            )
        assert_uba_connection_ready(
            uba,
            raise_error=lambda c, m: TradingSchedulerControlError(c, m),
        )
        assert_recovery_ready(
            self._session,
            uba_id,
            raise_error=lambda c, m: TradingSchedulerControlError(c, m),
        )
        assert_risk_account_not_paused(
            self._session,
            uba,
            raise_error=lambda c, m: TradingSchedulerControlError(c, m),
        )
        now = datetime.now(timezone.utc)
        expires = uba.arm_expires_at
        if expires is None:
            raise TradingSchedulerControlError(
                "arm_ttl_missing", "ARM expires_at missing"
            )
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        remaining = int((expires - now).total_seconds())
        if remaining <= 0:
            raise TradingSchedulerControlError(
                "arm_expired", "ARM already expired"
            )
        if remaining < int(min_arm_remaining_seconds):
            raise TradingSchedulerControlError(
                "arm_ttl_insufficient",
                f"ARM remaining {remaining}s < {min_arm_remaining_seconds}s",
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
            raise TradingSchedulerControlError(
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
            raise TradingSchedulerControlError(
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
                raise TradingSchedulerControlError(
                    code, f"{key} remain: {blocking[key]}"
                )

        try:
            BrokerCredentialVaultService(
                self._session
            ).assert_live_order_allowed(
                uba_id, broker_code=str(uba.broker_code).upper()
            )
        except BrokerCredentialVaultError as exc:
            raise TradingSchedulerControlError(
                exc.code, exc.message
            ) from exc

        try:
            ks = KillSwitchService(self._session)
            scopes = [
                KillSwitchService.GLOBAL_SCOPE,
                uba_kill_switch_scope(uba_id),
                f"USER:{int(uba.user_id)}",
            ]
            if ks.is_active_for_scopes(scopes):
                raise TradingSchedulerControlError(
                    "kill_switch_active",
                    "Kill switch is active",
                )
        except TradingSchedulerControlError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TradingSchedulerControlError(
                "kill_switch_unavailable", str(exc)
            ) from exc

        health = evaluate_live_order_health(self._session)
        if not health.get("live_orders_allowed"):
            raise TradingSchedulerControlError(
                "broker_unhealthy",
                f"health={health.get('status')}",
            )

        # Runner / Strategy — hub dispatch만 켜져 있고 scope=0 이면 주문 경로 없음
        st = realtime_strategy_runner.status()
        ex = realtime_execution_runner.status()
        if int(st.get("active_scopes") or 0) > 0:
            raise TradingSchedulerControlError(
                "strategy_scopes_active",
                f"Strategy active_scopes={st.get('active_scopes')}",
            )
        if bool(ex.get("running")):
            raise TradingSchedulerControlError(
                "execution_runner_active",
                "Execution runner already running",
            )

        strategy_idle = self._strategy_runtime_counts(uba_id)
        if strategy_idle["active_runtime"] > 0:
            raise TradingSchedulerControlError(
                "strategy_runtime_active",
                "Strategy runtime active > 0",
            )
        # active strategy link는 자동매매 준비에 필요 — link만으로 주문 경로 없음.
        # 주문 차단은 active_runtime / strategy·execution runner로 Fail Closed.
        # (구 STEP 9-5: links=0 강제 → 자동매매 UBA에서 Scheduler RUN과 충돌)

        return {
            "uba_id": uba_id,
            "user_id": int(uba.user_id),
            "broker_code": uba.broker_code.upper(),
            "live": True,
            "arm": True,
            "arm_expires_at": expires.isoformat(),
            "arm_remaining_seconds": remaining,
            "blocking": blocking,
            "strategy": strategy_idle,
            "health_status": health.get("status"),
            "active_links_allowed": True,
            "note": (
                "active_links may be >0; orders still blocked until "
                "strategy/execution runtime starts"
            ),
        }

    def start(
        self,
        *,
        actor: str,
        reason: str,
        correlation_id: str,
        user_broker_account_id: int,
        min_arm_remaining_seconds: int = MIN_ARM_REMAINING_FOR_START,
        enforce_gates: bool = True,
    ) -> dict[str, Any]:
        if not (reason or "").strip():
            raise TradingSchedulerControlError(
                "reason_required", "Start reason is required"
            )
        if not (correlation_id or "").strip():
            raise TradingSchedulerControlError(
                "correlation_id_required",
                "correlation_id is required",
            )

        prev_desired = get_trading_scheduler_desired_state()
        prev_running = bool(realtime_trading_scheduler.scheduler.running)
        gate: dict[str, Any] = {}
        if enforce_gates:
            try:
                gate = self.assert_start_preconditions(
                    user_broker_account_id=int(user_broker_account_id),
                    min_arm_remaining_seconds=min_arm_remaining_seconds,
                )
            except TradingSchedulerControlError as exc:
                # 이미 RUN인데 LIVE/ARM 게이트 실패 → Fail Closed PAUSE
                if prev_running and exc.code in {
                    "live_required",
                    "arm_required",
                    "arm_expired",
                    "arm_ttl_missing",
                    "arm_ttl_insufficient",
                    "uba_inactive",
                }:
                    self.pause(
                        actor=actor,
                        reason=f"fail_closed_gate:{exc.code}",
                        correlation_id=correlation_id.strip()[:128],
                        user_broker_account_id=int(user_broker_account_id),
                        require_correlation_id=False,
                    )
                raise

        if prev_running:
            # Idempotent — 재시작·Audit 없음
            status = self.status()
            status.update(
                {
                    "already_running": True,
                    "scheduler_changed": False,
                    "previous_desired": prev_desired,
                    "previous_actual": "RUNNING",
                    "reason": reason.strip()[:2000],
                    "correlation_id": correlation_id.strip()[:128],
                    "actor": actor,
                    "gate": gate,
                    "live_unchanged": True,
                    "arm_unchanged": True,
                    "runners_started": False,
                }
            )
            return status

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        arm_expires_before = (
            uba.arm_expires_at.isoformat()
            if uba is not None and uba.arm_expires_at
            else None
        )
        live_before = bool(uba.live_order_enabled) if uba else None
        arm_before = bool(uba.live_armed) if uba else None

        set_trading_scheduler_desired_state(
            "RUN",
            actor=actor,
            reason=reason.strip()[:2000],
            correlation_id=correlation_id.strip()[:128],
        )
        repo = RuntimeControlRepository(self._session)
        try:
            db_row = repo.update_trading_scheduler_desired(
                desired_state="RUN",
                actor=actor,
                reason=reason.strip()[:2000],
                correlation_id=correlation_id.strip()[:128],
                last_actual_state=None,
                blocked_reason=None,
            )
            hydrate_trading_scheduler_control(
                desired_state=db_row.desired_state,
                actor=db_row.requested_by,
                reason=db_row.requested_reason,
                correlation_id=db_row.correlation_id,
                updated_at=db_row.updated_at.isoformat(),
                version=int(db_row.version),
                persisted=True,
            )
            emit_live_safety_audit(
                self._session,
                event_type="TRADING_SCHEDULER_DESIRED_STATE_CHANGED",
                actor=actor,
                run_id=correlation_id.strip()[:128],
                user_id=gate.get("user_id"),
                account_id=int(user_broker_account_id),
                strategy_id=None,
                detail={
                    "previous_desired": prev_desired,
                    "new_desired": "RUN",
                    "reason": reason.strip()[:2000],
                    "correlation_id": correlation_id.strip()[:128],
                    "version": int(db_row.version),
                },
                commit=False,
            )
        except RuntimeControlConflictError as exc:
            raise TradingSchedulerControlError(
                "version_conflict", str(exc)
            ) from exc
        realtime_trading_scheduler.start()
        repo.touch_heartbeat(last_actual_state="RUNNING")

        def _compensate_scheduler_start(code: str, message: str) -> None:
            """프로세스 Scheduler 기동 후 검증 실패 시 PAUSE로 보상."""
            try:
                if realtime_trading_scheduler.scheduler.running:
                    realtime_trading_scheduler.scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
            try:
                set_trading_scheduler_desired_state(
                    "PAUSE",
                    actor=actor,
                    reason=f"COMPENSATE:{code}:{message}"[:2000],
                    correlation_id=correlation_id.strip()[:128],
                )
                repo.update_trading_scheduler_desired(
                    desired_state="PAUSE",
                    actor=actor,
                    reason=f"COMPENSATE:{code}"[:2000],
                    correlation_id=correlation_id.strip()[:128],
                    last_actual_state="PAUSED",
                    blocked_reason=code,
                )
                repo.touch_heartbeat(last_actual_state="PAUSED")
            except Exception:  # noqa: BLE001
                pass
            emit_live_safety_audit(
                self._session,
                event_type="SCHEDULER_RUN_COMPENSATED",
                actor=actor,
                run_id=correlation_id.strip()[:128],
                user_id=gate.get("user_id"),
                account_id=int(user_broker_account_id),
                strategy_id=None,
                detail={
                    "result": "COMPENSATED",
                    "failure_reason": message,
                    "code": code,
                    "correlation_id": correlation_id.strip()[:128],
                    "user_broker_account_id": int(user_broker_account_id),
                    "admin_user_id": actor,
                },
                commit=False,
            )
            raise TradingSchedulerControlError(code, message)

        # LIVE/ARM 미변경 재확인
        if uba is not None:
            self._session.refresh(uba)
            if bool(uba.live_order_enabled) != bool(live_before):
                _compensate_scheduler_start(
                    "live_mutated", "LIVE changed during scheduler start"
                )
            if bool(uba.live_armed) != bool(arm_before):
                _compensate_scheduler_start(
                    "arm_mutated", "ARM changed during scheduler start"
                )
            after_exp = (
                uba.arm_expires_at.isoformat() if uba.arm_expires_at else None
            )
            if after_exp != arm_expires_before:
                _compensate_scheduler_start(
                    "arm_ttl_refreshed",
                    "ARM TTL must not be refreshed by scheduler start",
                )

        # Runner 미기동 확인 (실행 주문 경로)
        st_after = realtime_strategy_runner.status()
        ex_after = realtime_execution_runner.status()
        if int(st_after.get("active_scopes") or 0) > 0:
            _compensate_scheduler_start(
                "strategy_scopes_started",
                "Scheduler start must not activate strategy scopes",
            )
        if bool(ex_after.get("running")):
            _compensate_scheduler_start(
                "execution_runner_started",
                "Scheduler start must not start execution runner",
            )

        status = self.status()
        detail = {
            "previous_desired": prev_desired,
            "previous_actual": "PAUSED",
            "new_desired": "RUN",
            "new_actual": status["actual_state"],
            "live": live_before,
            "arm": arm_before,
            "arm_expires_at": arm_expires_before,
            "runtime": "paused",
            "active_strategy_count": 0,
            "reason": reason.strip()[:2000],
            "correlation_id": correlation_id.strip()[:128],
            "user_broker_account_id": int(user_broker_account_id),
            "broker_code": gate.get("broker_code"),
            "user_id": gate.get("user_id"),
        }
        emit_live_safety_audit(
            self._session,
            event_type="SCHEDULER_RUN",
            actor=actor,
            run_id=correlation_id.strip()[:128],
            user_id=gate.get("user_id"),
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail=detail,
            commit=False,
        )
        status.update(
            {
                "already_running": False,
                "scheduler_changed": True,
                "previous_desired": prev_desired,
                "previous_actual": "PAUSED",
                "reason": reason.strip()[:2000],
                "correlation_id": correlation_id.strip()[:128],
                "actor": actor,
                "gate": gate,
                "live_unchanged": True,
                "arm_unchanged": True,
                "runners_started": False,
                "audit_detail": detail,
            }
        )
        return status

    def pause(
        self,
        *,
        actor: str,
        reason: str,
        correlation_id: str,
        user_broker_account_id: int | None = None,
        require_correlation_id: bool = True,
    ) -> dict[str, Any]:
        """비상 Pause — LIVE/ARM/Runner 미변경."""
        if not (reason or "").strip():
            raise TradingSchedulerControlError(
                "reason_required", "Pause reason is required"
            )
        if require_correlation_id and not (correlation_id or "").strip():
            raise TradingSchedulerControlError(
                "correlation_id_required",
                "correlation_id is required",
            )

        prev_desired = get_trading_scheduler_desired_state()
        prev_running = bool(realtime_trading_scheduler.scheduler.running)
        if not prev_running and prev_desired == "PAUSE":
            status = self.status()
            status.update(
                {
                    "already_paused": True,
                    "scheduler_changed": False,
                    "reason": reason.strip()[:2000],
                    "correlation_id": (correlation_id or "")[:128],
                    "actor": actor,
                }
            )
            return status

        set_trading_scheduler_desired_state(
            "PAUSE",
            actor=actor,
            reason=reason.strip()[:2000],
            correlation_id=(correlation_id or "")[:128] or None,
        )
        repo = RuntimeControlRepository(self._session)
        try:
            db_row = repo.update_trading_scheduler_desired(
                desired_state="PAUSE",
                actor=actor,
                reason=reason.strip()[:2000],
                correlation_id=(correlation_id or "")[:128] or None,
                last_actual_state="PAUSED",
                blocked_reason=None,
            )
            hydrate_trading_scheduler_control(
                desired_state=db_row.desired_state,
                actor=db_row.requested_by,
                reason=db_row.requested_reason,
                correlation_id=db_row.correlation_id,
                updated_at=db_row.updated_at.isoformat(),
                version=int(db_row.version),
                persisted=True,
            )
            emit_live_safety_audit(
                self._session,
                event_type="TRADING_SCHEDULER_DESIRED_STATE_CHANGED",
                actor=actor,
                run_id=(correlation_id or "")[:128] or None,
                user_id=None,
                account_id=user_broker_account_id,
                strategy_id=None,
                detail={
                    "previous_desired": prev_desired,
                    "new_desired": "PAUSE",
                    "reason": reason.strip()[:2000],
                    "correlation_id": (correlation_id or "")[:128] or None,
                    "version": int(db_row.version),
                },
                commit=False,
            )
        except RuntimeControlConflictError as exc:
            raise TradingSchedulerControlError(
                "version_conflict", str(exc)
            ) from exc
        # shutdown은 async — 동기 경로에서는 scheduler.shutdown 직접
        if realtime_trading_scheduler.scheduler.running:
            realtime_trading_scheduler.scheduler.shutdown(wait=False)
        repo.touch_heartbeat(last_actual_state="PAUSED")

        status = self.status()
        emit_live_safety_audit(
            self._session,
            event_type="SCHEDULER_PAUSE",
            actor=actor,
            run_id=(correlation_id or "")[:128] or None,
            user_id=None,
            account_id=user_broker_account_id,
            strategy_id=None,
            detail={
                "previous_desired": prev_desired,
                "previous_actual": (
                    "RUNNING" if prev_running else "PAUSED"
                ),
                "new_desired": "PAUSE",
                "new_actual": status["actual_state"],
                "reason": reason.strip()[:2000],
                "correlation_id": (correlation_id or "")[:128] or None,
            },
            commit=False,
        )
        status.update(
            {
                "already_paused": False,
                "scheduler_changed": True,
                "reason": reason.strip()[:2000],
                "correlation_id": (correlation_id or "")[:128],
                "actor": actor,
                "live_unchanged": True,
                "arm_unchanged": True,
            }
        )
        return status

    def evaluate_startup_restore_conditions(
        self,
        *,
        migration_at_head: bool,
    ) -> tuple[bool, str | None]:
        """Startup RUN 자동복원 조건.

        Fail Closed: LIVE OFF + Scheduler RUN 불변식 위반을 막기 위해
        재시작 시 RUN 자동복원을 허용하지 않는다.
        운영 순서 Resume → Pre-flight → LIVE ON → ARM ON → Scheduler RUN.
        """

        _ = migration_at_head
        return False, "OPERATOR_SEQUENCE_REQUIRED"

    def attempt_startup_restore(
        self,
        *,
        process_instance_id: str,
        migration_at_head: bool,
    ) -> dict[str, Any]:
        """Startup 시 desired=RUN이어도 자동 RUN 금지 — PAUSE로 Fail Closed."""

        repo = RuntimeControlRepository(self._session)
        row = repo.get_trading_scheduler_row(create_if_missing=True)
        assert row is not None
        desired = str(row.desired_state or "PAUSE").upper()
        prev_actual = (
            "RUNNING"
            if realtime_trading_scheduler.scheduler.running
            else "PAUSED"
        )

        emit_live_safety_audit(
            self._session,
            event_type="TRADING_SCHEDULER_STARTUP_RESTORE_ATTEMPTED",
            actor="STARTUP",
            run_id=process_instance_id,
            user_id=None,
            account_id=None,
            strategy_id=None,
            detail={
                "desired_state": desired,
                "previous_actual": prev_actual,
                "process_instance_id": process_instance_id,
            },
            commit=False,
        )

        if desired != "RUN":
            if realtime_trading_scheduler.scheduler.running:
                realtime_trading_scheduler.scheduler.shutdown(wait=False)
            repo.update_trading_scheduler_desired(
                desired_state="PAUSE",
                actor="STARTUP",
                reason="startup_no_restore_needed",
                correlation_id=process_instance_id,
                last_actual_state="PAUSED",
                startup_restore_attempted=True,
                startup_restore_result="SKIPPED_DESIRED_PAUSE",
                process_instance_id=process_instance_id,
                blocked_reason=None,
            )
            hydrate_trading_scheduler_control(
                desired_state="PAUSE",
                persisted=True,
                startup_restore_attempted=True,
                startup_restore_result="SKIPPED_DESIRED_PAUSE",
                restored_on_startup=False,
            )
            repo.touch_heartbeat(
                last_actual_state="PAUSED",
                process_instance_id=process_instance_id,
            )
            return {
                "attempted": True,
                "restored": False,
                "result": "SKIPPED_DESIRED_PAUSE",
                "blocked_reason": None,
                "actual_state": "PAUSED",
            }

        _ok, blocked = self.evaluate_startup_restore_conditions(
            migration_at_head=migration_at_head
        )
        blocked = blocked or "OPERATOR_SEQUENCE_REQUIRED"
        if realtime_trading_scheduler.scheduler.running:
            realtime_trading_scheduler.scheduler.shutdown(wait=False)
        set_trading_scheduler_desired_state(
            "PAUSE",
            actor="STARTUP",
            reason="startup_force_pause_operator_sequence",
            correlation_id=process_instance_id,
        )
        repo.update_trading_scheduler_desired(
            desired_state="PAUSE",
            actor="STARTUP",
            reason="startup_force_pause_operator_sequence",
            correlation_id=process_instance_id,
            last_actual_state="PAUSED",
            startup_restore_attempted=True,
            startup_restore_result="FORCED_PAUSE",
            process_instance_id=process_instance_id,
            blocked_reason=blocked,
        )
        hydrate_trading_scheduler_control(
            desired_state="PAUSE",
            persisted=True,
            blocked_reason=blocked,
            startup_restore_attempted=True,
            startup_restore_result="FORCED_PAUSE",
            restored_on_startup=False,
        )
        emit_live_safety_audit(
            self._session,
            event_type="TRADING_SCHEDULER_STARTUP_RESTORE_BLOCKED",
            actor="STARTUP",
            run_id=process_instance_id,
            user_id=None,
            account_id=None,
            strategy_id=None,
            detail={
                "desired_state": "PAUSE",
                "previous_desired": "RUN",
                "actual_state": "PAUSED",
                "blocked_reason": blocked,
                "process_instance_id": process_instance_id,
                "note": (
                    "Scheduler RUN not auto-restored; "
                    "require LIVE ON → ARM ON → Scheduler RUN"
                ),
            },
            commit=False,
        )
        repo.touch_heartbeat(
            last_actual_state="PAUSED",
            process_instance_id=process_instance_id,
        )
        return {
            "attempted": True,
            "restored": False,
            "result": "FORCED_PAUSE",
            "blocked_reason": blocked,
            "actual_state": "PAUSED",
        }

    def _strategy_runtime_counts(self, uba_id: int) -> dict[str, int]:
        active_runtime = 0
        active_links = 0
        try:
            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            mgr = dynamic_strategy_runtime_manager
            if hasattr(mgr, "list_active_for_uba"):
                active_runtime = len(
                    list(mgr.list_active_for_uba(uba_id) or [])  # type: ignore[attr-defined]
                )
            elif hasattr(mgr, "active_scopes"):
                scopes = list(getattr(mgr, "active_scopes")() or [])
                needle = f"uba:{uba_id}"
                active_runtime = sum(
                    1 for s in scopes if needle in str(s).lower()
                )
        except Exception:  # noqa: BLE001
            active_runtime = 0

        try:
            from stock_platform.strategy_deployment.definition_entities import (
                AccountStrategyLinkEntity,
            )

            active_links = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(AccountStrategyLinkEntity)
                    .where(
                        AccountStrategyLinkEntity.user_broker_account_id
                        == int(uba_id),
                        AccountStrategyLinkEntity.is_active.is_(True),
                    )
                )
                or 0
            )
        except Exception:  # noqa: BLE001
            # 컬럼명이 다르면 0으로 보수 처리하지 않고 전체 active link 조회 시도
            try:
                from stock_platform.strategy_deployment.definition_entities import (
                    AccountStrategyLinkEntity,
                )

                active_links = int(
                    self._session.scalar(
                        select(func.count())
                        .select_from(AccountStrategyLinkEntity)
                        .where(
                            AccountStrategyLinkEntity.is_active.is_(True)
                        )
                    )
                    or 0
                )
            except Exception:  # noqa: BLE001
                active_links = 0

        return {
            "active_runtime": active_runtime,
            "active_links": active_links,
        }
