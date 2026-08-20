"""Activation 만료 → ARM OFF / LIVE OFF / Scheduler PAUSE cascade.

ARM TTL 만료(_expire_uba)와 별도로, Activation 창이 끝나면
동일 UBA의 LIVE/ARM을 fail-closed로 회수한다.
AUTO RE-ARM 없음. 타 UBA LIVE/ARM은 변경하지 않는다.

Scheduler PAUSE는 프로세스 전역(기존 ARM 만료와 동일)이며
실패해도 LIVE/ARM OFF는 롤백하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.order.live_safety_audit import (
    ACTIVATION_EXPIRED,
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.trading.account_models import UserBrokerAccount


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def activation_remaining_seconds(
    entity: LiveTradingTransitionEntity | None,
    *,
    now: datetime | None = None,
) -> int:
    """잔여 Activation TTL(초). 없거나 만료면 0."""

    if entity is None:
        return 0
    exp = aware_utc(entity.expires_at)
    if exp is None:
        return 0
    current = now or datetime.now(timezone.utc)
    return max(0, int((exp - current).total_seconds()))


def is_activation_due(
    entity: LiveTradingTransitionEntity,
    *,
    now: datetime | None = None,
) -> bool:
    """enabled 행이 만료(또는 무기한 금지)인지."""

    current = now or datetime.now(timezone.utc)
    exp = aware_utc(entity.expires_at)
    if exp is None:
        return True
    return exp <= current


def _try_scheduler_pause(
    session: Session,
    *,
    actor: str,
    uba_id: int | None,
    reason: str,
) -> bool:
    """PAUSE 실패해도 True/False만 반환 — 호출측 LIVE/ARM OFF를 막지 않음."""

    try:
        from stock_platform.trading.trading_scheduler_control_service import (
            TradingSchedulerControlService,
        )

        TradingSchedulerControlService(session).pause(
            actor=actor or "SYSTEM",
            reason=reason[:2000],
            correlation_id=f"activation-expire-pause-{int(uba_id or 0)}",
            user_broker_account_id=(
                int(uba_id) if uba_id is not None else None
            ),
            require_correlation_id=False,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _revoke_uba_live_arm(
    session: Session,
    uba: UserBrokerAccount,
    *,
    actor: str,
) -> dict[str, Any]:
    """UBA LIVE OFF + ARM 토큰/TTL 회수. Scheduler PAUSE는 별도."""

    already_off = (
        not bool(uba.live_order_enabled) and not bool(uba.live_armed)
    )
    if already_off:
        return {
            "live_off": True,
            "arm_off": True,
            "already_off": True,
        }

    from stock_platform.trading.live_arm_service import LiveArmService

    LiveArmService(session)._expire_uba(uba, actor=actor)
    return {
        "live_off": not bool(uba.live_order_enabled),
        "arm_off": not bool(uba.live_armed),
        "already_off": False,
    }


def _emit_activation_expired_audit(
    session: Session,
    *,
    actor: str,
    entity: LiveTradingTransitionEntity | None,
    uba_id: int | None,
    broker_code: str | None,
    expired_at: datetime,
    live_off: bool,
    arm_off: bool,
    scheduler_paused: bool,
    source: str,
    idempotent: bool,
) -> None:
    """원문 ARM 토큰·credential 금지."""

    activation_id = None
    if entity is not None:
        activation_id = getattr(
            entity, "live_trading_transition_id", None
        )
    detail = {
        "activation_id": activation_id,
        "user_broker_account_id": uba_id,
        "broker_code": (broker_code or "").upper() or None,
        "expired_at": expired_at.isoformat(),
        "live_off": bool(live_off),
        "arm_off": bool(arm_off),
        "scheduler_paused": bool(scheduler_paused),
        "source": source,
        "idempotent": bool(idempotent),
    }
    emit_live_safety_audit(
        session,
        event_type=ACTIVATION_EXPIRED,
        actor=actor,
        run_id=None,
        user_id=None,
        account_id=uba_id,
        strategy_id=None,
        detail=detail,
        commit=False,
    )
    emit_live_order_telegram(
        event_type=ACTIVATION_EXPIRED,
        title="LIVE ACTIVATION EXPIRED",
        message=(
            f"UBA {uba_id} Activation expired → "
            f"LIVE {'OFF' if live_off else 'ON'} "
            f"ARM {'OFF' if arm_off else 'ON'}"
            + (" + Scheduler PAUSE" if scheduler_paused else "")
        ),
        detail=detail,
    )


def expire_enabled_activation(
    session: Session,
    entity: LiveTradingTransitionEntity,
    *,
    actor: str = "SYSTEM",
    now: datetime | None = None,
) -> dict[str, Any]:
    """만료 Activation 1건 disable + 동일 UBA cascade. idempotent."""

    current = now or datetime.now(timezone.utc)
    uba_id = (
        int(entity.user_broker_account_id)
        if entity.user_broker_account_id is not None
        else None
    )
    broker = str(entity.broker_code or "").upper() or None
    was_enabled = bool(entity.enabled)

    if was_enabled:
        entity.enabled = False
        entity.activation_status = "EXPIRED"
        entity.disabled_at = current
        if not (entity.disable_reason or "").strip():
            if entity.expires_at is None:
                entity.disable_reason = (
                    "Activation missing expires_at (indefinite forbidden)"
                )
            else:
                entity.disable_reason = "Activation expired"
        session.add(entity)
        session.flush()

    live_off = True
    arm_off = True
    already_off = True
    uba = None
    if uba_id is not None:
        uba = session.get(UserBrokerAccount, uba_id)
        if uba is not None:
            revoked = _revoke_uba_live_arm(
                session, uba, actor=actor
            )
            live_off = bool(revoked["live_off"])
            arm_off = bool(revoked["arm_off"])
            already_off = bool(revoked["already_off"])

    scheduler_paused = _try_scheduler_pause(
        session,
        actor=actor,
        uba_id=uba_id,
        reason="ACTIVATION_EXPIRED:auto_pause_before_live_off",
    )
    idempotent = (not was_enabled) and already_off
    _emit_activation_expired_audit(
        session,
        actor=actor,
        entity=entity,
        uba_id=uba_id,
        broker_code=broker,
        expired_at=aware_utc(entity.expires_at) or current,
        live_off=live_off,
        arm_off=arm_off,
        scheduler_paused=scheduler_paused,
        source="DUE_ROW",
        idempotent=idempotent,
    )
    raw_tid = getattr(entity, "live_trading_transition_id", None)
    return {
        "activation_id": int(raw_tid) if raw_tid is not None else None,
        "user_broker_account_id": uba_id,
        "broker_code": broker,
        "activation_disabled": True,
        "live_off": live_off,
        "arm_off": arm_off,
        "scheduler_paused": scheduler_paused,
        "idempotent": idempotent,
    }


def expire_due_activations(
    session: Session,
    *,
    actor: str = "SYSTEM",
    now: datetime | None = None,
) -> int:
    """enabled + 만료 Activation 전건 cascade. commit 하지 않음."""

    current = now or datetime.now(timezone.utc)
    rows = list(
        session.scalars(
            select(LiveTradingTransitionEntity).where(
                LiveTradingTransitionEntity.enabled.is_(True)
            )
        )
    )
    count = 0
    for entity in rows:
        if not is_activation_due(entity, now=current):
            continue
        expire_enabled_activation(
            session, entity, actor=actor, now=current
        )
        count += 1
    return count


def revoke_stale_live_without_activation(
    session: Session,
    *,
    actor: str = "SYSTEM",
    now: datetime | None = None,
) -> int:
    """Activation이 없는데 LIVE/ARM이 남은 UBA를 회수 (restart stale)."""

    from stock_platform.broker.live_transition_service import (
        LiveTradingTransitionService,
    )

    current = now or datetime.now(timezone.utc)
    rows = list(
        session.scalars(
            select(UserBrokerAccount).where(
                or_(
                    UserBrokerAccount.live_order_enabled.is_(True),
                    UserBrokerAccount.live_armed.is_(True),
                )
            )
        )
    )
    transition = LiveTradingTransitionService(session)
    count = 0
    for uba in rows:
        active = transition.peek_active(
            broker_code=str(uba.broker_code),
            user_broker_account_id=int(uba.user_broker_account_id),
            now=current,
        )
        if active is not None:
            continue
        revoked = _revoke_uba_live_arm(session, uba, actor=actor)
        scheduler_paused = _try_scheduler_pause(
            session,
            actor=actor,
            uba_id=int(uba.user_broker_account_id),
            reason="ACTIVATION_EXPIRED:stale_live_without_activation",
        )
        _emit_activation_expired_audit(
            session,
            actor=actor,
            entity=None,
            uba_id=int(uba.user_broker_account_id),
            broker_code=str(uba.broker_code or "").upper(),
            expired_at=current,
            live_off=bool(revoked["live_off"]),
            arm_off=bool(revoked["arm_off"]),
            scheduler_paused=scheduler_paused,
            source="STALE_NO_ACTIVE",
            idempotent=bool(revoked["already_off"]),
        )
        count += 1
    return count


def scan_and_expire_live_sessions(
    session: Session,
    *,
    actor: str = "SYSTEM",
) -> dict[str, Any]:
    """주기 job 진입점: Activation due + ARM TTL due + stale LIVE.

    Unattended lease가 ACTIVE이면 ARM/Activation 만료 전 renewal을 먼저 시도한다.
    commit은 호출자가 수행한다 (테스트에서 rollback 가능).
    """

    from stock_platform.trading.live_arm_service import LiveArmService
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    unattended = LiveUnattendedAuthorizationService(
        session
    ).scan_renew_and_expire(actor=f"{actor}_UNATTENDED")
    activation_n = expire_due_activations(session, actor=actor)
    arm_n = LiveArmService(session).expire_all_due(actor=actor)
    stale_n = revoke_stale_live_without_activation(session, actor=actor)
    return {
        "unattended": unattended,
        "activation_expired": int(activation_n),
        "arm_expired": int(arm_n),
        "stale_revoked": int(stale_n),
    }
