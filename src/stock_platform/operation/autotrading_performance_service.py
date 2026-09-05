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
PeriodFilter = Literal["TODAY", "7D", "30D", "90D", "ALL"]

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
    # MA Dead Cross 를 generic SIGNAL 보다 먼저 분리 (analytics SoT)
    if "DEAD_CROSS" in u or "MA_DEAD" in u:
        return "MA_DEAD_CROSS"
    if "STOP" in u:
        return "STOP_LOSS"
    if "TAKE" in u or "PROFIT" in u:
        return "TAKE_PROFIT"
    if "MAX_HOLD" in u or "TIME_EXIT" in u:
        return "MAX_HOLD_TIME"
    if "SIGNAL" in u or "STRATEGY" in u:
        return "STRATEGY_SIGNAL"
    return "OTHER_AUTO"


def exit_reason_label_ko(category: str) -> str:
    labels = {
        "TAKE_PROFIT": "익절",
        "STOP_LOSS": "손절",
        "TRAILING_STOP": "트레일링 스탑",
        "MA_DEAD_CROSS": "MA 데드크로스",
        "MAX_HOLD_TIME": "최대보유",
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
    days = {"7D": 7, "30D": 30, "90D": 90}.get(period, 30)
    return (day_start - timedelta(days=days - 1)).astimezone(timezone.utc)


def _parse_kst_date(raw: str | date | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()[:10]
    if not text:
        return None
    return date.fromisoformat(text)


def resolve_period_window(
    *,
    period: PeriodFilter = "30D",
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    today: date | None = None,
    max_days: int = 90,
) -> tuple[datetime | None, datetime | None, date, date]:
    """KST date boundary → UTC window.

    start inclusive 00:00 KST, end inclusive through end-of-day KST.
    Returns (start_utc, end_utc_exclusive, start_date_kst, end_date_kst).
    """

    today_kst = today or datetime.now(_KST).date()
    start_d = _parse_kst_date(start_date)
    end_d = _parse_kst_date(end_date)
    if start_d is not None or end_d is not None:
        end_d = end_d or today_kst
        start_d = start_d or end_d
        if start_d > end_d:
            start_d, end_d = end_d, start_d
        if (end_d - start_d).days > max_days:
            start_d = end_d - timedelta(days=max_days)
        start_utc = datetime(
            start_d.year, start_d.month, start_d.day, tzinfo=_KST
        ).astimezone(timezone.utc)
        end_exclusive = datetime(
            end_d.year, end_d.month, end_d.day, tzinfo=_KST
        ) + timedelta(days=1)
        return start_utc, end_exclusive.astimezone(timezone.utc), start_d, end_d

    start_utc = _period_start(period, today=today_kst)
    if start_utc is None:
        # ALL — open-ended; UI still shows today as end
        return None, None, date(1970, 1, 1), today_kst
    start_d = start_utc.astimezone(_KST).date()
    end_exclusive = datetime(
        today_kst.year, today_kst.month, today_kst.day, tzinfo=_KST
    ) + timedelta(days=1)
    return start_utc, end_exclusive.astimezone(timezone.utc), start_d, today_kst


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
        include_ops: bool = False,
        uba_ids: frozenset[int] | None = None,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        user_broker_account_id: int | None = None,
    ) -> dict[str, Any]:
        if user_broker_account_id is not None:
            scope_ubas = frozenset({int(user_broker_account_id)})
        else:
            scope_ubas = uba_ids or DEFAULT_PROTECTED_UBA_IDS
        today = datetime.now(_KST).date()
        period_start, period_end_excl, start_d, end_d = resolve_period_window(
            period=period,
            start_date=start_date,
            end_date=end_date,
            today=today,
        )
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

        def _in_window(closed_at: Any) -> bool:
            if not closed_at:
                return False
            ts = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if period_start is not None and ts < period_start:
                return False
            if period_end_excl is not None and ts >= period_end_excl:
                return False
            return True

        period_closed = [t for t in closed_trades if _in_window(t.get("closed_at"))]

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
        today_order_activity = self._build_today_order_activity(
            brokers=brokers,
            scope_ubas=scope_ubas,
            today_start=today_start,
        )
        today_hourly_pnl = self._build_today_hourly_pnl(
            all_closed=closed_trades,
            today_start=today_start,
        )
        daily_returns = self._build_daily_returns(period_closed)
        cumulative_returns = self._build_cumulative_returns(daily_returns)
        daily_by_broker = (
            self._build_daily_returns_by_broker(period_closed)
            if broker == "ALL"
            else []
        )
        cumulative_by_broker = (
            self._build_cumulative_pnl_by_broker(daily_by_broker)
            if broker == "ALL"
            else []
        )
        open_symbols = {
            str(p.get("symbol") or "").upper() for p in open_positions if p.get("symbol")
        }
        symbol_performance = self._build_symbol_performance(
            period_closed, open_symbols=open_symbols
        )
        symbol_totals = self._symbol_totals(symbol_performance)
        exit_reason_performance = self._build_exit_reason_performance(period_closed)
        win_loss = self._build_win_loss(period_closed)
        return_distribution = self._build_return_distribution(period_closed)
        broker_comparison = self._build_broker_comparison(period_closed, closed_trades)
        recent_closed = period_closed[:20]
        round_trips = list(period_closed)
        holding_return = self._build_holding_return(period_closed)

        ops_insight: dict[str, Any] | None = None
        if include_ops:
            ops_insight = self._build_ops_insight(
                broker=broker,
                scope_ubas=scope_ubas,
                today_start=today_start,
            )

        closed_count = len(period_closed)
        low_sample = closed_count < 5
        period_label = (
            f"{start_d.isoformat()} ~ {end_d.isoformat()}"
            if period_start is not None or start_date or end_date
            else period
        )

        return {
            "broker": broker,
            "period": period,
            "period_window": {
                "start_date": start_d.isoformat(),
                "end_date": end_d.isoformat(),
                "label": period_label,
                "timezone": "Asia/Seoul",
                "user_broker_account_id": (
                    int(user_broker_account_id)
                    if user_broker_account_id is not None
                    else None
                ),
            },
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
            "today_order_activity": today_order_activity,
            "today_hourly_pnl": today_hourly_pnl,
            "daily_returns": daily_returns,
            "cumulative_returns": cumulative_returns,
            "daily_by_broker": daily_by_broker,
            "cumulative_by_broker": cumulative_by_broker,
            "symbol_performance": symbol_performance,
            "symbol_performance_totals": symbol_totals,
            "exit_reason_performance": exit_reason_performance,
            "win_loss": win_loss,
            "return_distribution": return_distribution,
            "broker_comparison": broker_comparison,
            "recent_closed_trades": recent_closed,
            "round_trips": round_trips,
            "holding_return": holding_return,
            "ops_insight": ops_insight,
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

    def build_symbol_detail(
        self,
        *,
        symbol: str,
        broker: BrokerFilter = "UPBIT",
        period: PeriodFilter = "TODAY",
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        user_broker_account_id: int | None = None,
    ) -> dict[str, Any]:
        """종목 Drawer용 — 일별 집계 + 건별 AUTO 거래."""

        payload = self.build(
            broker=broker,
            period=period,
            start_date=start_date,
            end_date=end_date,
            user_broker_account_id=user_broker_account_id,
        )
        sym = str(symbol or "").strip().upper()
        trades = [
            t
            for t in (payload.get("round_trips") or [])
            if str(t.get("symbol") or "").upper() == sym
        ]
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in trades:
            d = _kst_trading_date(
                datetime.fromisoformat(str(t["closed_at"]).replace("Z", "+00:00"))
                if t.get("closed_at")
                else None
            )
            if d is not None:
                by_day[d.isoformat()].append(t)

        daily_rows: list[dict[str, Any]] = []
        for day in sorted(by_day.keys(), reverse=True):
            xs = by_day[day]
            gross = sum((Decimal(str(x["gross_pnl"])) for x in xs), ZERO)
            fees = sum((Decimal(str(x.get("fees") or 0)) for x in xs), ZERO)
            net = sum((Decimal(str(x["net_pnl"])) for x in xs), ZERO)
            wins = sum(1 for x in xs if Decimal(str(x["net_pnl"])) > ZERO)
            daily_rows.append(
                {
                    "date": day,
                    "buy_count": len(xs),  # round-trip 기준 완료건 = 매수·매도 쌍
                    "sell_count": len(xs),
                    "round_trip_count": len(xs),
                    "gross_pnl": str(gross.quantize(QUANT)),
                    "fees": str(fees.quantize(QUANT)),
                    "net_pnl": str(net.quantize(QUANT)),
                    "win_rate_pct": str(
                        (Decimal(wins) / Decimal(len(xs)) * Decimal("100")).quantize(
                            _PCT_QUANT
                        )
                        if xs
                        else ZERO
                    ),
                }
            )

        gross = sum((Decimal(str(x["gross_pnl"])) for x in trades), ZERO)
        fees = sum((Decimal(str(x.get("fees") or 0)) for x in trades), ZERO)
        net = sum((Decimal(str(x["net_pnl"])) for x in trades), ZERO)
        wins = sum(1 for x in trades if Decimal(str(x["net_pnl"])) > ZERO)
        return {
            "symbol": sym,
            "period_window": payload.get("period_window"),
            "totals": {
                "round_trip_count": len(trades),
                "buy_count": len(trades),
                "sell_count": len(trades),
                "gross_pnl": str(gross.quantize(QUANT)),
                "fees": str(fees.quantize(QUANT)),
                "net_pnl": str(net.quantize(QUANT)),
                "win_rate_pct": str(
                    (Decimal(wins) / Decimal(len(trades)) * Decimal("100")).quantize(
                        _PCT_QUANT
                    )
                    if trades
                    else None
                ),
            },
            "daily": daily_rows,
            "trades": trades,
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

        # 오늘 수익/손실 금액 — canonical net_pnl 기준 (새 산식 금지)
        today_profit = sum(
            (Decimal(str(t["net_pnl"])) for t in today_closed if Decimal(str(t["net_pnl"])) > ZERO),
            ZERO,
        ).quantize(QUANT)
        today_loss_abs = sum(
            (
                abs(Decimal(str(t["net_pnl"])))
                for t in today_closed
                if Decimal(str(t["net_pnl"])) < ZERO
            ),
            ZERO,
        ).quantize(QUANT)
        today_loss = (-today_loss_abs).quantize(QUANT)  # UI: -5,000원
        today_fees = sum(
            (Decimal(str(t.get("fees") or 0)) for t in today_closed),
            ZERO,
        ).quantize(QUANT)
        today_wins = sum(1 for t in today_closed if Decimal(str(t["net_pnl"])) > ZERO)
        today_losses = sum(1 for t in today_closed if Decimal(str(t["net_pnl"])) < ZERO)
        today_closed_n = len(today_closed)
        today_win_rate = (
            str(
                (Decimal(today_wins) / Decimal(today_closed_n) * Decimal("100")).quantize(
                    _PCT_QUANT
                )
            )
            if today_closed_n > 0
            else None
        )
        today_symbols = {str(t.get("symbol") or "") for t in today_closed if t.get("symbol")}
        hold_secs = [
            int(t["duration_sec"])
            for t in today_closed
            if isinstance(t.get("duration_sec"), (int, float))
        ]
        avg_hold_sec = int(sum(hold_secs) / len(hold_secs)) if hold_secs else None

        best_trade = max(
            today_closed,
            key=lambda t: Decimal(str(t["net_pnl"])),
            default=None,
        )
        worst_trade = min(
            today_closed,
            key=lambda t: Decimal(str(t["net_pnl"])),
            default=None,
        )

        period_net = _sum_net(period_closed)
        period_cost = _sum_entry_cost(period_closed)
        period_gross = sum(
            (Decimal(str(t.get("gross_pnl") or 0)) for t in period_closed),
            ZERO,
        ).quantize(QUANT)
        period_fees = sum(
            (Decimal(str(t.get("fees") or 0)) for t in period_closed),
            ZERO,
        ).quantize(QUANT)
        # consistency: net ≈ gross - fees (0.01원 허용)
        consistency_delta = (period_gross - period_fees - period_net).quantize(QUANT)
        all_net = _sum_net(all_closed)
        all_cost = _sum_entry_cost(all_closed)
        all_gross = sum(
            (Decimal(str(t.get("gross_pnl") or 0)) for t in all_closed),
            ZERO,
        ).quantize(QUANT)
        all_fees = sum(
            (Decimal(str(t.get("fees") or 0)) for t in all_closed),
            ZERO,
        ).quantize(QUANT)
        # lifetime 수익/손실 — gross 기준 (수수료 전). 손실은 음수.
        all_winning_gross = sum(
            (
                Decimal(str(t.get("gross_pnl") or 0))
                for t in all_closed
                if Decimal(str(t.get("gross_pnl") or 0)) > ZERO
            ),
            ZERO,
        ).quantize(QUANT)
        all_losing_gross = sum(
            (
                Decimal(str(t.get("gross_pnl") or 0))
                for t in all_closed
                if Decimal(str(t.get("gross_pnl") or 0)) < ZERO
            ),
            ZERO,
        ).quantize(QUANT)
        # net 기준 표시용 (기존 today_* 와 동일 semantics)
        all_profit_net = sum(
            (
                Decimal(str(t["net_pnl"]))
                for t in all_closed
                if Decimal(str(t["net_pnl"])) > ZERO
            ),
            ZERO,
        ).quantize(QUANT)
        all_loss_net_abs = sum(
            (
                abs(Decimal(str(t["net_pnl"])))
                for t in all_closed
                if Decimal(str(t["net_pnl"])) < ZERO
            ),
            ZERO,
        ).quantize(QUANT)
        lifetime_formula_delta = (all_gross - all_fees - all_net).quantize(QUANT)

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

        gross_wins = sum(
            (Decimal(str(t["net_pnl"])) for t in period_closed if Decimal(str(t["net_pnl"])) > ZERO),
            ZERO,
        )
        gross_losses_abs = sum(
            (
                abs(Decimal(str(t["net_pnl"])))
                for t in period_closed
                if Decimal(str(t["net_pnl"])) < ZERO
            ),
            ZERO,
        )
        profit_factor = None
        if gross_losses_abs > ZERO:
            profit_factor = str((gross_wins / gross_losses_abs).quantize(Decimal("0.0001")))
        elif gross_wins > ZERO:
            profit_factor = "INF"

        hold_secs_p = [
            int(t["duration_sec"])
            for t in period_closed
            if isinstance(t.get("duration_sec"), (int, float))
        ]
        avg_hold_period = (
            int(sum(hold_secs_p) / len(hold_secs_p)) if hold_secs_p else None
        )

        return {
            "broker": broker,
            "period": period,
            "today_realized_pnl": str(today_net),
            "today_net_pnl": str(today_net),  # alias — 순손익 = canonical realized
            "today_profit_amount": str(today_profit),
            "today_loss_amount": str(today_loss),
            "today_fees": str(today_fees),
            "today_gross_pnl": str(
                sum(
                    (Decimal(str(t.get("gross_pnl") or 0)) for t in today_closed),
                    ZERO,
                ).quantize(QUANT)
            ),
            "today_wins": today_wins,
            "today_losses": today_losses,
            "today_win_rate_pct": today_win_rate,
            "today_closed_trade_count": today_closed_n,
            "today_symbol_count": len(today_symbols),
            "today_avg_hold_sec": avg_hold_sec,
            "today_best_symbol": (
                str(best_trade.get("symbol")) if best_trade is not None else None
            ),
            "today_best_pnl": (
                str(Decimal(str(best_trade["net_pnl"])).quantize(QUANT))
                if best_trade is not None
                else None
            ),
            "today_worst_symbol": (
                str(worst_trade.get("symbol")) if worst_trade is not None else None
            ),
            "today_worst_pnl": (
                str(Decimal(str(worst_trade["net_pnl"])).quantize(QUANT))
                if worst_trade is not None
                else None
            ),
            "today_return_pct": _return_pct(today_net, today_cost),
            "period_realized_pnl": str(period_net),
            "period_net_pnl": str(period_net),
            "period_gross_pnl": str(period_gross),
            "period_fees": str(period_fees),
            "period_profit_factor": profit_factor,
            "period_avg_hold_sec": avg_hold_period,
            "period_gross_minus_fees_delta": str(consistency_delta),
            "period_return_pct": _return_pct(period_net, period_cost),
            "cumulative_realized_pnl": str(all_net),
            "cumulative_net_pnl": str(all_net),
            "cumulative_gross_pnl": str(all_gross),
            "cumulative_fees": str(all_fees),
            "cumulative_winning_gross": str(all_winning_gross),
            "cumulative_losing_gross": str(all_losing_gross),
            "cumulative_profit_amount": str(all_profit_net),
            "cumulative_loss_amount": str((-all_loss_net_abs).quantize(QUANT)),
            "cumulative_closed_trade_count": len(all_closed),
            "cumulative_gross_minus_fees_delta": str(lifetime_formula_delta),
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

    def _build_today_order_activity(
        self,
        *,
        brokers: list[str],
        scope_ubas: frozenset[int],
        today_start: datetime,
    ) -> dict[str, Any]:
        """오늘(KST) AUTO 주문 건수/금액 — TradingOrder filled_amount 재사용."""

        filled_statuses = {"FILLED", "DONE", "COMPLETED", "PARTIAL", "PARTIALLY_FILLED"}
        cancelled_statuses = {"CANCELLED", "CANCELED", "REJECTED", "EXPIRED"}
        open_statuses = {"NEW", "ACCEPTED", "SUBMITTED", "PENDING", "OPEN", "CREATED"}

        buy_count = sell_count = filled_count = open_count = cancelled_count = 0
        buy_amount = sell_amount = ZERO

        rows = list(
            self.session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id.in_(scope_ubas),
                    TradingOrderEntity.broker_code.in_(brokers),
                    TradingOrderEntity.created_at >= today_start,
                    TradingOrderEntity.strategy_id.isnot(None),
                )
            )
        )
        for order in rows:
            side = str(getattr(order, "side_code", "") or "").upper()
            st = str(getattr(order, "status_code", "") or "").upper()
            amount = Decimal(str(getattr(order, "filled_amount", 0) or 0))
            if amount <= ZERO:
                qty = Decimal(str(getattr(order, "filled_quantity", 0) or 0))
                px = Decimal(str(getattr(order, "average_fill_price", 0) or 0))
                if qty > ZERO and px > ZERO:
                    amount = (qty * px).quantize(QUANT)

            if side in {"BUY", "BID"}:
                buy_count += 1
                if st in filled_statuses or amount > ZERO:
                    buy_amount += amount
            elif side in {"SELL", "ASK"}:
                sell_count += 1
                if st in filled_statuses or amount > ZERO:
                    sell_amount += amount

            if st in filled_statuses or (
                Decimal(str(getattr(order, "filled_quantity", 0) or 0)) > ZERO
            ):
                filled_count += 1
            if st in open_statuses and st not in filled_statuses:
                open_count += 1
            if st in cancelled_statuses:
                cancelled_count += 1

        return {
            "buy_count": buy_count,
            "sell_count": sell_count,
            "filled_count": filled_count,
            "open_count": open_count,
            "cancelled_count": cancelled_count,
            "buy_amount": str(buy_amount.quantize(QUANT)),
            "sell_amount": str(sell_amount.quantize(QUANT)),
            "day_boundary": "Asia/Seoul",
        }

    def _build_today_hourly_pnl(
        self,
        *,
        all_closed: list[dict[str, Any]],
        today_start: datetime,
    ) -> list[dict[str, Any]]:
        """오늘 시간별 실현손익(bar) + 누적(line) — closed binding net_pnl."""

        buckets: dict[int, Decimal] = {h: ZERO for h in range(24)}
        for t in all_closed:
            closed_at = t.get("closed_at")
            if not closed_at:
                continue
            ts = datetime.fromisoformat(str(closed_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < today_start:
                continue
            hour = ts.astimezone(_KST).hour
            buckets[hour] += Decimal(str(t["net_pnl"]))

        cum = ZERO
        rows: list[dict[str, Any]] = []
        for hour in range(24):
            pnl = buckets[hour].quantize(QUANT)
            cum = (cum + pnl).quantize(QUANT)
            rows.append(
                {
                    "hour": hour,
                    "label": f"{hour:02d}:00",
                    "realized_pnl": str(pnl),
                    "cumulative_realized_pnl": str(cum),
                }
            )
        return rows

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
        self,
        period_closed: list[dict[str, Any]],
        *,
        open_symbols: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in period_closed:
            by_sym[str(t["symbol"])].append(t)

        open_set = {s.upper() for s in (open_symbols or set())}
        rows: list[dict[str, Any]] = []
        for sym, trades in by_sym.items():
            gross = sum((Decimal(str(x.get("gross_pnl") or 0)) for x in trades), ZERO)
            fees = sum((Decimal(str(x.get("fees") or 0)) for x in trades), ZERO)
            net = sum((Decimal(str(x["net_pnl"])) for x in trades), ZERO)
            cost = sum((Decimal(str(x["entry_cost"])) for x in trades), ZERO)
            wins = sum(1 for x in trades if Decimal(str(x["net_pnl"])) > ZERO)
            losses = sum(1 for x in trades if Decimal(str(x["net_pnl"])) < ZERO)
            n = len(trades)
            holds = [
                int(x["duration_sec"])
                for x in trades
                if isinstance(x.get("duration_sec"), (int, float))
            ]
            exit_dist: dict[str, int] = defaultdict(int)
            for x in trades:
                exit_dist[str(x.get("exit_reason_category") or "OTHER_AUTO")] += 1
            top_exit = (
                max(exit_dist.items(), key=lambda kv: kv[1])[0] if exit_dist else None
            )
            last_closed = max(
                (x.get("closed_at") for x in trades if x.get("closed_at")),
                default=None,
            )
            rows.append(
                {
                    "symbol": sym,
                    "symbol_name": None,  # instrument join optional
                    "buy_count": n,
                    "sell_count": n,
                    "round_trip_count": n,
                    "buy_amount": str(cost.quantize(QUANT)),
                    "sell_amount": str((cost + gross).quantize(QUANT)),
                    "gross_pnl": str(gross.quantize(QUANT)),
                    "fees": str(fees.quantize(QUANT)),
                    "net_pnl": str(net.quantize(QUANT)),
                    "realized_pnl": str(net.quantize(QUANT)),  # legacy alias
                    "win_count": wins,
                    "loss_count": losses,
                    "win_rate_pct": str(
                        (Decimal(wins) / Decimal(n) * Decimal("100")).quantize(
                            _PCT_QUANT
                        )
                        if n > 0
                        else ZERO
                    ),
                    "avg_hold_sec": int(sum(holds) / len(holds)) if holds else None,
                    "return_pct": str(
                        (net / cost * Decimal("100")).quantize(_PCT_QUANT)
                        if cost > ZERO
                        else ZERO
                    ),
                    "trade_count": n,
                    "primary_exit_reason": top_exit,
                    "primary_exit_reason_label_ko": (
                        exit_reason_label_ko(top_exit) if top_exit else None
                    ),
                    "last_closed_at": last_closed,
                    "has_open_auto": sym.upper() in open_set,
                }
            )
        # 기본: 매수 건수 내림차순, 동점이면 순손익 오름차순
        rows.sort(
            key=lambda r: (
                -int(r.get("buy_count") or 0),
                Decimal(str(r["net_pnl"])),
            )
        )
        return rows

    def _symbol_totals(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "buy_count": 0,
                "sell_count": 0,
                "round_trip_count": 0,
                "gross_pnl": "0.00",
                "fees": "0.00",
                "net_pnl": "0.00",
            }
        return {
            "buy_count": sum(int(r.get("buy_count") or 0) for r in rows),
            "sell_count": sum(int(r.get("sell_count") or 0) for r in rows),
            "round_trip_count": sum(int(r.get("round_trip_count") or 0) for r in rows),
            "gross_pnl": str(
                sum((Decimal(str(r.get("gross_pnl") or 0)) for r in rows), ZERO).quantize(
                    QUANT
                )
            ),
            "fees": str(
                sum((Decimal(str(r.get("fees") or 0)) for r in rows), ZERO).quantize(
                    QUANT
                )
            ),
            "net_pnl": str(
                sum((Decimal(str(r.get("net_pnl") or 0)) for r in rows), ZERO).quantize(
                    QUANT
                )
            ),
        }

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
            rets = [Decimal(str(x["return_pct"])) for x in period_trades]
            avg_ret = (
                (sum(rets, ZERO) / Decimal(n)).quantize(_PCT_QUANT) if n > 0 else None
            )
            losses_pnl = [
                Decimal(str(x["net_pnl"]))
                for x in period_trades
                if Decimal(str(x["net_pnl"])) < ZERO
            ]
            max_loss = min(losses_pnl) if losses_pnl else None
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
                    "avg_return_pct": str(avg_ret) if avg_ret is not None else None,
                    "max_loss_pnl": str(max_loss.quantize(QUANT))
                    if max_loss is not None
                    else None,
                    "trade_count": n,
                    "label": None,
                }
            )
        return rows

    def _build_daily_returns_by_broker(
        self, period_closed: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_day_broker: dict[tuple[date, str], list[dict[str, Any]]] = defaultdict(
            list
        )
        for t in period_closed:
            closed_at = t.get("closed_at")
            if not closed_at:
                continue
            day = _kst_trading_date(datetime.fromisoformat(str(closed_at)))
            if not day:
                continue
            code = str(t.get("broker_code") or "").upper()
            by_day_broker[(day, code)].append(t)

        rows: list[dict[str, Any]] = []
        for (day, code), trades in sorted(by_day_broker.items()):
            net = sum((Decimal(str(x["net_pnl"])) for x in trades), ZERO)
            rows.append(
                {
                    "trading_date": day.isoformat(),
                    "broker_code": code,
                    "realized_pnl": str(net.quantize(QUANT)),
                    "trade_count": len(trades),
                }
            )
        return rows

    def _build_cumulative_pnl_by_broker(
        self, daily_by_broker: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cum: dict[str, Decimal] = {}
        rows: list[dict[str, Any]] = []
        for row in sorted(daily_by_broker, key=lambda r: (r["trading_date"], r["broker_code"])):
            code = str(row["broker_code"])
            cum[code] = cum.get(code, ZERO) + Decimal(str(row["realized_pnl"]))
            rows.append(
                {
                    "trading_date": row["trading_date"],
                    "broker_code": code,
                    "cumulative_realized_pnl": str(cum[code].quantize(QUANT)),
                }
            )
        return rows

    def _build_holding_return(
        self, period_closed: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "binding_id": t.get("binding_id"),
                "broker_code": t.get("broker_code"),
                "symbol": t.get("symbol"),
                "duration_sec": t.get("duration_sec"),
                "return_pct": t.get("return_pct"),
                "net_pnl": t.get("net_pnl"),
            }
            for t in period_closed
            if t.get("duration_sec") is not None
        ]

    def _build_ops_insight(
        self,
        *,
        broker: BrokerFilter,
        scope_ubas: frozenset[int],
        today_start: datetime,
    ) -> dict[str, Any]:
        from stock_platform.operation.upbit_full_market.constants import (
            SLOT_WAITING_SIGNAL,
        )
        from stock_platform.operation.upbit_full_market.entities import (
            UpbitPortfolioPolicyEntity,
            UpbitPositionSlotEntity,
        )
        from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
            portfolio_entry_telemetry,
        )

        pipeline: dict[str, Any] = {}
        blockers: list[dict[str, Any]] = []

        if broker in ("ALL", "UPBIT") and 1380 in scope_ubas:
            uba = 1380
            telem = portfolio_entry_telemetry.snapshot(uba) or {}
            policy = self.session.scalar(
                select(UpbitPortfolioPolicyEntity).where(
                    UpbitPortfolioPolicyEntity.user_broker_account_id == uba
                )
            )
            slots = list(
                self.session.scalars(
                    select(UpbitPositionSlotEntity).where(
                        UpbitPositionSlotEntity.user_broker_account_id == uba
                    )
                )
            )
            waiting = [
                s
                for s in slots
                if str(s.status).upper() == SLOT_WAITING_SIGNAL
                and str(s.symbol or "").strip()
            ]
            capacity = int(getattr(policy, "max_positions", 0) or 0) if policy else 0

            total_eval = 0
            blocked_eval = 0
            reason_counts: dict[str, int] = defaultdict(int)
            for row in telem.values():
                if not isinstance(row, dict):
                    continue
                cnt = int(row.get("evaluation_count") or 0)
                total_eval += cnt
                if str(row.get("last_decision") or "").upper() == "BLOCK":
                    blocked_eval += cnt
                reason = str(row.get("last_block_reason") or "UNKNOWN")
                reason_counts[reason] += cnt

            auto_orders_today = 0
            auto_fills_today = 0
            for order in self.session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.created_at >= today_start,
                    TradingOrderEntity.strategy_id.isnot(None),
                )
            ):
                auto_orders_today += 1
                st = str(getattr(order, "status_code", "") or "").upper()
                if st in {"FILLED", "DONE", "COMPLETED"}:
                    auto_fills_today += 1

            open_auto = len(
                list(
                    self.session.scalars(
                        select(StrategyPositionBindingEntity).where(
                            StrategyPositionBindingEntity.user_broker_account_id
                            == uba,
                            StrategyPositionBindingEntity.broker_code == "UPBIT",
                            StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
                            StrategyPositionBindingEntity.ownership_code
                            == OWNERSHIP_STRATEGY,
                        )
                    )
                )
            )

            pipeline = {
                "broker_code": "UPBIT",
                "slots_occupied": len(waiting),
                "slots_capacity": capacity,
                "entry_evaluations": total_eval,
                "entry_blocked": blocked_eval,
                "auto_open_positions": open_auto,
                "orders_today_auto": auto_orders_today,
                "fills_today_auto": auto_fills_today,
            }

            if total_eval > 0:
                for reason, cnt in sorted(
                    reason_counts.items(), key=lambda x: x[1], reverse=True
                ):
                    blockers.append(
                        {
                            "reason_code": reason,
                            "count": cnt,
                            "pct": str(
                                (
                                    Decimal(cnt)
                                    / Decimal(total_eval)
                                    * Decimal("100")
                                ).quantize(_PCT_QUANT)
                            ),
                        }
                    )

        return {
            "pipeline": pipeline,
            "entry_blockers": blockers,
            "blocker_note": (
                "telemetry evaluation_count를 last_block_reason별 집계 "
                "(.run/uba_*_entry_eval_latest.json + in-memory)"
            ),
        }
