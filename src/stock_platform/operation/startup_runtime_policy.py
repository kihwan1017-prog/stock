"""STEP 10-2 — 서버 Startup 시 운영 상태 Fail-Closed 정책."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.operation.runtime_control_repository import (
    RuntimeControlRepository,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_service import LiveArmService
from stock_platform.trading.trading_scheduler_control import (
    hydrate_trading_scheduler_control,
)


def build_process_instance_id() -> str:
    return f"pid-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _detect_shadow_startup_listen_owner(
    *, port: int = 8000
) -> dict[str, Any]:
    """이미 다른 살아있는 PID가 canonical listener면 shadow startup으로 판정.

    HealthEnsure 등이 health 일시 실패로 두 번째 process를 띄우면
    phase1 fail-closed가 공유 DB의 LIVE/ARM을 끄는 사고가 난다.
    """

    self_pid = int(os.getpid())
    owner: int | None = None
    try:
        from pathlib import Path

        listen_file = (
            Path(__file__).resolve().parents[3] / ".run" / "backend.listen.pid"
        )
        if listen_file.is_file():
            raw = listen_file.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                owner = int(raw)
    except OSError:
        owner = None

    if owner is None:
        try:
            import psutil  # type: ignore

            for conn in psutil.net_connections(kind="inet"):
                if (
                    conn.laddr
                    and int(getattr(conn.laddr, "port", 0) or 0) == int(port)
                    and str(conn.status).upper() == "LISTEN"
                    and conn.pid
                ):
                    owner = int(conn.pid)
                    break
        except Exception:  # noqa: BLE001
            owner = None

    if owner is None or int(owner) == self_pid:
        return {
            "is_shadow": False,
            "reason": "NO_OTHER_CANONICAL_LISTENER",
            "self_pid": self_pid,
            "listen_owner_pid": owner,
        }

    # listen.pid / port owner 가 다른 살아 있는 process인지 확인
    owner_alive = False
    try:
        import psutil  # type: ignore

        owner_alive = psutil.pid_exists(int(owner))
    except Exception:  # noqa: BLE001
        try:
            os.kill(int(owner), 0)
            owner_alive = True
        except OSError:
            owner_alive = False

    if not owner_alive:
        return {
            "is_shadow": False,
            "reason": "STALE_LISTEN_PID",
            "self_pid": self_pid,
            "listen_owner_pid": owner,
        }

    return {
        "is_shadow": True,
        "reason": "OTHER_LISTEN_OWNER",
        "self_pid": self_pid,
        "listen_owner_pid": owner,
    }


def migration_at_head(session: Session) -> bool:
    """Alembic head 적용 여부 (실패 시 Fail Closed)."""

    try:
        from pathlib import Path

        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[3]
        config = Config(str(root / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        if not head:
            return True
        conn = session.connection()
        context = MigrationContext.configure(conn)
        current = context.get_current_revision()
        return current == head
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "migration_head_check_failed",
            error=str(exc)[:200],
        )
        return False


class RuntimeStartupPolicy:
    """재시작 후 LIVE/ARM OFF, Runtime paused, Scheduler 조건부 복원."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = RuntimeControlRepository(session)
        self._process_id = build_process_instance_id()
        self._startup_at = datetime.now(timezone.utc).isoformat()

    async def apply_phase1(self) -> dict[str, Any]:
        """DB 로드 + LIVE/ARM 강제 OFF (broker recovery 이전)."""

        result: dict[str, Any] = {
            "phase": 1,
            "process_instance_id": self._process_id,
            "startup_at": self._startup_at,
        }
        try:
            from stock_platform.operation.runtime_process_stability import (
                build_runtime_stability_snapshot,
                classify_startup_fail_closed_cause,
            )

            stability = build_runtime_stability_snapshot()
            result["runtime_stability"] = stability
            result["restart_cause"] = classify_startup_fail_closed_cause()
            emit_live_safety_audit(
                self._session,
                event_type="PROCESS_START",
                actor="STARTUP",
                run_id=None,
                user_id=None,
                account_id=None,
                strategy_id=None,
                detail={
                    "process_instance_id": self._process_id,
                    "startup_at": self._startup_at,
                    "RUNTIME_MODE": stability.get("RUNTIME_MODE"),
                    "HOT_RELOAD_ENABLED": stability.get("HOT_RELOAD_ENABLED"),
                    "REAL_RUNTIME_STABLE": stability.get(
                        "REAL_RUNTIME_STABLE"
                    ),
                    "pid": stability.get("pid"),
                    "restart_cause": result["restart_cause"],
                },
                commit=False,
            )
        except Exception as exc:  # noqa: BLE001
            result["runtime_stability_error"] = type(exc).__name__

        result["migration_at_head"] = migration_at_head(self._session)

        # 다른 PID가 이미 listen 중이면 shadow startup — LIVE/ARM DB 강제 OFF 금지
        shadow = _detect_shadow_startup_listen_owner()
        result["shadow_startup_guard"] = shadow
        if shadow.get("is_shadow"):
            logger.warning(
                "runtime_startup_policy_phase1_shadow_abort",
                **{k: v for k, v in shadow.items() if k != "detail"},
            )
            result["live_forced_off_count"] = 0
            result["arm_forced_off_count"] = 0
            result["phase1_aborted"] = "SHADOW_STARTUP_OTHER_LISTEN_OWNER"
            result["scheduler_desired_loaded"] = None
            emit_live_safety_audit(
                self._session,
                event_type="STARTUP_SHADOW_ABORT",
                actor="STARTUP",
                run_id=None,
                user_id=None,
                account_id=None,
                strategy_id=None,
                detail={
                    "process_instance_id": self._process_id,
                    "startup_at": self._startup_at,
                    **shadow,
                },
                commit=False,
            )
            return result

        row = self._repo.get_trading_scheduler_row(create_if_missing=True)
        assert row is not None
        hydrate_trading_scheduler_control(
            desired_state=row.desired_state,
            actor=row.requested_by,
            reason=row.requested_reason,
            correlation_id=row.correlation_id,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
            version=int(row.version),
            persisted=True,
            blocked_reason=row.blocked_reason,
            startup_restore_attempted=bool(row.startup_restore_attempted),
            startup_restore_result=row.startup_restore_result,
            started_at=(
                row.last_started_at.isoformat()
                if row.last_started_at
                else None
            ),
            paused_at=(
                row.last_paused_at.isoformat()
                if row.last_paused_at
                else None
            ),
        )
        result["scheduler_desired_loaded"] = row.desired_state

        live_off = self._force_live_off()
        arm_off = self._force_arm_off()
        result["live_forced_off_count"] = live_off
        result["arm_forced_off_count"] = arm_off
        return result

    async def apply_phase2(self) -> dict[str, Any]:
        """Runtime/Strategy idle + Scheduler 조건부 복원 (bootstrap 이후)."""

        from stock_platform.trading.trading_scheduler_control_service import (
            TradingSchedulerControlService,
        )

        result: dict[str, Any] = {
            "phase": 2,
            "process_instance_id": self._process_id,
        }

        await self._force_runtime_paused()
        except_brokers: set[str] = set()
        try:
            from stock_platform.common.settings import get_settings

            if bool(
                getattr(
                    get_settings(),
                    "realtime_upbit_shadow_auto_start_enabled",
                    False,
                )
            ):
                except_brokers.add("UPBIT")
        except Exception:  # noqa: BLE001
            pass
        paused_scopes = await dynamic_strategy_runtime_manager.pause_all(
            reason="startup_forced_idle",
            except_brokers=except_brokers or None,
        )
        result["strategy_runtime_paused_count"] = paused_scopes
        result["startup_except_brokers"] = sorted(except_brokers)
        emit_live_safety_audit(
            self._session,
            event_type="STRATEGY_RUNTIME_STARTUP_FORCED_IDLE",
            actor="STARTUP",
            run_id=None,
            user_id=None,
            account_id=None,
            strategy_id=None,
            detail={
                "paused_scopes": paused_scopes,
                "process_instance_id": self._process_id,
                "startup_at": self._startup_at,
            },
            commit=False,
        )

        restore = TradingSchedulerControlService(
            self._session
        ).attempt_startup_restore(
            process_instance_id=self._process_id,
            migration_at_head=migration_at_head(self._session),
        )
        result["scheduler_restore"] = restore

        # Upbit 24/7 Shadow Runtime — Flag ON일 때만 (LIVE 실주문 아님)
        try:
            from stock_platform.realtime.integrated_runtime_lifecycle import (
                ensure_upbit_runtime_after_startup,
            )

            result["upbit_shadow_runtime"] = (
                await ensure_upbit_runtime_after_startup()
            )
        except Exception as exc:  # noqa: BLE001
            result["upbit_shadow_runtime"] = {
                "started": False,
                "error": type(exc).__name__,
            }
        return result

    def _force_live_off(self) -> int:
        rows = list(
            self._session.scalars(
                select(UserBrokerAccount).where(
                    UserBrokerAccount.live_order_enabled.is_(True)
                )
            )
        )
        count = 0
        from stock_platform.operation.runtime_process_stability import (
            classify_startup_fail_closed_cause,
        )

        restart_cause = classify_startup_fail_closed_cause()
        for uba in rows:
            before = bool(uba.live_order_enabled)
            uba.live_order_enabled = False
            uba.updated_at = datetime.now(timezone.utc)
            if before:
                count += 1
                emit_live_safety_audit(
                    self._session,
                    event_type="LIVE_STARTUP_FORCED_OFF",
                    actor="STARTUP",
                    run_id=None,
                    user_id=int(uba.user_id),
                    account_id=int(uba.user_broker_account_id),
                    strategy_id=None,
                    detail={
                        "process_instance_id": self._process_id,
                        "startup_at": self._startup_at,
                        "broker_code": str(uba.broker_code).upper(),
                        "fail_closed_reason": "fail_closed_restart",
                        "restart_cause": restart_cause,
                    },
                    commit=False,
                )
        return count

    def _force_arm_off(self) -> int:
        rows = list(
            self._session.scalars(
                select(UserBrokerAccount).where(
                    or_(
                        UserBrokerAccount.live_armed.is_(True),
                        UserBrokerAccount.arm_expires_at.is_not(None),
                    )
                )
            )
        )
        count = 0
        arm_svc = LiveArmService(self._session)
        for uba in rows:
            if not bool(uba.live_armed) and uba.arm_expires_at is None:
                continue
            expires_before = (
                uba.arm_expires_at.isoformat()
                if uba.arm_expires_at
                else None
            )
            arm_svc.disarm(
                user_broker_account_id=int(uba.user_broker_account_id),
                actor="STARTUP",
                reason="fail_closed_restart",
                correlation_id=f"startup-{self._process_id}",
                turn_live_off=False,
                require_correlation_id=False,
            )
            self._session.refresh(uba)
            expires_after = (
                uba.arm_expires_at.isoformat()
                if uba.arm_expires_at
                else None
            )
            if expires_before != expires_after and expires_after is not None:
                raise RuntimeError("ARM TTL must not refresh on startup")
            count += 1
            from stock_platform.operation.runtime_process_stability import (
                classify_startup_fail_closed_cause,
            )

            emit_live_safety_audit(
                self._session,
                event_type="ARM_STARTUP_FORCED_OFF",
                actor="STARTUP",
                run_id=None,
                user_id=int(uba.user_id),
                account_id=int(uba.user_broker_account_id),
                strategy_id=None,
                detail={
                    "process_instance_id": self._process_id,
                    "startup_at": self._startup_at,
                    "arm_expires_before": expires_before,
                    "arm_expires_after": expires_after,
                    "fail_closed_reason": "fail_closed_restart",
                    "restart_cause": classify_startup_fail_closed_cause(),
                },
                commit=False,
            )
        return count

    async def _force_runtime_paused(self) -> None:
        try:
            await realtime_execution_runner.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await realtime_strategy_runner.stop()
        except Exception:  # noqa: BLE001
            pass
        emit_live_safety_audit(
            self._session,
            event_type="RUNTIME_STARTUP_FORCED_PAUSED",
            actor="STARTUP",
            run_id=None,
            user_id=None,
            account_id=None,
            strategy_id=None,
            detail={
                "process_instance_id": self._process_id,
                "startup_at": self._startup_at,
            },
            commit=False,
        )


def count_global_submission_unknown(session: Session) -> int:
    """전역 Submission Unknown 건수."""

    try:
        from stock_platform.order.entities import TradingOrderEntity
        from stock_platform.order.models import OrderStatus

        unknown_statuses = {
            OrderStatus.AMBIGUOUS_SUBMISSION.value,
            OrderStatus.MANUAL_REVIEW_REQUIRED.value,
        }
        return int(
            session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(
                    TradingOrderEntity.status_code.in_(
                        list(unknown_statuses)
                    )
                )
            )
            or 0
        )
    except Exception:  # noqa: BLE001
        return 0
