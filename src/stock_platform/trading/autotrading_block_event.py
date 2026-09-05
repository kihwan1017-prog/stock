"""Durable AUTO trading block transition history (UBA scoped)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from stock_platform.database.base import Base


class AutotradingBlockEventEntity(Base):
    """UNBLOCKED↔BLOCKED / material reason change 만 insert."""

    __tablename__ = "autotrading_block_event"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "fingerprint",
            "blocked_at",
            name="uq_autotrading_block_event_fp",
        ),
        Index(
            "ix_autotrading_block_event_uba_blocked",
            "user_broker_account_id",
            "blocked_at",
        ),
        Index(
            "ix_autotrading_block_event_uba_open",
            "user_broker_account_id",
            "resolved_at",
        ),
        {"schema": "operation"},
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    event_kind: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # BLOCKED | REASON_CHANGED | UNBLOCKED
    fingerprint: Mapped[str] = mapped_column(String(120), nullable=False)
    primary_reason_code: Mapped[str | None] = mapped_column(String(80))
    primary_reason_text: Mapped[str | None] = mapped_column(Text)
    secondary_reasons_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    source_component: Mapped[str | None] = mapped_column(String(80))
    kill_switch_scope: Mapped[str | None] = mapped_column(String(40))
    kill_switch_reason: Mapped[str | None] = mapped_column(String(200))
    related_event_id: Mapped[str | None] = mapped_column(String(80))
    related_order_id: Mapped[int | None] = mapped_column(BigInteger)
    related_activation_id: Mapped[int | None] = mapped_column(BigInteger)
    runtime_state_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    unblocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolution_type: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AutotradingBlockEventService:
    """Transition-only block provenance recorder."""

    SYSTEM_BLOCK_CODES = frozenset(
        {
            "KILL_SWITCH_ACTIVE",
            "LIVE_OFF",
            "ARM_OFF",
            "ARM_OFF_OR_EXPIRED",
            "LIVE_NOT_APPROVED",
            "ACTIVATION_INACTIVE",
            "ACCOUNT_PAUSED",
            "TRADING_PAUSED",
            "RECOVERY_CONFLICT",
            "AMBIGUOUS_ORDER",
            "EXECUTION_STACK_DOWN",
            "FILLED_EXIT_WITH_OPEN_BINDING",
        }
    )
    ENTRY_CONDITION_CODES = frozenset(
        {
            "NO_CANDIDATES",
            "NO_GOLDEN_CROSS",
            "NO_SIGNAL",
            "CANDIDATE_STALE",
        }
    )

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def fingerprint(
        *,
        primary: str | None,
        secondary: list[str],
        kill_scope: str | None,
        kill_reason: str | None,
    ) -> str:
        secs = "|".join(sorted({str(s) for s in secondary if s}))
        return (
            f"{primary or 'NONE'}::{secs}::"
            f"{kill_scope or '-'}::{(kill_reason or '-')[:60]}"
        )[:120]

    def latest_open(
        self, *, user_broker_account_id: int
    ) -> AutotradingBlockEventEntity | None:
        return self._session.scalar(
            select(AutotradingBlockEventEntity)
            .where(
                AutotradingBlockEventEntity.user_broker_account_id
                == int(user_broker_account_id),
                AutotradingBlockEventEntity.resolved_at.is_(None),
                AutotradingBlockEventEntity.event_kind.in_(
                    ("BLOCKED", "REASON_CHANGED")
                ),
            )
            .order_by(AutotradingBlockEventEntity.blocked_at.desc())
            .limit(1)
        )

    def latest_resolved(
        self, *, user_broker_account_id: int
    ) -> AutotradingBlockEventEntity | None:
        return self._session.scalar(
            select(AutotradingBlockEventEntity)
            .where(
                AutotradingBlockEventEntity.user_broker_account_id
                == int(user_broker_account_id),
                AutotradingBlockEventEntity.resolved_at.is_not(None),
            )
            .order_by(AutotradingBlockEventEntity.resolved_at.desc())
            .limit(1)
        )

    def record_from_ops_snapshot(
        self,
        *,
        user_broker_account_id: int,
        market: str,
        blockers: list[str],
        primary_blocker: str | None,
        kill: dict[str, Any] | None,
        runtime_snapshot: dict[str, Any],
        activation_id: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """SYSTEM blockers만 durable. NO_CANDIDATES 등 entry-condition 제외."""

        from datetime import timezone

        ts = now or datetime.now(timezone.utc)
        system_blockers = [
            b
            for b in blockers
            if str(b) in self.SYSTEM_BLOCK_CODES
            or str(b).startswith("KILL_")
            or str(b).endswith("_OFF")
        ]
        # quote stale alone is often consequence — keep if system already blocked
        is_blocked = bool(system_blockers) or bool(
            (kill or {}).get("active")
        )
        primary = primary_blocker
        if (kill or {}).get("active"):
            primary = "KILL_SWITCH_ACTIVE"
        secondary = [b for b in blockers if b != primary]
        kill_scope = (kill or {}).get("scope_code")
        kill_reason = (kill or {}).get("reason")
        fp = self.fingerprint(
            primary=primary if is_blocked else None,
            secondary=secondary if is_blocked else [],
            kill_scope=str(kill_scope) if kill_scope else None,
            kill_reason=str(kill_reason) if kill_reason else None,
        )
        open_row = self.latest_open(
            user_broker_account_id=user_broker_account_id
        )

        if not is_blocked:
            if open_row is None:
                return None
            open_row.unblocked_at = ts
            open_row.resolved_at = ts
            open_row.resolution_type = "AUTO_OBSERVED_CLEAR"
            self._session.flush()
            return {
                "action": "UNBLOCKED",
                "event_id": int(open_row.event_id),
            }

        from stock_platform.trading.autotrading_block_reason_labels import (
            primary_reason_text_ko,
        )

        reason_text = primary_reason_text_ko(
            primary, kill_reason=kill_reason
        )

        if open_row is None:
            evt = AutotradingBlockEventEntity(
                user_broker_account_id=int(user_broker_account_id),
                market=str(market or "UNKNOWN").upper()[:20],
                event_kind="BLOCKED",
                fingerprint=fp,
                primary_reason_code=str(primary) if primary else None,
                primary_reason_text=str(reason_text) if reason_text else None,
                secondary_reasons_json=secondary,
                source_component=str(
                    (kill or {}).get("activated_by") or "ops_status"
                )[:80],
                kill_switch_scope=str(kill_scope) if kill_scope else None,
                kill_switch_reason=str(kill_reason)[:200]
                if kill_reason
                else None,
                related_activation_id=activation_id,
                runtime_state_snapshot=runtime_snapshot,
                blocked_at=ts
                if not (kill or {}).get("activated_at")
                else _parse_ts((kill or {}).get("activated_at")) or ts,
            )
            self._session.add(evt)
            self._session.flush()
            return {"action": "BLOCKED", "event_id": int(evt.event_id)}

        if open_row.fingerprint == fp:
            return {"action": "NOOP", "event_id": int(open_row.event_id)}

        # material reason change — close prior + open new
        open_row.resolved_at = ts
        open_row.unblocked_at = ts
        open_row.resolution_type = "REASON_CHANGED"
        evt = AutotradingBlockEventEntity(
            user_broker_account_id=int(user_broker_account_id),
            market=str(market or "UNKNOWN").upper()[:20],
            event_kind="REASON_CHANGED",
            fingerprint=fp,
            primary_reason_code=str(primary) if primary else None,
            primary_reason_text=str(reason_text) if reason_text else None,
            secondary_reasons_json=secondary,
            source_component=str(
                (kill or {}).get("activated_by") or "ops_status"
            )[:80],
            kill_switch_scope=str(kill_scope) if kill_scope else None,
            kill_switch_reason=str(kill_reason)[:200] if kill_reason else None,
            related_activation_id=activation_id,
            runtime_state_snapshot=runtime_snapshot,
            blocked_at=ts,
        )
        self._session.add(evt)
        self._session.flush()
        return {
            "action": "REASON_CHANGED",
            "event_id": int(evt.event_id),
            "prior_event_id": int(open_row.event_id),
        }

    def ui_payload(
        self, *, user_broker_account_id: int
    ) -> dict[str, Any]:
        open_row = self.latest_open(
            user_broker_account_id=user_broker_account_id
        )
        resolved = self.latest_resolved(
            user_broker_account_id=user_broker_account_id
        )
        if open_row is not None:
            return {
                "status": "BLOCKED",
                "blocked_at": open_row.blocked_at.isoformat()
                if open_row.blocked_at
                else None,
                "primary_reason_code": open_row.primary_reason_code,
                "primary_reason_text": open_row.primary_reason_text,
                "secondary_reasons": open_row.secondary_reasons_json or [],
                "kill_switch_scope": open_row.kill_switch_scope,
                "kill_switch_reason": open_row.kill_switch_reason,
                "source_component": open_row.source_component,
                "event_id": int(open_row.event_id),
                "unblocked_at": None,
                "resolved_at": None,
                # 복구 lifecycle — 차단 중이면 시작=차단시각, 완료=없음
                "recovery_started_at": open_row.blocked_at.isoformat()
                if open_row.blocked_at
                else None,
                "recovered_at": None,
                "recovery_result": "PENDING",
                "recovery_method": "NOT_ATTEMPTED",
                "resolution_type": None,
            }
        if resolved is not None:
            resolution = str(resolved.resolution_type or "").upper()
            if resolution in {"AUTO_OBSERVED_CLEAR", "AUTO", "SELF_HEAL"}:
                method = "AUTO"
                result = "SUCCESS"
            elif resolution in {"MANUAL", "OPERATOR", "ADMIN"}:
                method = "MANUAL"
                result = "SUCCESS"
            elif resolution in {"REASON_CHANGED"}:
                method = "AUTO"
                result = "SUCCESS"
            elif resolution:
                method = "MIXED"
                result = "SUCCESS"
            else:
                method = "UNKNOWN"
                result = "SUCCESS"
            recovered_at = (
                resolved.resolved_at or resolved.unblocked_at
            )
            return {
                "status": "RESOLVED",
                "blocked_at": resolved.blocked_at.isoformat()
                if resolved.blocked_at
                else None,
                "unblocked_at": resolved.unblocked_at.isoformat()
                if resolved.unblocked_at
                else None,
                "resolved_at": resolved.resolved_at.isoformat()
                if resolved.resolved_at
                else None,
                "primary_reason_code": resolved.primary_reason_code,
                "primary_reason_text": resolved.primary_reason_text,
                "secondary_reasons": resolved.secondary_reasons_json or [],
                "resolution_type": resolved.resolution_type,
                "event_id": int(resolved.event_id),
                "recovery_started_at": resolved.blocked_at.isoformat()
                if resolved.blocked_at
                else None,
                "recovered_at": recovered_at.isoformat() if recovered_at else None,
                "recovery_result": result,
                "recovery_method": method,
            }
        return {
            "status": "NONE",
            "recovery_result": "NOT_ATTEMPTED",
            "recovery_method": "NOT_ATTEMPTED",
        }


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
