"""STEP 8-4 — Paper Recovery Adapter (Stock / Crypto)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_adapter import (
    AccountRecoveryContext,
    AdapterRecoveryResult,
)
from stock_platform.database.session import get_session_factory
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    PaperTrade,
)
from stock_platform.trading.models import OrderStatus, PaperOrder


_CRYPTO_EXCHANGES = frozenset({"UPBIT", "CRYPTO", "BINANCE"})


class StockPaperRecoveryAdapter:
    broker_code = "PAPER_STOCK"

    def supports(self, context: AccountRecoveryContext) -> bool:
        code = context.broker_code.upper()
        return code in {"PAPER", "PAPER_STOCK"} and context.market_type in {
            "STOCK",
            "ALL",
        }

    async def recover(
        self, context: AccountRecoveryContext
    ) -> AdapterRecoveryResult:
        return await _recover_paper(
            context,
            broker_code=self.broker_code,
            crypto=False,
        )


class CryptoPaperRecoveryAdapter:
    broker_code = "PAPER_CRYPTO"

    def supports(self, context: AccountRecoveryContext) -> bool:
        code = context.broker_code.upper()
        return code in {"PAPER_CRYPTO", "PAPER"} and context.market_type in {
            "CRYPTO",
            "ALL",
        }

    async def recover(
        self, context: AccountRecoveryContext
    ) -> AdapterRecoveryResult:
        return await _recover_paper(
            context,
            broker_code=self.broker_code,
            crypto=True,
        )


async def _recover_paper(
    context: AccountRecoveryContext,
    *,
    broker_code: str,
    crypto: bool,
) -> AdapterRecoveryResult:
    result = AdapterRecoveryResult(
        status="SUCCESS",
        broker_code=broker_code,
        paper_account_id=context.paper_account_id,
        user_id=context.user_id,
    )
    if context.paper_account_id is None:
        result.status = "FAILED"
        result.errors.append("paper_account_id required")
        result.trading_should_remain_paused = True
        return result.finish()

    session = get_session_factory()()
    try:
        account = session.get(PaperAccount, context.paper_account_id)
        if account is None or account.deleted_at is not None:
            result.status = "FAILED"
            result.errors.append("Paper account not found")
            result.trading_should_remain_paused = True
            return result.finish()

        before = {
            "available_cash": str(account.available_cash),
            "realized_profit_loss": str(account.realized_profit_loss),
        }

        orders = list(
            session.scalars(
                select(PaperOrder).where(
                    PaperOrder.account_id == context.paper_account_id
                )
            )
        )
        trades = list(
            session.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == context.paper_account_id
                )
            )
        )
        positions = list(
            session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == context.paper_account_id
                )
            )
        )

        result.open_orders_checked = sum(
            1
            for o in orders
            if o.status_code
            in {
                OrderStatus.CREATED.value,
                OrderStatus.ACCEPTED.value,
                OrderStatus.PARTIALLY_FILLED.value,
            }
        )

        # 체결 합계 vs 주문
        fills_by_order: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        orphan_trades = 0
        for trade in trades:
            if trade.order_id is None:
                orphan_trades += 1
                continue
            fills_by_order[int(trade.order_id)] += Decimal(str(trade.quantity))

        orders_updated = 0
        for order in orders:
            filled_sum = fills_by_order.get(int(order.order_id), Decimal("0"))
            requested = Decimal(str(order.requested_quantity))
            if filled_sum > requested:
                result.conflicts_found += 1
                result.warnings.append(
                    f"order {order.order_id}: fill qty exceeds order qty"
                )
                continue
            # 주문 filled_quantity 정합
            if Decimal(str(order.filled_quantity)) != filled_sum:
                order.filled_quantity = filled_sum
                orders_updated += 1
            # 상태 복구
            if filled_sum <= 0:
                continue
            if filled_sum >= requested:
                if order.status_code != OrderStatus.FILLED.value:
                    order.status_code = OrderStatus.FILLED.value
                    orders_updated += 1
            elif order.status_code not in {
                OrderStatus.PARTIALLY_FILLED.value,
                OrderStatus.CANCELLED.value,
            }:
                order.status_code = OrderStatus.PARTIALLY_FILLED.value
                orders_updated += 1

            # 평균 체결가
            related = [
                t for t in trades if t.order_id == order.order_id
            ]
            if related:
                notional = sum(
                    (Decimal(str(t.fill_price)) * Decimal(str(t.quantity)))
                    for t in related
                )
                qty = sum(Decimal(str(t.quantity)) for t in related)
                if qty > 0:
                    order.average_fill_price = notional / qty

        result.orders_updated = orders_updated
        if orphan_trades:
            result.conflicts_found += orphan_trades
            result.warnings.append(f"orphan trades: {orphan_trades}")

        # 포지션 재계산 (orders+trades → positions)
        rebuilt: dict[tuple[str, str], dict] = {}
        for trade in trades:
            # crypto / stock 필터
            ex = (trade.exchange_code or "").upper()
            is_crypto = ex in _CRYPTO_EXCHANGES
            if crypto and not is_crypto:
                continue
            if not crypto and is_crypto:
                continue
            key = (ex, trade.symbol.upper())
            slot = rebuilt.setdefault(
                key,
                {
                    "qty": Decimal("0"),
                    "cost": Decimal("0"),
                    "realized": Decimal("0"),
                },
            )
            qty = Decimal(str(trade.quantity))
            price = Decimal(str(trade.fill_price))
            side = (trade.side or "").upper()
            if side == "BUY":
                new_qty = slot["qty"] + qty
                slot["cost"] = slot["cost"] + (price * qty)
                slot["qty"] = new_qty
            elif side == "SELL":
                if slot["qty"] > 0:
                    avg = (
                        slot["cost"] / slot["qty"]
                        if slot["qty"]
                        else Decimal("0")
                    )
                    sell_qty = min(qty, slot["qty"])
                    slot["realized"] += (price - avg) * sell_qty
                    slot["qty"] -= sell_qty
                    slot["cost"] = avg * slot["qty"]
                slot["realized"] += Decimal(str(trade.realized_profit_loss or 0))

        # 기존 포지션과 대조 — 큰 불일치는 conflict
        pos_map = {
            (
                (p.exchange_code or "").upper(),
                (p.symbol or "").upper(),
            ): p
            for p in positions
        }
        positions_updated = 0
        for key, slot in rebuilt.items():
            existing = pos_map.get(key)
            qty = slot["qty"]
            avg = (
                (slot["cost"] / qty) if qty > 0 else Decimal("0")
            )
            if existing is None:
                if qty <= 0:
                    continue
                session.add(
                    PaperPosition(
                        account_id=context.paper_account_id,
                        exchange_code=key[0],
                        symbol=key[1],
                        quantity=qty,
                        average_entry_price=avg,
                        realized_profit_loss=slot["realized"],
                    )
                )
                positions_updated += 1
                continue
            if abs(Decimal(str(existing.quantity)) - qty) > Decimal(
                "0.00000001"
            ):
                result.warnings.append(
                    f"position {key} qty mismatch "
                    f"db={existing.quantity} rebuilt={qty}"
                )
                # 원장 재계산 우선 — before/after 기록
                result.detail.setdefault("position_changes", []).append(
                    {
                        "symbol": key[1],
                        "before_qty": str(existing.quantity),
                        "after_qty": str(qty),
                        "before_avg": str(existing.average_entry_price),
                        "after_avg": str(avg),
                    }
                )
                existing.quantity = qty
                existing.average_entry_price = avg
                existing.realized_profit_loss = slot["realized"]
                positions_updated += 1
            elif qty <= 0 and Decimal(str(existing.quantity)) != 0:
                existing.quantity = Decimal("0")
                positions_updated += 1

        # 고아 포지션 (재계산에 없는데 수량>0)
        for key, existing in pos_map.items():
            ex = key[0]
            is_crypto = ex in _CRYPTO_EXCHANGES
            if crypto and not is_crypto:
                continue
            if not crypto and is_crypto:
                continue
            if key not in rebuilt and Decimal(str(existing.quantity)) > 0:
                result.conflicts_found += 1
                result.warnings.append(f"orphan position {key}")

        result.positions_updated = positions_updated
        result.balances_updated = 0  # 현금 재계산은 보수적으로 경고만
        # 가용현금 음수 검사
        if Decimal(str(account.available_cash)) < 0:
            result.conflicts_found += 1
            result.warnings.append("available_cash negative")

        result.detail["before"] = before
        result.detail["after"] = {
            "available_cash": str(account.available_cash),
            "realized_profit_loss": str(account.realized_profit_loss),
            "orders": len(orders),
            "trades": len(trades),
            "positions": len(positions),
        }

        if result.conflicts_found > 0:
            result.status = "MANUAL_REVIEW"
            result.trading_should_remain_paused = True
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        result.status = "FAILED"
        result.errors.append(str(exc))
        result.trading_should_remain_paused = True
        result.retry_required = True
    finally:
        session.close()

    return result.finish()
