# -*- coding: utf-8 -*-
"""Fail-open hooks — never alter trading decisions / never raise into LIVE path."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def observe_scanner_universe(
    *,
    scanner_run_id: str,
    ranked_rows: list[dict[str, Any]],
    selected_symbols: list[str] | set[str] | None = None,
    strategy_id: int | None = None,
    user_broker_account_id: int | None = None,
    observed_at: datetime | None = None,
    scanner_source: str = "UPBIT_OPPORTUNITY_SCANNER",
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_strategy_observability.service import (
            persist_scanner_universe,
        )

        return persist_scanner_universe(
            scanner_run_id=str(scanner_run_id),
            observed_at=observed_at,
            strategy_id=strategy_id,
            user_broker_account_id=user_broker_account_id,
            rows=list(ranked_rows or []),
            selected_symbols=set(selected_symbols or set()),
            scanner_source=scanner_source,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"hook": "scanner_universe", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED"}


def observe_admission(
    *,
    admission: Any,
    symbol: str,
    user_broker_account_id: int | None,
    strategy_id: int | None,
    signal_id: str | None = None,
    selection_id: int | None = None,
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_strategy_observability.constants import (
            EVENT_ADMISSION,
        )
        from stock_platform.operation.upbit_strategy_observability.service import (
            build_admission_payload,
            persist_event,
        )

        ad = admission.to_dict() if hasattr(admission, "to_dict") else dict(admission or {})
        return persist_event(
            event_type=EVENT_ADMISSION,
            payload=build_admission_payload(ad),
            user_broker_account_id=user_broker_account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            signal_id=signal_id,
            selection_id=selection_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"hook": "admission", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED"}


def observe_signal_event(
    *,
    side: str,
    signal_id: str | None,
    symbol: str,
    strategy_id: int | None,
    user_broker_account_id: int | None,
    price: Any,
    short_ma: Any,
    long_ma: Any,
    reason: str | None = None,
    selection_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_strategy_observability.constants import (
            EVENT_EXIT,
            EVENT_SIGNAL_BUY,
            EVENT_SIGNAL_SELL,
        )
        from stock_platform.operation.upbit_strategy_observability.service import (
            build_signal_payload,
            persist_event,
        )

        side_u = str(side).upper()
        if side_u == "BUY":
            event_type = EVENT_SIGNAL_BUY
        elif reason and "DEAD_CROSS" in str(reason).upper():
            event_type = EVENT_EXIT
        else:
            event_type = EVENT_SIGNAL_SELL
        payload = build_signal_payload(
            signal_type=side_u,
            price=price,
            short_ma=short_ma,
            long_ma=long_ma,
            extra={
                "reason": reason,
                "selection_id": selection_id,
                **(extra or {}),
            },
        )
        return persist_event(
            event_type=event_type,
            payload=payload,
            user_broker_account_id=user_broker_account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            signal_id=signal_id,
            selection_id=selection_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"hook": "signal", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED"}


def observe_exit_event(
    *,
    symbol: str,
    strategy_id: int | None,
    user_broker_account_id: int | None,
    exit_reason: str,
    price: Any,
    short_ma: Any,
    long_ma: Any,
    holding_seconds: int | None = None,
    entry_price: Any = None,
    signal_id: str | None = None,
    binding_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_strategy_observability.constants import (
            EVENT_EXIT,
        )
        from stock_platform.operation.upbit_strategy_observability.service import (
            build_signal_payload,
            persist_event,
        )

        payload = build_signal_payload(
            signal_type="SELL",
            price=price,
            short_ma=short_ma,
            long_ma=long_ma,
            extra={
                "exit_reason": exit_reason,
                "holding_seconds": holding_seconds,
                "position_entry_price": str(entry_price) if entry_price is not None else None,
                # MFE/MAE at exit signal are optional live estimates — not post-exit look-ahead
                **(extra or {}),
            },
        )
        return persist_event(
            event_type=EVENT_EXIT,
            payload=payload,
            user_broker_account_id=user_broker_account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            signal_id=signal_id,
            binding_id=binding_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"hook": "exit", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED"}


def observe_order_timeline_stamp(
    *,
    user_broker_account_id: int,
    symbol: str,
    side_code: str,
    order_id: int,
    strategy_id: int | None = None,
    binding_id: int | None = None,
    signal_id: str | None = None,
    selection_id: int | None = None,
    stamps: dict[str, datetime | None] | None = None,
    note: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_strategy_observability.service import (
            upsert_order_timeline,
        )

        return upsert_order_timeline(
            user_broker_account_id=int(user_broker_account_id),
            symbol=symbol,
            side_code=side_code,
            order_id=int(order_id),
            strategy_id=strategy_id,
            binding_id=binding_id,
            signal_id=signal_id,
            selection_id=selection_id,
            stamps=stamps,
            note=note,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"hook": "timeline", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED"}


def observe_mark_selected_symbols(
    *,
    scanner_run_id: str,
    selected_symbols: list[str],
    user_broker_account_id: int | None = None,
    strategy_id: int | None = None,
    universe_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-upsert universe with selected flags after portfolio assign."""

    try:
        if not universe_rows:
            return {"ok": True, "note": "NO_ROWS"}
        return observe_scanner_universe(
            scanner_run_id=scanner_run_id,
            ranked_rows=universe_rows,
            selected_symbols=selected_symbols,
            strategy_id=strategy_id,
            user_broker_account_id=user_broker_account_id,
            scanner_source="UPBIT_PORTFOLIO_ASSIGN",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"hook": "mark_selected", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED"}
