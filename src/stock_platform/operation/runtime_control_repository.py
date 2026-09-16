"""STEP 10-2 — Runtime Control State Repository (optimistic lock)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from stock_platform.operation.runtime_control_entities import (
    COMPONENT_TRADING_SCHEDULER,
    SCOPE_GLOBAL,
    RuntimeControlStateEntity,
)


class RuntimeControlConflictError(ValueError):
    """Optimistic lock 충돌."""

    def __init__(self, message: str = "version_conflict") -> None:
        super().__init__(message)
        self.code = "version_conflict"


class RuntimeControlRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_trading_scheduler_row(
        self,
        *,
        create_if_missing: bool = True,
    ) -> RuntimeControlStateEntity | None:
        row = self._session.scalar(
            select(RuntimeControlStateEntity).where(
                RuntimeControlStateEntity.component
                == COMPONENT_TRADING_SCHEDULER,
                RuntimeControlStateEntity.scope_type == SCOPE_GLOBAL,
                RuntimeControlStateEntity.scope_id == 0,
            )
        )
        if row is None and create_if_missing:
            now = datetime.now(timezone.utc)
            row = RuntimeControlStateEntity(
                component=COMPONENT_TRADING_SCHEDULER,
                scope_type=SCOPE_GLOBAL,
                scope_id=0,
                desired_state="PAUSE",
                last_actual_state="PAUSED",
                requested_by="system",
                requested_reason="auto_create",
                detail={},
                version=1,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
            self._session.flush()
        return row

    def update_trading_scheduler_desired(
        self,
        *,
        desired_state: str,
        actor: str | None,
        reason: str | None,
        correlation_id: str | None,
        expected_version: int | None = None,
        last_actual_state: str | None = None,
        blocked_reason: str | None = None,
        startup_restore_attempted: bool | None = None,
        startup_restore_result: str | None = None,
        process_instance_id: str | None = None,
        detail_patch: dict[str, Any] | None = None,
    ) -> RuntimeControlStateEntity:
        row = self.get_trading_scheduler_row(create_if_missing=True)
        assert row is not None
        if (
            expected_version is not None
            and int(row.version) != int(expected_version)
        ):
            raise RuntimeControlConflictError()

        now = datetime.now(timezone.utc)
        normalized = desired_state.strip().upper()
        if normalized in {"RUN", "RUNNING", "START"}:
            normalized = "RUN"
        elif normalized in {"PAUSE", "PAUSED", "STOP", "STOPPED"}:
            normalized = "PAUSE"
        else:
            raise ValueError(f"invalid desired_state: {desired_state}")

        stmt = (
            update(RuntimeControlStateEntity)
            .where(
                RuntimeControlStateEntity.control_id == row.control_id,
                RuntimeControlStateEntity.version == row.version,
            )
            .values(
                desired_state=normalized,
                requested_by=actor,
                requested_reason=reason,
                correlation_id=correlation_id,
                updated_at=now,
                version=row.version + 1,
            )
        )
        if last_actual_state is not None:
            stmt = stmt.values(last_actual_state=last_actual_state)
        if blocked_reason is not None:
            stmt = stmt.values(blocked_reason=blocked_reason)
        if startup_restore_attempted is not None:
            stmt = stmt.values(
                startup_restore_attempted=startup_restore_attempted
            )
        if startup_restore_result is not None:
            stmt = stmt.values(
                startup_restore_result=startup_restore_result
            )
        if process_instance_id is not None:
            stmt = stmt.values(process_instance_id=process_instance_id)
        if normalized == "RUN":
            stmt = stmt.values(last_started_at=now)
        elif normalized == "PAUSE":
            stmt = stmt.values(last_paused_at=now)
        if detail_patch:
            merged = {**(row.detail or {}), **detail_patch}
            stmt = stmt.values(detail=merged)

        result = self._session.execute(stmt)
        if result.rowcount != 1:
            raise RuntimeControlConflictError()

        self._session.expire(row)
        refreshed = self._session.get(
            RuntimeControlStateEntity, int(row.control_id)
        )
        assert refreshed is not None
        return refreshed

    def touch_heartbeat(
        self,
        *,
        last_actual_state: str,
        process_instance_id: str | None = None,
    ) -> None:
        row = self.get_trading_scheduler_row(create_if_missing=True)
        assert row is not None
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "last_heartbeat_at": now,
            "last_actual_state": last_actual_state,
            "updated_at": now,
        }
        if process_instance_id is not None:
            values["process_instance_id"] = process_instance_id
        self._session.execute(
            update(RuntimeControlStateEntity)
            .where(RuntimeControlStateEntity.control_id == row.control_id)
            .values(**values)
        )
