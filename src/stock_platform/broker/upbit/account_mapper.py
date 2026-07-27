from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.broker.account_dto import (
    BrokerAccountSyncResult,
    BrokerPositionSnapshot,
)


ZERO = Decimal("0")
BROKER_CODE = "UPBIT"
EXCHANGE_CODE = "UPBIT"


class UpbitAccountMapper:
    """
    Upbit GET /v1/accounts 응답 → 공통 BrokerAccountSyncResult.

    KRW 행은 예수금/주문가능으로, 그 외 통화는 보유 포지션으로 매핑한다.
    """

    @classmethod
    def map(
        cls,
        *,
        account_number: str,
        accounts: list[dict[str, Any]],
        tickers_by_market: dict[str, dict[str, Any]] | None = None,
    ) -> BrokerAccountSyncResult:
        tickers = tickers_by_market or {}
        krw_row: dict[str, Any] | None = None
        asset_rows: list[dict[str, Any]] = []

        for row in accounts:
            if not isinstance(row, dict):
                continue
            currency = str(row.get("currency") or "").strip().upper()
            if not currency:
                continue
            if currency == "KRW":
                krw_row = row
            else:
                asset_rows.append(row)

        deposit = cls._decimal(krw_row, "balance") if krw_row else ZERO
        locked = cls._decimal(krw_row, "locked") if krw_row else ZERO
        available = deposit  # 업비트 balance는 잠금 제외 가용분
        # locked가 있으면 총 예수금 = balance + locked
        total_deposit = deposit + locked

        positions: list[BrokerPositionSnapshot] = []
        total_purchase = ZERO
        total_evaluation = ZERO

        for row in asset_rows:
            position = cls._position(row, tickers=tickers)
            # 잔고·잠금 모두 0이면 스냅샷에서 제외
            if position.quantity <= ZERO:
                continue
            positions.append(position)
            total_purchase += position.purchase_amount
            total_evaluation += position.evaluation_amount

        total_profit_loss = total_evaluation - total_purchase
        total_return_rate = ZERO
        if total_purchase > ZERO:
            total_return_rate = (
                total_profit_loss / total_purchase
            ) * Decimal("100")

        return BrokerAccountSyncResult(
            broker_code=BROKER_CODE,
            account_number=account_number,
            deposit_amount=total_deposit,
            available_order_amount=available,
            total_purchase_amount=total_purchase,
            total_evaluation_amount=total_evaluation,
            total_profit_loss=total_profit_loss,
            total_return_rate=total_return_rate,
            positions=positions,
            synchronized_at=datetime.now(timezone.utc),
            raw_data={
                "accounts": accounts,
                "tickers": tickers,
            },
        )

    @classmethod
    def _position(
        cls,
        row: dict[str, Any],
        *,
        tickers: dict[str, dict[str, Any]],
    ) -> BrokerPositionSnapshot:
        currency = str(row.get("currency") or "").strip().upper()
        balance = cls._decimal(row, "balance")
        locked = cls._decimal(row, "locked")
        quantity = balance + locked
        avg_buy = cls._decimal(row, "avg_buy_price")
        unit = str(row.get("unit_currency") or "KRW").strip().upper()
        market = f"{unit}-{currency}"
        ticker = tickers.get(market) or tickers.get(market.upper()) or {}
        current = cls._decimal(ticker, "trade_price", "prev_closing_price")
        if current <= ZERO:
            current = avg_buy

        purchase_amount = (avg_buy * quantity).quantize(
            Decimal("0.00000001")
        ) if quantity else ZERO
        evaluation_amount = (current * quantity).quantize(
            Decimal("0.00000001")
        ) if quantity else ZERO
        profit_loss = evaluation_amount - purchase_amount
        return_rate = ZERO
        if purchase_amount > ZERO:
            return_rate = (profit_loss / purchase_amount) * Decimal("100")

        return BrokerPositionSnapshot(
            exchange_code=EXCHANGE_CODE,
            symbol=market,
            name=currency,
            quantity=quantity,
            available_quantity=balance,
            average_purchase_price=avg_buy,
            current_price=current,
            purchase_amount=purchase_amount,
            evaluation_amount=evaluation_amount,
            profit_loss=profit_loss,
            return_rate=return_rate,
            raw_data=row,
        )

    @staticmethod
    def _decimal(
        payload: dict[str, Any] | None,
        *keys: str,
    ) -> Decimal:
        if not payload:
            return ZERO
        for key in keys:
            value = payload.get(key)
            if value in (None, ""):
                continue
            cleaned = str(value).replace(",", "").strip()
            try:
                return Decimal(cleaned)
            except InvalidOperation:
                continue
        return ZERO
