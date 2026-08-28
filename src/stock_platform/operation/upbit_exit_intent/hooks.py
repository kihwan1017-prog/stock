# -*- coding: utf-8 -*-
"""Hooks: MA evaluator / order executor / lifecycle / restore."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_exit_intent.constants import (
    ATTEMPT_RETRY,
    EXIT_REASON_MA_DEAD_CROSS,
)
from stock_platform.operation.upbit_exit_intent.service import (
    UpbitExitIntentService,
    feature_enabled,
    resolve_open_binding,
)


def create_intent_on_ma_emit(
    *,
    user_broker_account_id: int,
    symbol: str,
    signal_id: str | None,
    strategy_id: int | None,
    strategy_version: str | None,
    quantity: Decimal | None,
) -> int | None:
    """Confirmed MA_DEAD_CROSS EMIT 직전 — durable intent (idempotent)."""

    if not feature_enabled():
        return None
    if not user_broker_account_id:
        return None
    session = get_session_factory()()
    try:
        binding_id, slot_id = resolve_open_binding(
            session,
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
        )
        svc = UpbitExitIntentService(session)
        row = svc.create_on_confirmed(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            exit_reason=EXIT_REASON_MA_DEAD_CROSS,
            binding_id=binding_id,
            slot_id=slot_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            signal_id=signal_id,
            quantity=quantity,
        )
        session.commit()
        return int(row.exit_intent_id) if row is not None else None
    except Exception:  # noqa: BLE001
        session.rollback()
        return None
    finally:
        session.close()


def prepare_durable_retry(
    *,
    user_broker_account_id: int,
    symbol: str,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
) -> dict[str, Any]:
    """Tick: cooldown due → state revalidate → emit_retry | wait | cleared…"""

    if not feature_enabled() or not user_broker_account_id:
        return {"action": "skip"}
    session = get_session_factory()()
    try:
        svc = UpbitExitIntentService(session)
        out = svc.prepare_retry_or_none(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            short_ma=short_ma,
            long_ma=long_ma,
        )
        session.commit()
        return out
    except Exception:  # noqa: BLE001
        session.rollback()
        return {"action": "skip", "reason": "HOOK_ERROR"}
    finally:
        session.close()


def link_order_to_intent(
    *,
    exit_intent_id: int | None,
    user_broker_account_id: int | None,
    symbol: str | None,
    order_id: int,
    signal_id: str | None = None,
    is_retry: bool = False,
) -> None:
    if not feature_enabled():
        return
    session = get_session_factory()()
    try:
        UpbitExitIntentService(session).link_order(
            exit_intent_id=exit_intent_id,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            order_id=int(order_id),
            signal_id=signal_id,
            is_retry=is_retry,
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    finally:
        session.close()


def on_exit_sell_terminal_cancel(
    *,
    order_id: int,
    user_broker_account_id: int,
    symbol: str,
    filled_quantity: Any = None,
    remaining_quantity: Any = None,
) -> None:
    if not feature_enabled():
        return
    session = get_session_factory()()
    try:
        filled = None
        rem = None
        if filled_quantity is not None:
            filled = Decimal(str(filled_quantity))
        if remaining_quantity is not None:
            rem = Decimal(str(remaining_quantity))
        UpbitExitIntentService(session).on_terminal_sell_cancel(
            order_id=int(order_id),
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            filled_quantity=filled,
            remaining_quantity=rem,
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    finally:
        session.close()


def on_exit_sell_full_fill(
    *,
    user_broker_account_id: int,
    symbol: str,
) -> None:
    if not feature_enabled():
        return
    session = get_session_factory()()
    try:
        svc = UpbitExitIntentService(session)
        row = svc.get_active(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            for_update=True,
        )
        if row is not None:
            svc.mark_completed(row, remaining_quantity=Decimal("0"))
            session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    finally:
        session.close()


def recover_intents_after_restore(
    *, user_broker_account_id: int | None = None
) -> dict[str, Any]:
    if not feature_enabled():
        return {"ok": True, "skipped": True}
    session = get_session_factory()()
    try:
        out = UpbitExitIntentService(session).recover_active_intents(
            user_broker_account_id=user_broker_account_id
        )
        session.commit()
        return out
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        session.close()


def read_active_intent_public(
    *, user_broker_account_id: int, symbol: str
) -> dict[str, Any] | None:
    session = get_session_factory()()
    try:
        svc = UpbitExitIntentService(session)
        row = svc.get_active(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
        )
        return svc.to_public(row)
    except Exception:  # noqa: BLE001
        return None
    finally:
        session.close()


def mark_intent_blocked(
    *,
    exit_intent_id: int,
    reason: str,
) -> None:
    if not feature_enabled():
        return
    session = get_session_factory()()
    try:
        svc = UpbitExitIntentService(session)
        row = svc.get_by_id(int(exit_intent_id), for_update=True)
        if row is not None:
            svc.mark_blocked(row, reason)
            session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    finally:
        session.close()


__all__ = [
    "ATTEMPT_RETRY",
    "create_intent_on_ma_emit",
    "prepare_durable_retry",
    "link_order_to_intent",
    "on_exit_sell_terminal_cancel",
    "on_exit_sell_full_fill",
    "recover_intents_after_restore",
    "read_active_intent_public",
    "mark_intent_blocked",
]
