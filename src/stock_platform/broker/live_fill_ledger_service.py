"""Kiwoom/LIVE 체결 → BrokerPositionSnapshot + AccountSnapshot 원장.

신규 Migration 없이 기존 snapshot 테이블을 fill-driven ledger로 사용한다.
브로커 재조회 Snapshot과 구분하기 위해 raw_data.ledger_source 를 기록한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)


class LiveFillLedgerService:
    """TradingOrder 체결을 Position/Cash 스냅샷에 반영."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_cash_seed(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str = "KIWOOM",
        initial_cash: Decimal = Decimal("10000000"),
    ) -> BrokerAccountSnapshotEntity:
        """MOCK/테스트용 초기 현금 시드 (없으면 생성)."""

        account_number = f"UBA:{int(user_broker_account_id)}"
        # UBA 고유 제약(uq_..._uba_active) 우선 — account_number 표기 불일치 흡수
        row = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code == broker_code,
                BrokerAccountSnapshotEntity.user_broker_account_id
                == int(user_broker_account_id),
            )
        )
        if row is None:
            row = self._session.scalar(
                select(BrokerAccountSnapshotEntity).where(
                    BrokerAccountSnapshotEntity.broker_code == broker_code,
                    BrokerAccountSnapshotEntity.account_number
                    == account_number,
                )
            )
        if row is not None:
            return row
        now = datetime.now(timezone.utc)
        row = BrokerAccountSnapshotEntity(
            broker_code=broker_code,
            account_number=account_number,
            user_broker_account_id=int(user_broker_account_id),
            currency_code="KRW",
            deposit_amount=initial_cash,
            available_order_amount=initial_cash,
            total_purchase_amount=Decimal("0"),
            total_evaluation_amount=Decimal("0"),
            total_profit_loss=Decimal("0"),
            total_return_rate=Decimal("0"),
            raw_data={
                "ledger_source": "FILL_DRIVEN",
                "realized_profit_loss": "0",
            },
            synchronized_at=now,
            snapshot_time=now,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def apply_execution(
        self,
        *,
        order,
        event: KiwoomExecutionEvent,
        actor: str = "LIVE_FILL_LEDGER",
    ) -> dict:
        uba_id = getattr(order, "user_broker_account_id", None)
        if uba_id is None:
            return {"applied": False, "reason": "NO_UBA"}

        broker_code = str(
            getattr(order, "broker_code", "KIWOOM") or "KIWOOM"
        ).upper()
        exchange = str(
            getattr(order, "exchange_code", "KRX") or "KRX"
        ).upper()
        symbol = str(
            getattr(order, "symbol", "") or event.symbol
        ).upper()
        account_number = f"UBA:{int(uba_id)}"
        side = str(
            getattr(order, "side_code", "") or event.side_code or ""
        ).upper()
        qty = Decimal(str(event.execution_quantity))
        price = Decimal(str(event.execution_price))
        if qty <= 0 or price <= 0:
            return {"applied": False, "reason": "INVALID_QTY_PRICE"}

        # 동일 UBA+심볼 포지션 우선 (exchange 표기 불일치 흡수)
        pos = self._session.scalar(
            select(BrokerPositionSnapshotEntity)
            .where(
                BrokerPositionSnapshotEntity.broker_code == broker_code,
                BrokerPositionSnapshotEntity.user_broker_account_id
                == int(uba_id),
                BrokerPositionSnapshotEntity.symbol == symbol,
            )
            .order_by(
                # 정확 exchange 일치 행 우선
                (
                    BrokerPositionSnapshotEntity.exchange_code == exchange
                ).desc(),
                BrokerPositionSnapshotEntity.quantity.desc(),
            )
            .limit(1)
        )
        if pos is None:
            pos = self._session.scalar(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.broker_code == broker_code,
                    BrokerPositionSnapshotEntity.account_number
                    == account_number,
                    BrokerPositionSnapshotEntity.exchange_code == exchange,
                    BrokerPositionSnapshotEntity.symbol == symbol,
                )
            )
        if pos is not None:
            raw_pos = dict(pos.raw_data or {})
            applied_ids = set(raw_pos.get("applied_execution_ids") or [])
            if event.broker_execution_id in applied_ids:
                return {
                    "applied": False,
                    "reason": "DUPLICATE_EXECUTION",
                    "quantity": str(pos.quantity),
                }

        now = datetime.now(timezone.utc)
        if pos is None:
            pos = BrokerPositionSnapshotEntity(
                broker_code=broker_code,
                account_number=account_number,
                user_broker_account_id=int(uba_id),
                exchange_code=exchange,
                symbol=symbol,
                name=symbol,
                quantity=Decimal("0"),
                available_quantity=Decimal("0"),
                average_purchase_price=Decimal("0"),
                current_price=price,
                purchase_amount=Decimal("0"),
                evaluation_amount=Decimal("0"),
                profit_loss=Decimal("0"),
                return_rate=Decimal("0"),
                raw_data={"ledger_source": "FILL_DRIVEN", "actor": actor},
                synchronized_at=now,
            )
            self._session.add(pos)

        prev_qty = Decimal(str(pos.quantity or 0))
        prev_avg = Decimal(str(pos.average_purchase_price or 0))
        realized_delta = Decimal("0")
        notional = (qty * price).quantize(Decimal("0.01"))

        if side == "BUY":
            new_qty = prev_qty + qty
            if new_qty > 0:
                pos.average_purchase_price = (
                    (prev_qty * prev_avg) + (qty * price)
                ) / new_qty
            pos.quantity = new_qty
            pos.available_quantity = new_qty
        elif side == "SELL":
            # 실현손익 = (매도가 - 평균단가) * 수량
            realized_delta = (
                (price - prev_avg) * qty
            ).quantize(Decimal("0.01"))
            new_qty = max(Decimal("0"), prev_qty - qty)
            pos.quantity = new_qty
            pos.available_quantity = new_qty
            if new_qty <= 0:
                pos.average_purchase_price = Decimal("0")
        else:
            return {"applied": False, "reason": "UNKNOWN_SIDE"}

        pos.current_price = price
        pos.purchase_amount = (
            Decimal(str(pos.quantity))
            * Decimal(str(pos.average_purchase_price))
        ).quantize(Decimal("0.01"))
        pos.evaluation_amount = (
            Decimal(str(pos.quantity)) * price
        ).quantize(Decimal("0.01"))
        pos.profit_loss = (
            Decimal(str(pos.evaluation_amount))
            - Decimal(str(pos.purchase_amount))
        ).quantize(Decimal("0.01"))
        if Decimal(str(pos.purchase_amount)) > 0:
            pos.return_rate = (
                Decimal(str(pos.profit_loss))
                / Decimal(str(pos.purchase_amount))
            ).quantize(Decimal("0.000001"))
        else:
            pos.return_rate = Decimal("0")

        raw = dict(pos.raw_data or {})
        raw["ledger_source"] = "FILL_DRIVEN"
        raw["last_actor"] = actor
        raw["last_broker_execution_id"] = event.broker_execution_id
        raw["last_trading_order_id"] = int(order.order_id)
        ids = list(raw.get("applied_execution_ids") or [])
        ids.append(event.broker_execution_id)
        raw["applied_execution_ids"] = ids[-50:]
        pos.raw_data = raw
        pos.user_broker_account_id = int(uba_id)
        pos.synchronized_at = now
        pos.snapshot_status = "ACTIVE"

        # Cash / Realized PnL
        cash = self.ensure_cash_seed(
            user_broker_account_id=int(uba_id),
            broker_code=broker_code,
        )
        avail = Decimal(str(cash.available_order_amount or 0))
        deposit = Decimal(str(cash.deposit_amount or 0))
        cash_raw = dict(cash.raw_data or {})
        realized = Decimal(str(cash_raw.get("realized_profit_loss") or 0))

        if side == "BUY":
            avail = avail - notional
            deposit = deposit - notional
        else:
            avail = avail + notional
            deposit = deposit + notional
            realized = realized + realized_delta

        cash.available_order_amount = avail
        cash.deposit_amount = deposit
        cash.total_purchase_amount = Decimal(str(pos.purchase_amount))
        cash.total_evaluation_amount = Decimal(str(pos.evaluation_amount))
        cash.total_profit_loss = Decimal(str(pos.profit_loss))
        cash_raw["ledger_source"] = "FILL_DRIVEN"
        cash_raw["realized_profit_loss"] = str(realized)
        cash_raw["last_actor"] = actor
        cash.raw_data = cash_raw
        cash.user_broker_account_id = int(uba_id)
        cash.synchronized_at = now
        cash.snapshot_time = now

        return {
            "applied": True,
            "reason": "OK",
            "quantity": str(pos.quantity),
            "average_purchase_price": str(pos.average_purchase_price),
            "available_cash": str(cash.available_order_amount),
            "realized_profit_loss": str(realized),
            "realized_delta": str(realized_delta),
        }
