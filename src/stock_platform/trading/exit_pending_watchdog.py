"""EXIT_PENDING open SELL telemetry — observability only (no order actions)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.trading.exit_pending_stuck import (
    _canonical_stuck_age_seconds,
    detect_exit_pending_zero_fill_stuck,
)

# observability tier thresholds (seconds) — trading action 에 사용 금지
LONG_WAIT_TIERS_SECONDS = (120, 600, 1800, 3600)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _distance_pct(order_price: Decimal | None, market_price: Decimal | None) -> float | None:
    if order_price is None or market_price is None:
        return None
    if market_price <= 0 or order_price <= 0:
        return None
    return float((order_price - market_price) / market_price * 100)


def _watchdog_state(
    *,
    age_seconds: float | None,
    stuck_threshold: int,
    ambiguous: bool,
    broker_state: str | None,
) -> str:
    if ambiguous:
        return "EXIT_PENDING_AMBIGUOUS"
    age = float(age_seconds or 0)
    if age <= 0:
        return "EXIT_PENDING_NORMAL"
    if age < stuck_threshold:
        return "EXIT_PENDING_NORMAL"
    if age >= LONG_WAIT_TIERS_SECONDS[-1]:
        return "EXIT_PENDING_LONG_WAIT"
    return "EXIT_PENDING_ZERO_FILL"


def build_exit_pending_watchdog_snapshot(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
    fetch_market_prices: bool = True,
) -> dict[str, Any]:
    """EXIT_PENDING slot + open AUTO SELL telemetry."""

    now = now or datetime.now(timezone.utc)
    stuck_threshold = _canonical_stuck_age_seconds()
    stuck = detect_exit_pending_zero_fill_stuck(
        session,
        user_broker_account_id=int(user_broker_account_id),
        now=now,
    )

    rows = session.execute(
        text(
            """
            SELECT s.slot_id, s.symbol, s.status AS slot_status,
                   o.order_id, o.status_code AS order_status,
                   o.broker_order_id, o.order_price,
                   o.filled_quantity, o.remaining_quantity,
                   o.created_at AS order_created_at,
                   o.metadata_payload
            FROM operation.upbit_position_slot s
            JOIN trading.trading_order o
              ON o.user_broker_account_id = s.user_broker_account_id
             AND o.broker_code = 'UPBIT'
             AND o.symbol = s.symbol
             AND UPPER(o.side_code) = 'SELL'
             AND UPPER(o.status_code) IN (
                   'OPEN','PENDING','SUBMITTED','ACCEPTED','PARTIAL','NEW',
                   'PARTIALLY_FILLED'
                 )
            WHERE s.user_broker_account_id = :uba
              AND s.status = 'EXIT_PENDING'
            ORDER BY o.created_at ASC
            """
        ),
        {"uba": int(user_broker_account_id)},
    ).mappings().all()

    client: Any | None = None
    items: list[dict[str, Any]] = []
    for row in rows:
        created = row["order_created_at"]
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (
            (now - created.astimezone(timezone.utc)).total_seconds()
            if created
            else None
        )
        meta = row["metadata_payload"] if isinstance(row["metadata_payload"], dict) else {}
        exit_reason = meta.get("exit_reason") or meta.get("signal_reason")
        broker_state: str | None = None
        ambiguous = False
        market_price: Decimal | None = None
        order_price = _dec(row.get("order_price"))
        uuid = str(row.get("broker_order_id") or "").strip()
        if fetch_market_prices and uuid:
            try:
                if client is None:
                    from stock_platform.broker.credential_adapter_factory import (
                        build_upbit_adapter_for_uba,
                    )

                    client = build_upbit_adapter_for_uba(
                        session, int(user_broker_account_id)
                    )._client  # noqa: SLF001
                remote = client.get_order(uuid=uuid)
                broker_state = str(remote.get("state") or "").lower()
                if not order_price:
                    order_price = _dec(remote.get("price"))
            except Exception:  # noqa: BLE001
                ambiguous = True
        if fetch_market_prices:
            try:
                from stock_platform.broker.upbit.market_snapshot import (
                    fetch_market_snapshots,
                )

                ticker, _ = fetch_market_snapshots(
                    str(row["symbol"]), use_mock=False
                )
                market_price = _dec(ticker.trade_price)
            except Exception:  # noqa: BLE001
                pass

        if broker_state in {"wait", "watch"} and not uuid:
            ambiguous = True

        wd_state = _watchdog_state(
            age_seconds=age,
            stuck_threshold=stuck_threshold,
            ambiguous=ambiguous,
            broker_state=broker_state,
        )
        filled = _dec(row.get("filled_quantity")) or Decimal("0")
        remaining = _dec(row.get("remaining_quantity"))
        items.append(
            {
                "ORDER_ID": int(row["order_id"]),
                "SYMBOL": str(row["symbol"]),
                "EXIT_REASON": exit_reason,
                "ORDER_AGE_SECONDS": round(age, 1) if age is not None else None,
                "ORDER_PRICE": str(order_price) if order_price is not None else None,
                "CURRENT_PRICE": (
                    str(market_price) if market_price is not None else None
                ),
                "PRICE_DISTANCE_PCT": _distance_pct(order_price, market_price),
                "ORDER_QTY": (
                    str(remaining + filled)
                    if remaining is not None
                    else str(row.get("remaining_quantity"))
                ),
                "FILLED_QTY": str(filled),
                "REMAINING_QTY": (
                    str(remaining) if remaining is not None else None
                ),
                "BROKER_STATE": broker_state,
                "watchdog_state": wd_state,
                "LOCAL_STATUS": str(row.get("order_status") or ""),
                "slot_id": int(row["slot_id"]),
            }
        )

    return {
        "items": items,
        "count": len(items),
        "stuck_detect": stuck,
        "stuck_threshold_seconds": stuck_threshold,
        "long_wait_tiers_seconds": list(LONG_WAIT_TIERS_SECONDS),
        "evaluated_at": now.isoformat(),
    }
