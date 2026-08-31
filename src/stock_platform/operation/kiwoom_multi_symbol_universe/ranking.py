"""Deterministic TOP-N ranking — bulk query optimized."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_multi_symbol_universe.bulk_market_data import (
    load_bulk_completed_closes,
    load_bulk_latest_two_daily_rows,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    MIN_COMPLETED_BARS,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ma_eval import (
    evaluate_daily_ma_cross,
)
from stock_platform.realtime.daily_bar_seed import today_kst


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
    """Bulk snapshot prefilter + deterministic rank — SMA는 상위 후보만."""

    t0 = time.perf_counter()
    timing: dict[str, float] = {}
    query_count = 0

    cutoff = as_of or today_kst()
    stats = {
        "universe_count": len(universe),
        "prefilter_pass": 0,
        "insufficient_history": 0,
        "below_min_trade_value": 0,
        "no_daily_row": 0,
    }

    instrument_ids = [int(item["instrument_id"]) for item in universe]
    symbol_by_id = {int(item["instrument_id"]): str(item["symbol"]).upper() for item in universe}
    name_by_id = {int(item["instrument_id"]): item.get("name") for item in universe}

    t_load = time.perf_counter()
    latest_map = load_bulk_latest_two_daily_rows(session, instrument_ids)
    query_count += 1
    timing["bulk_latest_daily_ms"] = round((time.perf_counter() - t_load) * 1000, 2)

    liquidity_pool: list[tuple[Decimal, str, int, dict[str, Any], dict[str, Any] | None]] = []
    for iid in instrument_ids:
        symbol = symbol_by_id[iid]
        pair = latest_map.get(iid)
        if pair is None:
            stats["no_daily_row"] += 1
            continue
        latest, previous = pair
        trade_value = _to_decimal(latest.get("trade_value")) or Decimal("0")
        if trade_value < min_trade_value:
            stats["below_min_trade_value"] += 1
            continue
        liquidity_pool.append((trade_value, symbol, iid, latest, previous))

    liquidity_pool.sort(key=lambda x: (x[0], x[1]), reverse=True)

    # MA history는 거래대금 순으로 필요한 만큼만 bulk load
    ranked: list[RankedCandidate] = []
    ma_batch_size = 80
    idx = 0
    ma_query_batches = 0

    while len(ranked) < max(1, int(monitor_target)) and idx < len(liquidity_pool):
        batch = liquidity_pool[idx : idx + ma_batch_size]
        idx += ma_batch_size
        if not batch:
            break
        batch_ids = [item[2] for item in batch]
        t_ma = time.perf_counter()
        closes_map = load_bulk_completed_closes(
            session,
            batch_ids,
            required=MIN_COMPLETED_BARS,
            today=cutoff,
        )
        ma_query_batches += 1
        timing.setdefault("ma_bulk_batches", 0)
        timing["ma_bulk_batches"] = int(timing.get("ma_bulk_batches", 0)) + 1
        timing["last_ma_bulk_ms"] = round((time.perf_counter() - t_ma) * 1000, 2)

        for trade_value, symbol, iid, latest, previous in batch:
            if len(ranked) >= max(1, int(monitor_target)):
                break
            closes = list(closes_map.get(iid, []))
            today_close = _to_decimal(latest.get("close_price"))
            if today_close is not None:
                closes = closes + [today_close]

            ma = evaluate_daily_ma_cross(symbol=symbol, closes=closes)
            if ma.insufficient_history:
                stats["insufficient_history"] += 1
                continue

            stats["prefilter_pass"] += 1
            close_price = today_close
            change_pct = None
            if previous is not None and close_price is not None:
                prev_close = _to_decimal(previous.get("close_price"))
                if prev_close and prev_close > 0:
                    change_pct = (close_price - prev_close) / prev_close * Decimal("100")

            ranked.append(
                RankedCandidate(
                    symbol=symbol,
                    name=name_by_id.get(iid),
                    rank=0,
                    price=close_price,
                    volume=_to_decimal(latest.get("volume")),
                    trading_value=trade_value,
                    change_pct=change_pct,
                    selection_reason="RANK_BY_TRADING_VALUE",
                    sma5=ma.sma5,
                    sma20=ma.sma20,
                    cross_state=ma.cross_state,
                    insufficient_history=False,
                )
            )

    ranked.sort(key=lambda c: (c.trading_value or Decimal("0"), c.symbol), reverse=True)
    ranked = ranked[: max(1, int(monitor_target))]
    final: list[RankedCandidate] = []
    for ridx, cand in enumerate(ranked, start=1):
        final.append(
            RankedCandidate(
                symbol=cand.symbol,
                name=cand.name,
                rank=ridx,
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

    query_count += ma_query_batches
    timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    stats["monitor_count"] = len(final)
    stats["timing"] = timing
    stats["query_count"] = query_count
    stats["ma_history_candidates_scanned"] = idx
    return final, stats
