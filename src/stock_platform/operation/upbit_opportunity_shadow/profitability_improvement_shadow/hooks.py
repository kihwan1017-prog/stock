"""Fail-open hooks — REAL path never blocked by shadow errors."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session


def observe_candidate_selection(
    session: Session,
    *,
    user_broker_account_id: int,
    scanner_run_id: str,
    selection_id: int | None,
    strategy_id: int | None,
    observed_at: datetime,
    universe_rows: list[dict[str, Any]],
) -> None:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
            observe_candidate_refresh,
        )

        observe_candidate_refresh(
            session,
            user_broker_account_id=user_broker_account_id,
            scanner_run_id=scanner_run_id,
            selection_id=selection_id,
            strategy_id=strategy_id,
            observed_at=observed_at,
            universe_rows=universe_rows,
        )
    except Exception:  # noqa: BLE001
        return


def enroll_binding_on_open(
    session: Session,
    *,
    user_broker_account_id: int,
    binding_id: int,
    symbol: str,
    strategy_id: int | None,
    entry_order_id: int | None,
    entry_at: datetime,
    entry_price: Decimal,
    entry_quantity: Decimal | None = None,
    entry_fee: Decimal | None = None,
) -> None:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
            enroll_exit_on_open,
            observe_reentry,
        )
        from sqlalchemy import select
        from stock_platform.risk_engine.strategy_owned_entities import (
            BINDING_STATUS_CLOSED,
            StrategyPositionBindingEntity,
        )

        enroll_exit_on_open(
            session,
            user_broker_account_id=user_broker_account_id,
            binding_id=binding_id,
            symbol=symbol,
            strategy_id=strategy_id,
            entry_order_id=entry_order_id,
            entry_at=entry_at,
            entry_price=entry_price,
            entry_quantity=entry_quantity,
            entry_fee=entry_fee,
        )

        # Lab C: prior closed binding same symbol → reentry event (shadow only)
        prior = session.scalar(
            select(StrategyPositionBindingEntity)
            .where(
                StrategyPositionBindingEntity.user_broker_account_id
                == int(user_broker_account_id),
                StrategyPositionBindingEntity.symbol == str(symbol).upper(),
                StrategyPositionBindingEntity.status == BINDING_STATUS_CLOSED,
                StrategyPositionBindingEntity.binding_id != int(binding_id),
            )
            .order_by(StrategyPositionBindingEntity.closed_at.desc())
            .limit(1)
        )
        if prior is not None and prior.closed_at is not None:
            observe_reentry(
                session,
                user_broker_account_id=user_broker_account_id,
                symbol=symbol,
                prior_exit_at=prior.closed_at,
                reentry_at=entry_at,
                entry_order_id=entry_order_id,
                binding_id=binding_id,
                strategy_id=strategy_id,
                prior_exit_binding_id=int(prior.binding_id),
                context={
                    # entry 발생만으로 independent confirmation으로 치지 않음
                    # (C3가 C2와 항상 동일해지는 결함 방지)
                    "new_signal": False,
                    "score_improved": False,
                    "ma_improved": False,
                    "momentum_reset": False,
                    "context_source": "ENTRY_HOOK_DEFAULT_UNCONFIRMED",
                },
            )
    except Exception:  # noqa: BLE001
        return


def finalize_binding_on_close(
    session: Session,
    *,
    binding_id: int,
    exit_at: datetime,
    exit_price: Decimal | None = None,
    exit_reason: str | None = None,
    gross_pnl: Decimal | None = None,
    fees: Decimal | None = None,
    net_pnl: Decimal | None = None,
    hold_seconds: float | None = None,
) -> None:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
            finalize_exit_on_close,
            finalize_reentry_pnl,
        )

        finalize_exit_on_close(
            session,
            binding_id=binding_id,
            exit_at=exit_at,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            hold_seconds=hold_seconds,
        )
        finalize_reentry_pnl(
            session, binding_id=binding_id, net_pnl=net_pnl, fees=fees
        )
    except Exception:  # noqa: BLE001
        return


def observe_binding_price(
    session: Session,
    *,
    binding_id: int,
    price: Decimal,
    observed_at: datetime | None = None,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
    macd: float | None = None,
    ma_dead_cross: bool = False,
) -> None:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
            observe_exit_price,
        )

        observe_exit_price(
            session,
            binding_id=binding_id,
            price=price,
            observed_at=observed_at,
            short_ma=short_ma,
            long_ma=long_ma,
            macd=macd,
            ma_dead_cross=ma_dead_cross,
        )
    except Exception:  # noqa: BLE001
        return
