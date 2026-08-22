"""AUTO trading performance aggregate — strategy_position_binding SoT (Read-only)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import BrokerPositionSnapshotEntity
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    OWNERSHIP_STRATEGY,
    StrategyPositionBindingEntity,
)
from stock_platform.trading.ops_account_classification import (
    DEFAULT_PROTECTED_UBA_IDS,
)

ZERO = Decimal("0")
QUANT = Decimal("0.01")
_PCT_QUANT = Decimal("0.0001")
_KST = ZoneInfo("Asia/Seoul")

BrokerFilter = Literal["ALL", "UPBIT", "KIWOOM"]
PeriodFilter = Literal["TODAY", "7D", "30D", "ALL"]

RETURN_FORMULA_NOTE = (
    "거래 수익률 = (실현손익 - 수수료) / 진입원가 × 100. "
    "누적 수익률 = 기간 내 순실현손익 합 / 기간 내 진입원가 합 × 100 "
    "(단순 자본가중, 복리 아님)."
)


def classify_exit_reason(raw: str | None) -> str:
    """청산 유형 canonical 분류 — MANUAL exit는 AUTO binding에 없음."""

    u = str(raw or "").upper()
    if not u:
        return "OTHER_AUTO"
    if "TRAIL" in u:
        return "TRAILING_STOP"
    if "STOP" in u:
        return "STOP_LOSS"
    if "TAKE" in u or "PROFIT" in u:
        return "TAKE_PROFIT"
    if (
        "DEAD_CROSS" in u
        or "MA_DEAD" in u
        or "SIGNAL" in u
        or "STRATEGY" in u
    ):
        return "STRATEGY_SIGNAL"
    return "OTHER_AUTO"


def exit_reason_label_ko(category: str) -> str:
    labels = {
        "TAKE_PROFIT": "익절",
        "STOP_LOSS": "손절",
        "TRAILING_STOP": "트레일링 스탑",
        "STRATEGY_SIGNAL": "전략 신호",
        "OTHER_AUTO": "기타(AUTO)",
    }
    return labels.get(category, category)


def _closed_quantity(binding: StrategyPositionBindingEntity) -> Decimal:
    """CLOSED binding — owned_quantity=0이므로 meta/가격으로 역산."""

    meta = dict(binding.meta_json or {})
    cached = meta.get("closed_quantity")
    if cached is not None:
        qty = Decimal(str(cached))
        if qty > ZERO:
            return qty

    entry = Decimal(str(binding.entry_price or 0))
    gross = Decimal(str(binding.realized_pnl or 0))
    exit_px = Decimal(str(meta.get("exit_fill_price") or 0))
    if entry > ZERO and exit_px > ZERO and gross != ZERO:
        diff = exit_px - entry
        if diff != ZERO:
            return (gross / diff).quantize(Decimal("0.00000001"))
    return ZERO


def binding_closed_trade_metrics(
    binding: StrategyPositionBindingEntity,
    *,
    exit_order: TradingOrderEntity | None = None,
) -> dict[str, Any]:
    """Canonical: gross=realized_pnl, net=gross-fees, return=net/entry_cost."""

    entry = Decimal(str(binding.entry_price or 0))
    gross = Decimal(str(binding.realized_pnl or 0))
    fees = Decimal(str(binding.fees or 0))
    net = (gross - fees).quantize(QUANT)
    qty = _closed_quantity(binding)
    entry_cost = (entry * qty).quantize(QUANT) if entry > ZERO and qty > ZERO else ZERO
    return_pct = (
        (net / entry_cost * Decimal("100")).quantize(_PCT_QUANT)
        if entry_cost > ZERO
        else ZERO
    )

    exit_reason_raw = ""
    if exit_order is not None:
        meta = dict(getattr(exit_order, "metadata_payload", None) or {})
        exit_reason_raw = str(
            meta.get("exit_reason") or meta.get("signal_reason") or ""
        )
    exit_category = classify_exit_reason(exit_reason_raw)

    opened = binding.opened_at
    closed = binding.closed_at
    duration_sec: int | None = None
    if opened and closed:
        duration_sec = int((closed - opened).total_seconds())

    meta = dict(binding.meta_json or {})
    exit_px = meta.get("exit_fill_price")

    return {
        "binding_id": int(binding.binding_id),
        "user_broker_account_id": int(binding.user_broker_account_id),
        "broker_code": str(binding.broker_code).upper(),
        "strategy_id": int(binding.strategy_id),
        "symbol": str(binding.symbol),
        "entry_price": str(entry),
        "exit_price": str(exit_px) if exit_px is not None else None,
        "quantity": str(qty),
        "entry_cost": str(entry_cost),
        "gross_pnl": str(gross.quantize(QUANT)),
        "fees": str(fees.quantize(QUANT)),
        "net_pnl": str(net),
        "return_pct": str(return_pct),
        "exit_reason_raw": exit_reason_raw or None,
        "exit_reason_category": exit_category,
        "exit_reason_label_ko": exit_reason_label_ko(exit_category),
        "opened_at": opened.isoformat() if opened else None,
        "closed_at": closed.isoformat() if closed else None,
        "duration_sec": duration_sec,
        "entry_order_id": binding.entry_order_id,
        "exit_order_id": meta.get("exit_order_id"),
    }


def binding_open_position_metrics(
    binding: StrategyPositionBindingEntity,
    *,
    mark_price: Decimal | None = None,
) -> dict[str, Any]:
    """OPEN AUTO binding 평가손익."""

    entry = Decimal(str(binding.entry_price or 0))
    qty = Decimal(str(binding.owned_quantity or 0))
    fees = Decimal(str(binding.fees or 0))
    entry_cost = (entry * qty).quantize(QUANT) if entry > ZERO and qty > ZERO else ZERO
    mark = Decimal(str(mark_price or 0))
    gross_unreal = ZERO
    if qty > ZERO and entry > ZERO and mark > ZERO:
        gross_unreal = ((mark - entry) * qty).quantize(QUANT)
    net_unreal = (gross_unreal - fees).quantize(QUANT)
    return_pct = (
        (net_unreal / entry_cost * Decimal("100")).quantize(_PCT_QUANT)
        if entry_cost > ZERO
        else ZERO
    )
    meta = dict(binding.meta_json or {})
    return {
        "binding_id": int(binding.binding_id),
        "user_broker_account_id": int(binding.user_broker_account_id),
        "broker_code": str(binding.broker_code).upper(),
        "strategy_id": int(binding.strategy_id),
        "symbol": str(binding.symbol),
        "entry_price": str(entry),
        "current_price": str(mark) if mark > ZERO else None,
        "quantity": str(qty),
        "entry_cost": str(entry_cost),
        "unrealized_pnl": str(net_unreal),
        "unrealized_return_pct": str(return_pct),
        "fees": str(fees.quantize(QUANT)),
        "opened_at": binding.opened_at.isoformat() if binding.opened_at else None,
        "stop_loss": meta.get("stop_loss"),
        "take_profit": meta.get("take_profit"),
        "trailing_stop": meta.get("trailing_stop"),
    }


def _period_start(period: PeriodFilter, *, today: date) -> datetime | None:
    if period == "ALL":
        return None
    day_start = datetime(today.year, today.month, today.day, tzinfo=_KST)
    if period == "TODAY":
        return day_start.astimezone(timezone.utc)
    days = 7 if period == "7D" else 30
    return (day_start - timedelta(days=days - 1)).astimezone(timezone.utc)


def _kst_trading_date(ts: datetime | None) -> date | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_KST).date()


@dataclass
class AutotradingPerformanceService:
    session: Session

    def build(
        self,
        *,
        broker: BrokerFilter = "ALL",
        period: PeriodFilter = "30D",
        uba_ids: frozenset[int] | None = None,
    ) -> dict[str, Any]:
        scope_ubas = uba_ids or DEFAULT_PROTECTED_UBA_IDS
        today = datetime.now(_KST).date()
        period_start = _period_start(period, today=today)
        today_start = datetime(today.year, today.month, today.day, tzinfo=_KST).astimezone(
            timezone.utc
        )

        brokers: list[str] = []
        if broker == "ALL":
            brokers = ["UPBIT", "KIWOOM"]
        else:
            brokers = [broker]

        base_filters = [
            StrategyPositionBindingEntity.user_broker_account_id.in_(scope_ubas),
            StrategyPositionBindingEntity.broker_code.in_(brokers),
            StrategyPositionBindingEntity.ownership_code == OWNERSHIP_STRATEGY,
        ]

        closed_rows = list(
            self.session.scalars(
                select(StrategyPositionBindingEntity)
                .where(
                    *base_filters,
                    StrategyPositionBindingEntity.status == BINDING_STATUS_CLOSED,
                )
                .order_by(StrategyPositionBindingEntity.closed_at.desc())
            )
        )
        open_rows = list(
            self.session.scalars(
                select(StrategyPositionBindingEntity).where(
                    *base_filters,
                    StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
                )
            )
        )

        exit_ids: set[int] = set()
        for b in closed_rows:
            meta = dict(b.meta_json or {})
            eid = meta.get("exit_order_id")
            if eid is not None:
                try:
                    exit_ids.add(int(eid))
                except (TypeError, ValueError):
                    pass

        exit_orders: dict[int, TradingOrderEntity] = {}
        if exit_ids:
            for order in self.session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.order_id.in_(exit_ids)
                )
            ):
                exit_orders[int(order.order_id)] = order

        mark_prices = self._load_mark_prices(scope_ubas)

        closed_trades: list[dict[str, Any]] = []
        for b in closed_rows:
            meta = dict(b.meta_json or {})
            eid = meta.get("exit_order_id")
            exit_order = None
            if eid is not None:
                try:
                    exit_order = exit_orders.get(int(eid))
                except (TypeError, ValueError):
                    pass
            closed_trades.append(
                binding_closed_trade_metrics(b, exit_order=exit_order)
            )

        period_closed = closed_trades
        if period_start is not None:
            period_closed = [
                t
                for t in closed_trades
                if t.get("closed_at")
                and datetime.fromisoformat(str(t["closed_at"])) >= period_start
            ]

        open_positions = [
            binding_open_position_metrics(
                b,
                mark_price=mark_prices.get(
                    (int(b.user_broker_account_id), str(b.symbol).upper())
                ),
            )
            for b in open_rows
        ]

        summary = self._build_summary(
            period_closed=period_closed,
            all_closed=closed_trades,
            open_positions=open_positions,
            today_start=today_start,
            broker=broker,
            period=period,
        )
        daily_returns = self._build_daily_returns(period_closed)
        cumulative_returns = self._build_cumulative_returns(daily_returns)
        symbol_performance = self._build_symbol_performance(period_closed)
        exit_reason_performance = self._build_exit_reason_performance(period_closed)
        win_loss = self._build_win_loss(period_closed)
        return_distribution = self._build_return_distribution(period_closed)
        broker_comparison = self._build_broker_comparison(period_closed, closed_trades)
        recent_closed = period_closed[:10]

        closed_count = len(period_closed)
        low_sample = closed_count < 5

        return {
            "broker": broker,
            "period": period,
            "return_formula_note": RETURN_FORMULA_NOTE,
            "inclusion_rule": (
                "operation.strategy_position_binding 중 "
                "ownership_code=STRATEGY_OWNED(AUTO) REAL UBA만 집계"
            ),
            "exclusion_rule": (
                "MANUAL/UNKNOWN/PAPER/TEST/MOCK/Shadow 제외. "
                "계좌 전체 평가손익과 분리."
            ),
            "summary": summary,
            "daily_returns": daily_returns,
            "cumulative_returns": cumulative_returns,
            "symbol_performance": symbol_performance,
            "exit_reason_performance": exit_reason_performance,
            "win_loss": win_loss,
            "return_distribution": return_distribution,
            "broker_comparison": broker_comparison,
            "recent_closed_trades": recent_closed,
            "open_positions": open_positions,
            "closed_trade_count": closed_count,
            "low_sample_warning": low_sample,
            "low_sample_message": (
                f"현재 완료된 자동매매 거래가 {closed_count}건입니다. "
                "거래 데이터가 더 쌓인 후 승률과 평균수익률을 판단하는 것이 좋습니다."
                if low_sample
                else None
            ),
        }

    def _load_mark_prices(
        self, uba_ids: frozenset[int]
    ) -> dict[tuple[int, str], Decimal]:
        prices: dict[tuple[int, str], Decimal] = {}
        rows = list(
            self.session.scalars(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id.in_(
                        uba_ids
                    ),
                    BrokerPositionSnapshotEntity.snapshot_status == "ACTIVE",
                )
            )
        )
        for p in rows:
            sym = str(p.symbol).upper()
            px = Decimal(str(p.current_price or 0))
            if px > ZERO:
                prices[(int(p.user_broker_account_id), sym)] = px
        return prices

    def _build_summary(
        self,
        *,
        period_closed: list[dict[str, Any]],
        all_closed: list[dict[str, Any]],
        open_positions: list[dict[str, Any]],
        today_start: datetime,
        broker: str,
        period: str,
    ) -> dict[str, Any]:
        def _sum_net(rows: list[dict[str, Any]]) -> Decimal:
            return sum(
                (Decimal(str(r["net_pnl"])) for r in rows),
                ZERO,
            ).quantize(QUANT)

        def _sum_entry_cost(rows: list[dict[str, Any]]) -> Decimal:
            return sum(
                (Decimal(str(r["entry_cost"])) for r in rows),
                ZERO,
            ).quantize(QUANT)

        def _return_pct(net: Decimal, cost: Decimal) -> str | None:
            if cost <= ZERO:
                return None
            return str((net / cost * Decimal("100")).quantize(_PCT_QUANT))

        today_closed = [
            t
            for t in all_closed
            if t.get("closed_at")
            and datetime.fromisoformat(str(t["closed_at"])) >= today_start
        ]
        today_net = _sum_net(today_closed)
        today_cost = _sum_entry_cost(today_closed)

        period_net = _sum_net(period_closed)
        period_cost = _sum_entry_cost(period_closed)
        all_net = _sum_net(all_closed)
        all_cost = _sum_entry_cost(all_closed)

        unrealized = sum(
            (Decimal(str(p["unrealized_pnl"])) for p in open_positions),
            ZERO,
        ).quantize(QUANT)

        wins = sum(1 for t in period_closed if Decimal(str(t["net_pnl"])) > ZERO)
        losses = sum(1 for t in period_closed if Decimal(str(t["net_pnl"])) < ZERO)
        flats = sum(1 for t in period_closed if Decimal(str(t["net_pnl"])) == ZERO)
        closed_n = len(period_closed)
        win_rate = (
            str((Decimal(wins) / Decimal(closed_n) * Decimal("100")).quantize(_PCT_QUANT))
            if closed_n > 0
            else None
        )

        avg_return: str | None = None
        if closed_n > 0:
            rets = [Decimal(str(t["return_pct"])) for t in period_closed]
            avg_return = str(
                (sum(rets, ZERO) / Decimal(closed_n)).quantize(_PCT_QUANT)
            )

        return {
            "broker": broker,
            "period": period,
            "today_realized_pnl": str(today_net),
            "today_return_pct": _return_pct(today_net, today_cost),
            "period_realized_pnl": str(period_net),
            "period_return_pct": _return_pct(period_net, period_cost),
            "cumulative_realized_pnl": str(all_net),
            "cumulative_return_pct": _return_pct(all_net, all_cost),
            "current_unrealized_pnl": str(unrealized),
            "win_rate_pct": win_rate,
            "closed_trade_count": closed_n,
            "open_position_count": len(open_positions),
            "avg_trade_return_pct": avg_return,
            "wins": wins,
            "losses": losses,
            "flats": flats,
        }

    def _build_daily_returns(
        self, period_closed: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for t in period_closed:
            closed_at = t.get("closed_at")
            if not closed_at:
                continue
            day = _kst_trading_date(datetime.fromisoformat(str(closed_at)))
            if day:
                by_day[day].append(t)

        rows: list[dict[str, Any]] = []
        for day in sorted(by_day.keys()):
            trades = by_day[day]
            net = sum((Decimal(str(x["net_pnl"])) for x in trades), ZERO)
            cost = sum((Decimal(str(x["entry_cost"])) for x in trades), ZERO)
            wins = sum(1 for x in trades if Decimal(str(x["net_pnl"])) > ZERO)
            losses = sum(1 for x in trades if Decimal(str(x["net_pnl"])) < ZERO)
            daily_pct = (
                (net / cost * Decimal("100")).quantize(_PCT_QUANT)
                if cost > ZERO
                else ZERO
            )
            rows.append(
                {
                    "trading_date": day.isoformat(),
                    "daily_return_pct": str(daily_pct),
                    "realized_pnl": str(net.quantize(QUANT)),
                    "entry_cost": str(cost.quantize(QUANT)),
                    "trade_count": len(trades),
                    "wins": wins,
                    "losses": losses,
                }
            )
        return rows

    def _build_cumulative_returns(
        self, daily_returns: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cum_net = ZERO
        cum_cost = ZERO
        rows: list[dict[str, Any]] = []
        for d in daily_returns:
            cum_net += Decimal(str(d["realized_pnl"]))
            cum_cost += Decimal(str(d.get("entry_cost") or 0))
            cum_pct = (
                (cum_net / cum_cost * Decimal("100")).quantize(_PCT_QUANT)
                if cum_cost > ZERO
                else ZERO
            )
            rows.append(
                {
                    "trading_date": d["trading_date"],
                    "cumulative_return_pct": str(cum_pct),
                    "cumulative_realized_pnl": str(cum_net.quantize(QUANT)),
                }
            )
        return rows

    def _build_symbol_performance(
        self, period_closed: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in period_closed:
            by_sym[str(t["symbol"])].append(t)

        rows: list[dict[str, Any]] = []
        for sym, trades in by_sym.items():
            net = sum((Decimal(str(x["net_pnl"])) for x in trades), ZERO)
            cost = sum((Decimal(str(x["entry_cost"])) for x in trades), ZERO)
            wins = sum(1 for x in trades if Decimal(str(x["net_pnl"])) > ZERO)
            n = len(trades)
            rows.append(
                {
                    "symbol": sym,
                    "realized_pnl": str(net.quantize(QUANT)),
                    "return_pct": str(
                        (net / cost * Decimal("100")).quantize(_PCT_QUANT)
                        if cost > ZERO
                        else ZERO
                    ),
                    "trade_count": n,
                    "win_rate_pct": str(
                        (Decimal(wins) / Decimal(n) * Decimal("100")).quantize(
                            _PCT_QUANT
                        )
                        if n > 0
                        else ZERO
                    ),
                }
            )
        rows.sort(key=lambda r: Decimal(str(r["realized_pnl"])), reverse=True)
        return rows[:10]

    def _build_exit_reason_performance(
        self, period_closed: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in period_closed:
            by_reason[str(t["exit_reason_category"])].append(t)

        rows: list[dict[str, Any]] = []
        for cat, trades in sorted(by_reason.items()):
            net = sum((Decimal(str(x["net_pnl"])) for x in trades), ZERO)
            wins = sum(1 for x in trades if Decimal(str(x["net_pnl"])) > ZERO)
            losses = sum(1 for x in trades if Decimal(str(x["net_pnl"])) < ZERO)
            rets = [Decimal(str(x["return_pct"])) for x in trades]
            avg_ret = (
                (sum(rets, ZERO) / Decimal(len(rets))).quantize(_PCT_QUANT)
                if rets
                else ZERO
            )
            rows.append(
                {
                    "exit_reason_category": cat,
                    "exit_reason_label_ko": exit_reason_label_ko(cat),
                    "trade_count": len(trades),
                    "win_count": wins,
                    "loss_count": losses,
                    "avg_return_pct": str(avg_ret),
                    "total_realized_pnl": str(net.quantize(QUANT)),
                }
            )
        return rows

    def _build_win_loss(
        self, period_closed: list[dict[str, Any]]
    ) -> dict[str, Any]:
        wins = sum(1 for t in period_closed if Decimal(str(t["net_pnl"])) > ZERO)
        losses = sum(1 for t in period_closed if Decimal(str(t["net_pnl"])) < ZERO)
        flats = sum(1 for t in period_closed if Decimal(str(t["net_pnl"])) == ZERO)
        n = len(period_closed)
        return {
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "total": n,
            "win_rate_pct": str(
                (Decimal(wins) / Decimal(n) * Decimal("100")).quantize(_PCT_QUANT)
                if n > 0
                else None
            ),
        }

    def _build_return_distribution(
        self, period_closed: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        buckets = [
            ("<= -5%", lambda p: p <= Decimal("-5")),
            ("-5~-3%", lambda p: Decimal("-5") < p <= Decimal("-3")),
            ("-3~-1%", lambda p: Decimal("-3") < p <= Decimal("-1")),
            ("-1~0%", lambda p: Decimal("-1") < p < ZERO),
            ("0~1%", lambda p: ZERO <= p < Decimal("1")),
            ("1~3%", lambda p: Decimal("1") <= p < Decimal("3")),
            ("3~5%", lambda p: Decimal("3") <= p < Decimal("5")),
            (">= 5%", lambda p: p >= Decimal("5")),
        ]
        rows: list[dict[str, Any]] = []
        for label, pred in buckets:
            count = sum(
                1
                for t in period_closed
                if pred(Decimal(str(t["return_pct"])))
            )
            rows.append({"bucket": label, "count": count})
        return rows

    def _build_broker_comparison(
        self,
        period_closed: list[dict[str, Any]],
        all_closed: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in ("UPBIT", "KIWOOM"):
            period_trades = [
                t for t in period_closed if t["broker_code"] == code
            ]
            all_trades = [t for t in all_closed if t["broker_code"] == code]
            if not all_trades:
                rows.append(
                    {
                        "broker_code": code,
                        "has_trades": False,
                        "realized_pnl": None,
                        "return_pct": None,
                        "win_rate_pct": None,
                        "trade_count": 0,
                        "label": "거래 없음",
                    }
                )
                continue
            net = sum(
                (Decimal(str(x["net_pnl"])) for x in period_trades), ZERO
            )
            cost = sum(
                (Decimal(str(x["entry_cost"])) for x in period_trades), ZERO
            )
            wins = sum(
                1 for x in period_trades if Decimal(str(x["net_pnl"])) > ZERO
            )
            n = len(period_trades)
            rows.append(
                {
                    "broker_code": code,
                    "has_trades": True,
                    "realized_pnl": str(net.quantize(QUANT)),
                    "return_pct": str(
                        (net / cost * Decimal("100")).quantize(_PCT_QUANT)
                        if cost > ZERO
                        else ZERO
                    ),
                    "win_rate_pct": str(
                        (Decimal(wins) / Decimal(n) * Decimal("100")).quantize(
                            _PCT_QUANT
                        )
                        if n > 0
                        else None
                    ),
                    "trade_count": n,
                    "label": None,
                }
            )
        return rows
