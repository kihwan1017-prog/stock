"""Deterministic TOP-N ranking from price_daily snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    EXCHANGE_KRX,
    MIN_COMPLETED_BARS,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ma_eval import (
    evaluate_daily_ma_cross,
)
from stock_platform.realtime.daily_bar_seed import (
    load_completed_daily_closes,
    today_kst,
)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    symbol: str
    name: str | None
    rank: int
    price: Decimal | None
    volume: Decimal | None
    trading_value: Decimal | None
    change_pct: Decimal | None
    selection_reason: str
    sma5: Decimal | None
    sma20: Decimal | None
    cross_state: str
    insufficient_history: bool


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def prefilter_and_rank_candidates(
    session: Session,
    universe: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    monitor_target: int = 10,
    min_trade_value: Decimal = Decimal("100000000"),
) -> tuple[list[RankedCandidate], dict[str, int]]:
    """REST/DB snapshot 기반 prefilter + deterministic rank."""

    cutoff = as_of or today_kst()
    repo = PriceDailyRepository(session)
    scored: list[tuple[tuple, RankedCandidate]] = []
    stats = {
        "universe_count": len(universe),
        "prefilter_pass": 0,
        "insufficient_history": 0,
        "below_min_trade_value": 0,
        "no_daily_row": 0,
    }

    for item in universe:
        symbol = str(item["symbol"]).upper()
        instrument_id = int(item["instrument_id"])
        latest_rows = repo.list_recent(instrument_id, limit=1)
        if not latest_rows:
            stats["no_daily_row"] += 1
            continue
        latest = latest_rows[0]
        trade_value = _to_decimal(latest.trade_value) or Decimal("0")
        if trade_value < min_trade_value:
            stats["below_min_trade_value"] += 1
            continue

        closes_tuples = load_completed_daily_closes(
            session,
            exchange_code=EXCHANGE_KRX,
            symbol=symbol,
            required=MIN_COMPLETED_BARS,
            today=cutoff,
        )
        closes = [c for _, c in closes_tuples]
        # 당일 rolling close — latest daily row
        today_close = _to_decimal(latest.close_price)
        if today_close is not None:
            closes = closes + [today_close]

        ma = evaluate_daily_ma_cross(symbol=symbol, closes=closes)
        if ma.insufficient_history:
            stats["insufficient_history"] += 1
            continue

        stats["prefilter_pass"] += 1
        close_price = _to_decimal(latest.close_price)
        change_pct = None
        prior_rows = repo.list_recent(instrument_id, limit=2)
        if len(prior_rows) >= 2 and close_price is not None:
            prev_close = _to_decimal(prior_rows[1].close_price)
            if prev_close and prev_close > 0:
                change_pct = (close_price - prev_close) / prev_close * Decimal("100")

        candidate = RankedCandidate(
            symbol=symbol,
            name=item.get("name"),
            rank=0,
            price=close_price,
            volume=_to_decimal(latest.volume),
            trading_value=trade_value,
            change_pct=change_pct,
            selection_reason="RANK_BY_TRADING_VALUE",
            sma5=ma.sma5,
            sma20=ma.sma20,
            cross_state=ma.cross_state,
            insufficient_history=False,
        )
        sort_key = (
            trade_value,
            symbol,
        )
        scored.append((sort_key, candidate))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(1, int(monitor_target))]

    ranked: list[RankedCandidate] = []
    for idx, (_, cand) in enumerate(top, start=1):
        ranked.append(
            RankedCandidate(
                symbol=cand.symbol,
                name=cand.name,
                rank=idx,
                price=cand.price,
                volume=cand.volume,
                trading_value=cand.trading_value,
                change_pct=cand.change_pct,
                selection_reason=cand.selection_reason,
                sma5=cand.sma5,
                sma20=cand.sma20,
                cross_state=cand.cross_state,
                insufficient_history=cand.insufficient_history,
            )
        )
    stats["monitor_count"] = len(ranked)
    return ranked, stats
