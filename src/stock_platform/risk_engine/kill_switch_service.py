from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.kill_switch_entities import (
    KillSwitchEntity,
    KillSwitchHistoryEntity,
)
from stock_platform.risk_engine.kill_switch_models import (
    KillSwitchState,
    KillSwitchStatus,
)


class KillSwitchService:
    GLOBAL_SCOPE = "GLOBAL"

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_state(self) -> KillSwitchState:
        entity = self._get_or_create()

        return KillSwitchState(
            status=(
                KillSwitchStatus.ACTIVE
                if entity.active
                else KillSwitchStatus.INACTIVE
            ),
            reason=entity.reason,
            activated_by=entity.activated_by,
            activated_at=entity.activated_at,
            deactivated_by=entity.deactivated_by,
            deactivated_at=entity.deactivated_at,
        )

    def activate(
        self,
        *,
        actor: str,
        reason: str,
    ) -> KillSwitchState:
        entity = self._get_or_create()
        now = datetime.now(timezone.utc)

        entity.active = True
        entity.reason = reason
        entity.activated_by = actor
        entity.activated_at = now
        entity.deactivated_by = None
        entity.deactivated_at = None

        self._session.add(
            KillSwitchHistoryEntity(
                scope_code=self.GLOBAL_SCOPE,
                action_code="ACTIVATE",
                reason=reason,
                actor=actor,
            )
        )
        self._session.commit()

        return self.get_state()

    def deactivate(
        self,
        *,
        actor: str,
        reason: str,
    ) -> KillSwitchState:
        entity = self._get_or_create()
        now = datetime.now(timezone.utc)

        entity.active = False
        entity.reason = reason
        entity.deactivated_by = actor
        entity.deactivated_at = now

        self._session.add(
            KillSwitchHistoryEntity(
                scope_code=self.GLOBAL_SCOPE,
                action_code="DEACTIVATE",
                reason=reason,
                actor=actor,
            )
        )
        self._session.commit()

        return self.get_state()

    def is_active(self) -> bool:
        return self._get_or_create().active

    def _get_or_create(self) -> KillSwitchEntity:
        entity = self._session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code
                == self.GLOBAL_SCOPE
            )
        )

        if entity is None:
            entity = KillSwitchEntity(
                scope_code=self.GLOBAL_SCOPE,
                active=False,
            )
            self._session.add(entity)
            self._session.commit()
            self._session.refresh(entity)

        return entity
