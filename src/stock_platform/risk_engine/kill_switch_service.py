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
        scope = (
            self.active_exchange_scope()
            if entity.active
            else set()
        )

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
            exchange_scope=tuple(sorted(scope)),
        )

    def activate(
        self,
        *,
        actor: str,
        reason: str,
        exchange_codes: list[str] | None = None,
    ) -> KillSwitchState:
        entity = self._get_or_create()
        now = datetime.now(timezone.utc)

        final_reason = self._compose_reason(
            reason,
            exchange_codes=exchange_codes,
        )

        entity.active = True
        entity.reason = final_reason
        entity.activated_by = actor
        entity.activated_at = now
        entity.deactivated_by = None
        entity.deactivated_at = None

        self._session.add(
            KillSwitchHistoryEntity(
                scope_code=self.GLOBAL_SCOPE,
                action_code="ACTIVATE",
                reason=final_reason,
                actor=actor,
            )
        )
        self._session.commit()

        # STEP 8-8 — Telegram + Audit (Scheduler pause는 API/호출측에서도 수행)
        try:
            from stock_platform.order.live_safety_audit import (
                emit_live_order_telegram,
                emit_live_safety_audit,
            )

            emit_live_safety_audit(
                self._session,
                event_type="KILL_SWITCH_ACTIVATE",
                actor=actor,
                run_id=None,
                user_id=None,
                account_id=None,
                strategy_id=None,
                detail={"reason": final_reason},
                commit=True,
            )
            emit_live_order_telegram(
                event_type="KILL_SWITCH",
                title="Kill Switch ACTIVE",
                message=f"Kill Switch activated: {final_reason}",
                detail={"reason": final_reason, "actor": actor},
            )
        except Exception:  # noqa: BLE001
            pass

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

    def is_active_for_scopes(self, scope_codes: list[str]) -> bool:
        """GLOBAL 또는 지정 scope 중 하나라도 활성이면 True."""

        codes = {
            (c or "").strip().upper()
            for c in scope_codes
            if c and str(c).strip()
        }
        codes.add(self.GLOBAL_SCOPE)
        rows = list(
            self._session.scalars(
                select(KillSwitchEntity).where(
                    KillSwitchEntity.scope_code.in_(sorted(codes)),
                    KillSwitchEntity.active.is_(True),
                )
            )
        )
        return len(rows) > 0

    def activate_scope(
        self,
        *,
        scope_code: str,
        actor: str,
        reason: str,
        exchange_codes: list[str] | None = None,
    ) -> KillSwitchState:
        """UBA/PAPER/BROKER 단위 Kill Switch 활성화 (account_number 키 금지)."""

        scope = (scope_code or "").strip().upper()
        if not scope or scope in {"MAIN", "DEFAULT", "SYSTEM_SHARED"}:
            raise ValueError(f"invalid kill switch scope: {scope_code}")
        if len(scope) > 40:
            raise ValueError("kill switch scope_code too long")

        entity = self._session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == scope
            )
        )
        now = datetime.now(timezone.utc)
        final_reason = self._compose_reason(
            reason,
            exchange_codes=exchange_codes,
        )
        if entity is None:
            entity = KillSwitchEntity(
                scope_code=scope,
                active=True,
                reason=final_reason,
                activated_by=actor,
                activated_at=now,
            )
            self._session.add(entity)
        else:
            entity.active = True
            entity.reason = final_reason
            entity.activated_by = actor
            entity.activated_at = now
            entity.deactivated_by = None
            entity.deactivated_at = None

        self._session.add(
            KillSwitchHistoryEntity(
                scope_code=scope,
                action_code="ACTIVATE",
                reason=final_reason,
                actor=actor,
            )
        )
        self._session.commit()
        return self.get_state()

    def deactivate_scope(
        self,
        *,
        scope_code: str,
        actor: str,
        reason: str,
    ) -> KillSwitchState:
        """UBA/PAPER scope Kill Switch 해제 (정정·재계산 후)."""

        scope = (scope_code or "").strip().upper()
        if not scope or scope == self.GLOBAL_SCOPE:
            raise ValueError(f"invalid kill switch scope: {scope_code}")

        entity = self._session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == scope
            )
        )
        now = datetime.now(timezone.utc)
        if entity is None:
            return self.get_state()
        entity.active = False
        entity.reason = reason
        entity.deactivated_by = actor
        entity.deactivated_at = now
        self._session.add(
            KillSwitchHistoryEntity(
                scope_code=scope,
                action_code="DEACTIVATE",
                reason=reason,
                actor=actor,
            )
        )
        self._session.commit()
        return self.get_state()

    def active_exchange_scope(self) -> set[str]:
        """
        reason에 EXCHANGES=UPBIT|KRX 형식이 있으면 해당 거래소만 차단.
        없으면 빈 set → 전역 차단.
        """

        entity = self._get_or_create()
        if not entity.active:
            return set()
        reason = entity.reason or ""
        for token in reason.replace(";", ",").split(","):
            part = token.strip()
            if part.upper().startswith("EXCHANGES="):
                raw = part.split("=", 1)[1]
                return {
                    item.strip().upper()
                    for item in raw.replace("|", ",").split(",")
                    if item.strip()
                }
        return set()

    def list_history(
        self,
        *,
        limit: int = 50,
    ) -> list[KillSwitchHistoryEntity]:
        """감사 조회용 이력 (최신순)."""

        safe_limit = max(1, min(int(limit), 200))
        stmt = (
            select(KillSwitchHistoryEntity)
            .order_by(
                KillSwitchHistoryEntity.kill_switch_history_id.desc()
            )
            .limit(safe_limit)
        )
        return list(self._session.scalars(stmt))

    @staticmethod
    def _compose_reason(
        reason: str,
        *,
        exchange_codes: list[str] | None,
    ) -> str:
        text = (reason or "").strip()
        if not exchange_codes:
            return text
        codes = sorted(
            {
                code.strip().upper()
                for code in exchange_codes
                if code and code.strip()
            }
        )
        if not codes:
            return text
        token = "EXCHANGES=" + "|".join(codes)
        if "EXCHANGES=" in text.upper():
            return text
        return f"{text}, {token}" if text else token

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
