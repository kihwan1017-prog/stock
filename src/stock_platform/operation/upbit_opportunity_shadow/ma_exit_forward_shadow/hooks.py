"""Consumer / lifecycle hooks — REAL path side-effect only."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.service import (
    enroll_on_position_open,
    finalize_baseline_on_binding_close,
    observe_tick,
    shadow_enabled,
)
from stock_platform.realtime.ma_exit_policy import MaExitThresholds

logger = structlog.get_logger(__name__)


def _uba_id_from_consumer(consumer: Any) -> int | None:
    scope = getattr(consumer, "scope", None)
    if scope is None:
        return None
    broker = str(getattr(scope, "broker_code", "") or "").upper()
    if broker != "UPBIT":
        return None
    aid = getattr(scope, "account_id", None)
    try:
        return int(aid) if aid else None
    except (TypeError, ValueError):
        return None


def observe_from_evaluator(
    *,
    scope: Any,
    config: Any,
    event: Any,
    position: Any,
    signal: Any | None,
    short_ma: Any,
    long_ma: Any,
    prev_short_ma: Any,
    prev_long_ma: Any,
) -> None:
    """ma_evaluator 내부 hook — 정확한 prev/current MA 전달."""

    if not shadow_enabled():
        return
    broker = str(getattr(scope, "broker_code", "") or "").upper()
    if broker != "UPBIT":
        return
    try:
        uba_id = int(getattr(scope, "account_id", 0) or 0)
    except (TypeError, ValueError):
        return
    if uba_id <= 0 or event.price is None:
        return

    thresholds = MaExitThresholds(
        exit_min_ma_separation_pct=float(
            getattr(config, "exit_min_ma_separation_pct", 0.03) or 0.03
        ),
        ma_exit_min_holding_seconds=int(
            getattr(config, "ma_exit_min_holding_seconds", 180) or 180
        ),
        estimated_fee_rate=float(getattr(config, "estimated_fee_rate", 0.0005) or 0.0005),
    )
    real_reason = None
    if signal is not None:
        real_reason = getattr(signal, "reason", None)

    try:
        factory = get_session_factory()
        with factory() as session:
            observe_tick(
                session,
                user_broker_account_id=uba_id,
                symbol=str(event.symbol or "").upper(),
                event_time=event.event_time,
                price=event.price,
                short_ma=short_ma,
                long_ma=long_ma,
                prev_short_ma=prev_short_ma,
                prev_long_ma=prev_long_ma,
                thresholds=thresholds,
                stop_loss_ratio=config.stop_loss_ratio,
                take_profit_ratio=config.take_profit_ratio,
                trail_distance_ratio=getattr(config, "trailing_stop_ratio", None)
                or Decimal("0.03"),
                real_signal_reason=str(real_reason) if real_reason else None,
                real_signal_price=event.price if real_reason else None,
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ma_exit_forward_shadow_eval_observe_failed",
            uba_id=uba_id,
            symbol=getattr(event, "symbol", None),
            error=str(exc)[:200],
        )


def observe_consumer_tick(
    *,
    consumer: Any,
    event: Any,
    position: Any,
    signal: Any | None,
) -> None:
    """RealtimeConsumer dispatch 후 호출 — 실패해도 REAL 무영향."""

    if not shadow_enabled():
        return
    uba_id = _uba_id_from_consumer(consumer)
    if uba_id is None or event.price is None:
        return

    evaluator = getattr(consumer, "evaluator", None)
    if evaluator is None:
        return

    symbol = str(event.symbol or "").upper()
    st = evaluator.get_state(symbol)
    cfg = evaluator.config
    thresholds = MaExitThresholds(
        exit_min_ma_separation_pct=float(
            getattr(cfg, "exit_min_ma_separation_pct", 0.03) or 0.03
        ),
        ma_exit_min_holding_seconds=int(
            getattr(cfg, "ma_exit_min_holding_seconds", 180) or 180
        ),
        estimated_fee_rate=float(getattr(cfg, "estimated_fee_rate", 0.0005) or 0.0005),
    )

    qty = getattr(position, "quantity", None) or Decimal("0")
    real_reason = None
    real_px = None
    if signal is not None:
        real_reason = getattr(signal, "reason", None)
        real_px = event.price

    try:
        factory = get_session_factory()
        with factory() as session:
            observe_tick(
                session,
                user_broker_account_id=uba_id,
                symbol=symbol,
                event_time=event.event_time,
                price=event.price,
                short_ma=st.last_eval_short,
                long_ma=st.last_eval_long,
                prev_short_ma=st.last_eval_prev_short,
                prev_long_ma=st.last_eval_prev_long,
                thresholds=thresholds,
                stop_loss_ratio=cfg.stop_loss_ratio,
                take_profit_ratio=cfg.take_profit_ratio,
                trail_distance_ratio=getattr(cfg, "trailing_stop_ratio", None)
                or Decimal("0.03"),
                real_signal_reason=str(real_reason) if real_reason else None,
                real_signal_price=real_px,
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ma_exit_forward_shadow_observe_failed",
            uba_id=uba_id,
            symbol=symbol,
            error=str(exc)[:200],
        )


def enroll_binding_on_open(
    session: Any,
    *,
    user_broker_account_id: int,
    binding_id: int,
    symbol: str,
    strategy_id: int | None,
    entry_order_id: int | None,
    entry_at: Any,
    entry_price: Decimal,
    entry_quantity: Decimal | None = None,
    entry_fee: Decimal | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return enroll_on_position_open(
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
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ma_exit_forward_shadow_enroll_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def finalize_binding_on_close(
    session: Any,
    *,
    binding_id: int,
    exit_reason: str | None,
    exit_at: Any,
    exit_price: Decimal | None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return finalize_baseline_on_binding_close(
            session,
            binding_id=binding_id,
            exit_reason=exit_reason,
            exit_at=exit_at,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            fee=fee,
            net_pnl=net_pnl,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ma_exit_forward_shadow_finalize_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}
