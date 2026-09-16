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
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.lineage import (
            build_reentry_context,
            resolve_candidate_provenance,
        )
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
            enroll_exit_on_open,
            observe_reentry,
        )
        from sqlalchemy import select
        from stock_platform.operation.upbit_full_market.constants import (
            BINDING_STATUS_CLOSED,
        )
        from stock_platform.operation.upbit_full_market.entities import (
            UpbitStrategyPositionBindingEntity,
        )
        from sqlalchemy.orm.attributes import flag_modified

        # entry provenance stamp (관측만 — ranking 미변경)
        try:
            from stock_platform.order.entities import TradingOrderEntity

            binding = session.get(UpbitStrategyPositionBindingEntity, int(binding_id))
            if binding is not None:
                meta_b = dict(binding.meta_json or {})
                entry_obs = dict(meta_b.get("entry_observation") or {})
                order_meta: dict[str, Any] = {}
                signal_id = entry_obs.get("signal_id")
                if entry_order_id is not None:
                    _ord = session.get(TradingOrderEntity, int(entry_order_id))
                    if _ord is not None:
                        order_meta = dict(getattr(_ord, "metadata_payload", None) or {})
                        signal_id = (
                            order_meta.get("signal_id")
                            or getattr(_ord, "source_signal_id", None)
                            or signal_id
                        )
                prov = resolve_candidate_provenance(
                    session,
                    selection_id=getattr(binding, "selection_id", None),
                    order_meta=order_meta,
                    binding_meta=meta_b,
                )
                entry_obs.update(
                    {
                        "entry_order_id": entry_order_id,
                        "entry_price": float(entry_price)
                        if entry_price is not None
                        else None,
                        "entry_at": entry_at.isoformat()
                        if hasattr(entry_at, "isoformat")
                        else None,
                        "entry_reason": order_meta.get("signal_reason")
                        or entry_obs.get("entry_reason")
                        or "NOT_RECORDED",
                        "signal_id": signal_id or "NOT_RECORDED",
                        **{
                            k: v
                            for k, v in prov.items()
                            if k
                            in {
                                "candidate_selection_id",
                                "scanner_rank",
                                "scanner_score",
                                "candidate_universe_size",
                                "candidate_selected_at",
                                "variant_scores",
                                "scanner_run_id",
                                "provenance_source",
                            }
                        },
                    }
                )
                meta_b["entry_observation"] = entry_obs
                binding.meta_json = meta_b
                flag_modified(binding, "meta_json")
        except Exception:  # noqa: BLE001
            pass

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

        # Lab C: prior closed Upbit binding same symbol → reentry event (shadow only)
        prior = session.scalar(
            select(UpbitStrategyPositionBindingEntity)
            .where(
                UpbitStrategyPositionBindingEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitStrategyPositionBindingEntity.symbol == str(symbol).upper(),
                UpbitStrategyPositionBindingEntity.status == BINDING_STATUS_CLOSED,
                UpbitStrategyPositionBindingEntity.binding_id != int(binding_id),
            )
            .order_by(UpbitStrategyPositionBindingEntity.closed_at.desc())
            .limit(1)
        )
        if prior is not None and prior.closed_at is not None:
            new_binding = session.get(UpbitStrategyPositionBindingEntity, int(binding_id))
            ctx = build_reentry_context(
                session,
                prior_binding=prior,
                new_binding=new_binding,
                entry_order_id=entry_order_id,
                entry_at=entry_at,
            )
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
                context=ctx,
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
            observe_ma_dc_price_for_binding,
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
        # Lab D forward tick (REAL SELL 판단 불변)
        observe_ma_dc_price_for_binding(
            session,
            binding_id=binding_id,
            price=price,
            observed_at=observed_at,
            short_ma=short_ma,
            long_ma=long_ma,
            macd=macd,
        )
    except Exception:  # noqa: BLE001
        return
