from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.broker.account_dto import (
    BrokerAccountSyncResult,
    BrokerPositionSnapshot,
)


ZERO = Decimal("0")


class KiwoomAccountMapper:
    """
    키움 응답 필드명을 내부 계좌 모델로 변환한다.

    키움 응답은 TR별로 축약 필드명이 다를 수 있어 여러 별칭을
    허용한다. raw_data도 함께 저장해 필드 변경을 추적한다.
    """

    POSITION_LIST_KEYS = (
        "acnt_evlt_remn_indv_tot",
        "stk_acnt_evlt_prst",
        "positions",
        "items",
    )

    @classmethod
    def map(
        cls,
        *,
        account_number: str,
        deposit_payload: dict[str, Any],
        balance_payload: dict[str, Any],
    ) -> BrokerAccountSyncResult:
        rows = cls._position_rows(balance_payload)

        positions = [
            cls._position(row)
            for row in rows
            if cls._text(
                row,
                "stk_cd",
                "symbol",
                "code",
            )
        ]

        return BrokerAccountSyncResult(
            broker_code="KIWOOM",
            account_number=account_number,
            deposit_amount=cls._number(
                deposit_payload,
                "entr",
                "deposit",
                "deposit_amount",
            ),
            available_order_amount=cls._number(
                deposit_payload,
                "ord_alow_amt",
                "orderable_amount",
                "available_order_amount",
            ),
            total_purchase_amount=cls._number(
                balance_payload,
                "tot_pur_amt",
                "total_purchase_amount",
            ),
            total_evaluation_amount=cls._number(
                balance_payload,
                "tot_evlt_amt",
                "total_evaluation_amount",
            ),
            total_profit_loss=cls._number(
                balance_payload,
                "tot_evlt_pl",
                "total_profit_loss",
            ),
            total_return_rate=cls._number(
                balance_payload,
                "tot_prft_rt",
                "total_return_rate",
            ),
            positions=positions,
            synchronized_at=datetime.now(timezone.utc),
            raw_data={
                "deposit": deposit_payload,
                "balance": balance_payload,
            },
        )

    @classmethod
    def _position(
        cls,
        row: dict[str, Any],
    ) -> BrokerPositionSnapshot:
        return BrokerPositionSnapshot(
            exchange_code=cls._text(
                row,
                "dmst_stex_tp",
                "exchange_code",
                default="KRX",
            ),
            symbol=cls._text(
                row,
                "stk_cd",
                "symbol",
                "code",
            ).lstrip("A"),
            name=cls._text(
                row,
                "stk_nm",
                "name",
                default="",
            ),
            quantity=cls._number(
                row,
                "rmnd_qty",
                "quantity",
                "holding_quantity",
            ),
            available_quantity=cls._number(
                row,
                "trde_able_qty",
                "available_quantity",
                "sellable_quantity",
            ),
            average_purchase_price=cls._number(
                row,
                "pur_pric",
                "average_purchase_price",
                "average_price",
            ),
            current_price=cls._number(
                row,
                "cur_prc",
                "current_price",
            ),
            purchase_amount=cls._number(
                row,
                "pur_amt",
                "purchase_amount",
            ),
            evaluation_amount=cls._number(
                row,
                "evlt_amt",
                "evaluation_amount",
            ),
            profit_loss=cls._number(
                row,
                "evltv_prft",
                "profit_loss",
            ),
            return_rate=cls._number(
                row,
                "prft_rt",
                "return_rate",
            ),
            raw_data=row,
        )

    @classmethod
    def _position_rows(
        cls,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        for key in cls.POSITION_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    row for row in value
                    if isinstance(row, dict)
                ]
        return []

    @staticmethod
    def _text(
        payload: dict[str, Any],
        *keys: str,
        default: str = "",
    ) -> str:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return default

    @staticmethod
    def _number(
        payload: dict[str, Any],
        *keys: str,
    ) -> Decimal:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                cleaned = (
                    str(value)
                    .replace(",", "")
                    .replace("%", "")
                    .strip()
                )
                try:
                    return Decimal(cleaned)
                except InvalidOperation:
                    continue
        return ZERO
