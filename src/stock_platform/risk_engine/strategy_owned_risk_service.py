"""Strategy-owned PnL — 수동 보유와 분리된 자동매매 일손익."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    OWNERSHIP_MANUAL,
    OWNERSHIP_STRATEGY,
    OWNERSHIP_UNKNOWN,
    StrategyDailyPnlEntity,
    StrategyPositionBindingEntity,
)


ZERO = Decimal("0")
QUANT = Decimal("0.01")
_KST = ZoneInfo("Asia/Seoul")
FILLED_STATUSES = frozenset(
    {"FILLED", "PARTIALLY_FILLED", "DONE", "COMPLETED"}
)


@dataclass(frozen=True, slots=True)
class StrategyDailyPnlSnapshot:
    user_broker_account_id: int
    broker_code: str
    strategy_id: int
    deployment_id: int
    trading_date: date
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees: Decimal
    current_pnl: Decimal
    current_loss_amount: Decimal
    loss_limit_amount: Decimal | None
    entry_count: int
    closed_trade_count: int
    open_binding_count: int
    consecutive_losses: int
    status_code: str
    filled_buy_count: int
    filled_sell_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_broker_account_id": self.user_broker_account_id,
            "broker_code": self.broker_code,
            "strategy_id": self.strategy_id,
            "deployment_id": self.deployment_id,
            "trading_date": self.trading_date.isoformat(),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
            "fees": str(self.fees),
            "current_pnl": str(self.current_pnl),
            "current_loss_amount": str(self.current_loss_amount),
            "loss_limit_amount": (
                str(self.loss_limit_amount)
                if self.loss_limit_amount is not None
                else None
            ),
            "entry_count": self.entry_count,
            "closed_trade_count": self.closed_trade_count,
            "open_binding_count": self.open_binding_count,
            "consecutive_losses": self.consecutive_losses,
            "status_code": self.status_code,
            "filled_buy_count": self.filled_buy_count,
            "filled_sell_count": self.filled_sell_count,
            "scope": "STRATEGY_OWNED",
        }


def parse_strategy_id(raw: str | int | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


# 하위 호환 alias
_parse_strategy_id = parse_strategy_id


class StrategyOwnedRiskService:
    """Strategy Daily Loss / ownership binding."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def classify_snapshot_positions(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        symbols: list[str],
    ) -> dict[str, str]:
        """심볼별 MANUAL / STRATEGY_OWNED / UNKNOWN — 추정으로 STRATEGY 부여 금지."""

        uba = int(user_broker_account_id)
        broker = str(broker_code).upper()
        open_bindings = list(
            self._session.scalars(
                select(StrategyPositionBindingEntity).where(
                    StrategyPositionBindingEntity.user_broker_account_id
                    == uba,
                    StrategyPositionBindingEntity.broker_code == broker,
                    StrategyPositionBindingEntity.status
                    == BINDING_STATUS_OPEN,
                )
            )
        )
        owned = {
            str(b.symbol).upper()
            for b in open_bindings
            if Decimal(str(b.owned_quantity or 0)) > 0
        }
        out: dict[str, str] = {}
        for sym in symbols:
            key = str(sym).upper()
            if key in owned:
                out[key] = OWNERSHIP_STRATEGY
            else:
                # provenance 없으면 수동/미관리로 안전 분류
                out[key] = OWNERSHIP_MANUAL
        return out

    def ensure_binding_from_fill(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None,
        symbol: str,
        entry_order_id: int | None,
        broker_order_id: str | None,
        quantity: Decimal,
        entry_price: Decimal | None,
        side: str,
        fees: Decimal = ZERO,
    ) -> StrategyPositionBindingEntity | None:
        """BUY fill → OPEN binding. SELL fill → qty 감소 / CLOSED."""

        uba = int(user_broker_account_id)
        broker = str(broker_code).upper()
        sid = int(strategy_id)
        dep = int(deployment_id or 0)
        sym = str(symbol).upper()
        side_u = str(side).upper()
        qty = Decimal(str(quantity))
        if qty <= ZERO:
            return None

        if side_u == "BUY":
            existing = None
            if entry_order_id is not None:
                existing = self._session.scalar(
                    select(StrategyPositionBindingEntity).where(
                        StrategyPositionBindingEntity.user_broker_account_id
                        == uba,
                        StrategyPositionBindingEntity.broker_code == broker,
                        StrategyPositionBindingEntity.strategy_id == sid,
                        StrategyPositionBindingEntity.symbol == sym,
                        StrategyPositionBindingEntity.entry_order_id
                        == int(entry_order_id),
                    )
                )
            if existing is not None:
                existing.owned_quantity = (
                    Decimal(str(existing.owned_quantity or 0)) + qty
                )
                existing.status = BINDING_STATUS_OPEN
                existing.closed_at = None
                if entry_price is not None:
                    existing.entry_price = Decimal(str(entry_price))
                existing.updated_at = datetime.now(timezone.utc)
                self._session.flush()
                return existing

            row = StrategyPositionBindingEntity(
                user_broker_account_id=uba,
                broker_code=broker,
                strategy_id=sid,
                deployment_id=dep if dep else None,
                symbol=sym,
                status=BINDING_STATUS_OPEN,
                ownership_code=OWNERSHIP_STRATEGY,
                entry_order_id=entry_order_id,
                broker_order_id=broker_order_id,
                owned_quantity=qty,
                entry_price=(
                    Decimal(str(entry_price)) if entry_price is not None else None
                ),
                fees=Decimal(str(fees or 0)),
            )
            self._session.add(row)
            self._session.flush()
            return row

        if side_u == "SELL":
            opens = list(
                self._session.scalars(
                    select(StrategyPositionBindingEntity)
                    .where(
                        StrategyPositionBindingEntity.user_broker_account_id
                        == uba,
                        StrategyPositionBindingEntity.broker_code == broker,
                        StrategyPositionBindingEntity.strategy_id == sid,
                        StrategyPositionBindingEntity.symbol == sym,
                        StrategyPositionBindingEntity.status
                        == BINDING_STATUS_OPEN,
                    )
                    .order_by(StrategyPositionBindingEntity.opened_at.asc())
                )
            )
            remain = qty
            last: StrategyPositionBindingEntity | None = None
            for row in opens:
                if remain <= ZERO:
                    break
                owned = Decimal(str(row.owned_quantity or 0))
                take = min(owned, remain)
                entry = Decimal(str(row.entry_price or 0))
                # 실현손익은 호출측이 가격을 meta에 넣을 수 있음 — 여기선 qty 감소만
                row.owned_quantity = owned - take
                row.fees = Decimal(str(row.fees or 0)) + Decimal(str(fees or 0))
                if row.owned_quantity <= ZERO:
                    row.owned_quantity = ZERO
                    row.status = BINDING_STATUS_CLOSED
                    row.closed_at = datetime.now(timezone.utc)
                remain -= take
                last = row
            self._session.flush()
            return last

        return None

    def compute_and_persist(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None = None,
        loss_limit: Decimal | None = None,
        trading_date: date | None = None,
        mark_prices: dict[str, Decimal] | None = None,
    ) -> StrategyDailyPnlSnapshot:
        """provenance 기반 계산. 강제 0 금지 — 증거 없으면 자연스럽게 0."""

        uba = int(user_broker_account_id)
        broker = str(broker_code).upper()
        sid = int(strategy_id)
        dep = int(deployment_id or 0)
        day = trading_date or datetime.now(_KST).date()
        day_start = datetime(day.year, day.month, day.day, tzinfo=_KST).astimezone(
            timezone.utc
        )
        day_end = day_start + timedelta(days=1)

        orders = list(
            self._session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.strategy_id == sid,
                    TradingOrderEntity.created_at >= day_start,
                    TradingOrderEntity.created_at < day_end,
                )
            )
        )
        if dep:
            orders = [
                o
                for o in orders
                if o.strategy_deployment_id is None
                or int(o.strategy_deployment_id) == dep
            ]

        filled_buys = 0
        filled_sells = 0
        fees = ZERO
        for order in orders:
            status = str(getattr(order, "status_code", "") or "").upper()
            if status not in FILLED_STATUSES:
                continue
            side = str(getattr(order, "side_code", "") or "").upper()
            if side == "BUY":
                filled_buys += 1
            elif side == "SELL":
                filled_sells += 1
            fee = Decimal(str(getattr(order, "fee_amount", 0) or 0))
            tax = Decimal(str(getattr(order, "tax_amount", 0) or 0))
            fees += fee + tax

        opens = list(
            self._session.scalars(
                select(StrategyPositionBindingEntity).where(
                    StrategyPositionBindingEntity.user_broker_account_id == uba,
                    StrategyPositionBindingEntity.broker_code == broker,
                    StrategyPositionBindingEntity.strategy_id == sid,
                    StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
                )
            )
        )
        if dep:
            opens = [
                b
                for b in opens
                if b.deployment_id is None or int(b.deployment_id or 0) == dep
            ]

        unrealized = ZERO
        prices = dict(mark_prices or {})
        if not prices and opens:
            from stock_platform.broker.account_models import (
                BrokerPositionSnapshotEntity,
            )

            snap_rows = list(
                self._session.scalars(
                    select(BrokerPositionSnapshotEntity).where(
                        BrokerPositionSnapshotEntity.user_broker_account_id
                        == uba,
                        BrokerPositionSnapshotEntity.snapshot_status
                        == "ACTIVE",
                    )
                )
            )
            for p in snap_rows:
                prices[str(p.symbol).upper()] = Decimal(
                    str(p.current_price or 0)
                )

        for b in opens:
            qty = Decimal(str(b.owned_quantity or 0))
            entry = Decimal(str(b.entry_price or 0))
            mark = Decimal(str(prices.get(str(b.symbol).upper(), 0) or 0))
            if qty > ZERO and entry > ZERO and mark > ZERO:
                unrealized += ((mark - entry) * qty).quantize(QUANT)
            fees += Decimal(str(b.fees or 0))

        # 당일 청산 binding의 기록된 실현손익만 합산 (추정 금지)
        realized = ZERO
        closed_today = list(
            self._session.scalars(
                select(StrategyPositionBindingEntity).where(
                    StrategyPositionBindingEntity.user_broker_account_id == uba,
                    StrategyPositionBindingEntity.strategy_id == sid,
                    StrategyPositionBindingEntity.status
                    == BINDING_STATUS_CLOSED,
                    StrategyPositionBindingEntity.closed_at >= day_start,
                    StrategyPositionBindingEntity.closed_at < day_end,
                )
            )
        )
        for b in closed_today:
            realized += Decimal(str(b.realized_pnl or 0))
            fees += Decimal(str(b.fees or 0))

        current_pnl = (realized + unrealized - fees).quantize(QUANT)
        current_loss = max(-current_pnl, ZERO).quantize(QUANT)
        status = "SAFE"
        if loss_limit is not None and loss_limit > ZERO and current_loss >= loss_limit:
            status = "LIMIT_REACHED"

        row = self._session.scalar(
            select(StrategyDailyPnlEntity).where(
                StrategyDailyPnlEntity.trading_date == day,
                StrategyDailyPnlEntity.broker_code == broker,
                StrategyDailyPnlEntity.user_broker_account_id == uba,
                StrategyDailyPnlEntity.strategy_id == sid,
                StrategyDailyPnlEntity.deployment_id == dep,
            )
        )
        if row is None:
            row = StrategyDailyPnlEntity(
                trading_date=day,
                broker_code=broker,
                user_broker_account_id=uba,
                strategy_id=sid,
                deployment_id=dep,
            )
            self._session.add(row)

        row.realized_pnl = realized.quantize(QUANT)
        row.unrealized_pnl = unrealized.quantize(QUANT)
        row.fees = fees.quantize(QUANT)
        row.current_pnl = current_pnl
        row.current_loss_amount = current_loss
        row.loss_limit_amount = loss_limit
        row.entry_count = filled_buys
        row.closed_trade_count = filled_sells
        row.open_binding_count = len(
            [b for b in opens if Decimal(str(b.owned_quantity or 0)) > 0]
        )
        row.status_code = status
        row.updated_at = datetime.now(timezone.utc)
        row.meta_json = {
            "filled_buy_count": filled_buys,
            "filled_sell_count": filled_sells,
            "ownership": OWNERSHIP_STRATEGY,
        }
        self._session.flush()

        return StrategyDailyPnlSnapshot(
            user_broker_account_id=uba,
            broker_code=broker,
            strategy_id=sid,
            deployment_id=dep,
            trading_date=day,
            realized_pnl=row.realized_pnl,
            unrealized_pnl=row.unrealized_pnl,
            fees=row.fees,
            current_pnl=row.current_pnl,
            current_loss_amount=row.current_loss_amount,
            loss_limit_amount=row.loss_limit_amount,
            entry_count=int(row.entry_count),
            closed_trade_count=int(row.closed_trade_count),
            open_binding_count=int(row.open_binding_count),
            consecutive_losses=int(row.consecutive_losses or 0),
            status_code=status,
            filled_buy_count=filled_buys,
            filled_sell_count=filled_sells,
        )

    def strategy_daily_loss_breached(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int | str | None,
        deployment_id: int | None,
        limit: Decimal,
    ) -> tuple[bool, dict[str, Any]]:
        """Strategy ENTRY용 일손실 게이트. strategy_id 없으면 (False, reason)."""

        sid = _parse_strategy_id(strategy_id)
        if sid is None:
            return False, {"mode": "NO_STRATEGY_SCOPE"}
        if limit <= ZERO:
            return False, {"mode": "NO_LIMIT"}

        snap = self.compute_and_persist(
            user_broker_account_id=user_broker_account_id,
            broker_code=broker_code,
            strategy_id=sid,
            deployment_id=deployment_id,
            loss_limit=limit,
        )
        hit = snap.current_loss_amount >= limit
        return hit, snap.to_dict()

    def account_hard_safety_blocks_entry(
        self,
        *,
        user_broker_account_id: int,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Account Safety CRITICAL만 차단.
        Account MTM daily loss 자체는 Strategy ENTRY를 막지 않음.
        Kill 활성 / account_daily_loss가 KILL_SWITCH_ACTIVE 인 경우만.
        """

        from stock_platform.risk_engine.daily_loss_entities import (
            AccountDailyLossEntity,
        )
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )
        from stock_platform.trading.account_identity import (
            uba_kill_switch_scope,
        )

        uba = int(user_broker_account_id)
        kill = KillSwitchService(self._session)
        scope = uba_kill_switch_scope(uba)
        if kill.is_active_for_scopes(
            [KillSwitchService.GLOBAL_SCOPE, scope]
        ):
            return True, {
                "reason": "KILL_SWITCH_ACTIVE",
                "scope": "ACCOUNT_SAFETY",
            }

        today = datetime.now(_KST).date()
        row = self._session.scalar(
            select(AccountDailyLossEntity).where(
                AccountDailyLossEntity.user_broker_account_id == uba,
                AccountDailyLossEntity.trading_date == today,
            )
        )
        if row is not None and str(row.status_code).upper() in {
            "KILL_SWITCH_ACTIVE",
            "KILL",
        }:
            return True, {
                "reason": "ACCOUNT_DAILY_LOSS_KILL_STATUS",
                "scope": "ACCOUNT_SAFETY",
                "status_code": row.status_code,
                "current_loss_amount": str(row.current_loss_amount),
            }
        # telemetry만 — LIMIT_REACHED(MTM)는 Strategy ENTRY를 막지 않음
        detail = {
            "scope": "ACCOUNT_SAFETY",
            "account_daily_loss_status": (
                str(row.status_code) if row is not None else None
            ),
            "account_current_loss": (
                str(row.current_loss_amount) if row is not None else None
            ),
            "blocks_strategy_entry": False,
        }
        return False, detail
