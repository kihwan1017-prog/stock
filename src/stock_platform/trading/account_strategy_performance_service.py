"""계좌별 실거래/Paper 전략 성과 집계 (백테스트와 분리)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)
from stock_platform.trading.account_models import PaperTrade
from stock_platform.trading.models import PaperOrder
from stock_platform.trading.order_strategy_provenance import UNATTRIBUTED


ZERO = Decimal("0")


class AccountStrategyPerformanceService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def summarize_paper(
        self,
        *,
        paper_account_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        trade_stmt = select(PaperTrade).where(
            PaperTrade.account_id == int(paper_account_id)
        )
        if date_from is not None:
            trade_stmt = trade_stmt.where(PaperTrade.traded_at >= date_from)
        if date_to is not None:
            trade_stmt = trade_stmt.where(PaperTrade.traded_at <= date_to)
        trades = list(self._session.scalars(trade_stmt))

        order_stmt = select(PaperOrder).where(
            PaperOrder.account_id == int(paper_account_id)
        )
        if date_from is not None:
            order_stmt = order_stmt.where(PaperOrder.created_at >= date_from)
        if date_to is not None:
            order_stmt = order_stmt.where(PaperOrder.created_at <= date_to)
        orders = list(self._session.scalars(order_stmt))

        buckets: dict[str, dict[str, Any]] = {}

        def bucket_key(strategy_id: int | None) -> str:
            return str(strategy_id) if strategy_id is not None else UNATTRIBUTED

        for order in orders:
            key = bucket_key(getattr(order, "strategy_id", None))
            b = buckets.setdefault(key, self._empty_bucket(key, order.strategy_id))
            b["order_count"] += 1

        for trade in trades:
            sid = getattr(trade, "strategy_id", None)
            key = bucket_key(sid)
            b = buckets.setdefault(key, self._empty_bucket(key, sid))
            b["fill_count"] += 1
            qty = Decimal(str(trade.quantity or 0))
            side = str(trade.side or "").upper()
            if side == "BUY":
                b["buy_quantity"] += qty
            elif side == "SELL":
                b["sell_quantity"] += qty
            pnl = Decimal(str(trade.realized_profit_loss or 0))
            b["realized_pnl"] += pnl
            if pnl > 0:
                b["win_count"] += 1
            elif pnl < 0:
                b["loss_count"] += 1
            traded_at = trade.traded_at
            if traded_at is not None:
                prev = b.get("last_trade_at")
                if prev is None or traded_at > prev:
                    b["last_trade_at"] = traded_at

        self._enrich_strategy_names(buckets)
        return [self._finalize(b) for b in buckets.values()]

    def summarize_live(
        self,
        *,
        user_broker_account_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(TradingOrderEntity).where(
            TradingOrderEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
        if date_from is not None:
            stmt = stmt.where(TradingOrderEntity.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(TradingOrderEntity.created_at <= date_to)
        orders = list(self._session.scalars(stmt))
        buckets: dict[str, dict[str, Any]] = {}

        def bucket_key(strategy_id: int | None) -> str:
            return str(strategy_id) if strategy_id is not None else UNATTRIBUTED

        for order in orders:
            sid = getattr(order, "strategy_id", None)
            key = bucket_key(sid)
            b = buckets.setdefault(key, self._empty_bucket(key, sid))
            b["order_count"] += 1
            filled = Decimal(str(order.filled_quantity or 0))
            if filled > 0:
                b["fill_count"] += 1
                side = str(order.side_code or "").upper()
                if side == "BUY":
                    b["buy_quantity"] += filled
                elif side == "SELL":
                    b["sell_quantity"] += filled
            # LIVE 실현손익은 별도 ledger 연결 전 — filled_amount 참고만
            b["realized_pnl"] += ZERO
            created = order.created_at
            if created is not None:
                prev = b.get("last_trade_at")
                if prev is None or created > prev:
                    b["last_trade_at"] = created

        self._enrich_strategy_names(buckets)
        return [self._finalize(b) for b in buckets.values()]

    def list_paper_trades(
        self,
        *,
        paper_account_id: int,
        strategy_id: int | None,
        unattributed: bool = False,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = select(PaperTrade).where(
            PaperTrade.account_id == int(paper_account_id)
        )
        if unattributed or strategy_id is None:
            stmt = stmt.where(PaperTrade.strategy_id.is_(None))
        else:
            stmt = stmt.where(PaperTrade.strategy_id == int(strategy_id))
        if date_from is not None:
            stmt = stmt.where(PaperTrade.traded_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(PaperTrade.traded_at <= date_to)
        stmt = stmt.order_by(PaperTrade.traded_at.desc()).limit(max(1, min(limit, 500)))
        rows = list(self._session.scalars(stmt))
        return [
            {
                "trade_id": int(t.trade_id),
                "order_id": t.order_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": str(t.quantity),
                "fill_price": str(t.fill_price),
                "realized_profit_loss": str(t.realized_profit_loss),
                "strategy_id": t.strategy_id,
                "strategy_version": t.strategy_version,
                "execution_mode": t.execution_mode,
                "attribution": (
                    UNATTRIBUTED
                    if t.strategy_id is None
                    else f"strategy:{t.strategy_id}"
                ),
                "source": "PAPER_LEDGER",
                "traded_at": t.traded_at.isoformat() if t.traded_at else None,
            }
            for t in rows
        ]

    def _empty_bucket(
        self, key: str, strategy_id: int | None
    ) -> dict[str, Any]:
        return {
            "bucket_key": key,
            "strategy_id": strategy_id,
            "strategy_name": None,
            "strategy_code": None,
            "strategy_version": None,
            "order_count": 0,
            "fill_count": 0,
            "buy_quantity": ZERO,
            "sell_quantity": ZERO,
            "realized_pnl": ZERO,
            "unrealized_pnl": ZERO,
            "fee_tax": ZERO,
            "net_pnl": ZERO,
            "win_count": 0,
            "loss_count": 0,
            "last_trade_at": None,
            "source": "ACCOUNT_LEDGER_NOT_BACKTEST",
        }

    def _enrich_strategy_names(self, buckets: dict[str, dict[str, Any]]) -> None:
        ids = [
            int(b["strategy_id"])
            for b in buckets.values()
            if b.get("strategy_id") is not None
        ]
        by_id: dict[int, Any] = {}
        if ids:
            rows = list(
                self._session.scalars(
                    select(StrategyDefinitionEntity).where(
                        StrategyDefinitionEntity.strategy_id.in_(ids)
                    )
                )
            )
            by_id = {int(r.strategy_id): r for r in rows}
        for b in buckets.values():
            sid = b.get("strategy_id")
            if sid is None:
                b["strategy_name"] = "전략 미식별"
                b["strategy_code"] = UNATTRIBUTED
                continue
            row = by_id.get(int(sid))
            if row is None:
                b["strategy_name"] = f"strategy:{sid}"
                b["strategy_code"] = None
            else:
                b["strategy_name"] = row.name
                b["strategy_code"] = row.strategy_code

    def _finalize(self, bucket: dict[str, Any]) -> dict[str, Any]:
        wins = int(bucket["win_count"])
        losses = int(bucket["loss_count"])
        decided = wins + losses
        win_rate = (
            float(wins) / float(decided) if decided > 0 else None
        )
        realized = Decimal(str(bucket["realized_pnl"]))
        unrealized = Decimal(str(bucket["unrealized_pnl"]))
        fee = Decimal(str(bucket["fee_tax"]))
        net = realized + unrealized - fee
        last = bucket.get("last_trade_at")
        return {
            "strategy_id": bucket["strategy_id"],
            "strategy_name": bucket["strategy_name"],
            "strategy_code": bucket["strategy_code"],
            "strategy_version": bucket["strategy_version"],
            "attribution": (
                UNATTRIBUTED
                if bucket["strategy_id"] is None
                else f"strategy:{bucket['strategy_id']}"
            ),
            "order_count": int(bucket["order_count"]),
            "fill_count": int(bucket["fill_count"]),
            "buy_quantity": str(bucket["buy_quantity"]),
            "sell_quantity": str(bucket["sell_quantity"]),
            "realized_pnl": str(realized),
            "unrealized_pnl": str(unrealized),
            "fee_tax": str(fee),
            "net_pnl": str(net),
            "win_count": wins,
            "loss_count": losses,
            "win_rate": win_rate,
            "period_return_rate": None,
            "last_trade_at": last.isoformat() if last else None,
            "source": bucket["source"],
        }
