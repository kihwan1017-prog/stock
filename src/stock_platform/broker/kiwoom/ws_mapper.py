from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderEventType,
    KiwoomOrderExecutionEvent,
)


ZERO = Decimal("0")


class KiwoomOrderExecutionMapper:
    """
    주문체결 WebSocket 메시지를 내부 이벤트로 변환한다.

    키움 WebSocket 응답은 실시간 타입/명세 버전에 따라 필드명이
    달라질 수 있어 여러 별칭을 허용하고 원본 메시지를 보존한다.
    """

    @classmethod
    def map(cls, payload: dict[str, Any]) -> KiwoomOrderExecutionEvent:
        data = cls._unwrap(payload)

        order_quantity = cls._number(
            data, "ord_qty", "order_quantity", "900"
        )
        filled_quantity = cls._number(
            data, "cntr_qty", "filled_quantity", "911"
        )
        remaining_quantity = cls._number(
            data, "oso_qty", "remaining_quantity", "902"
        )

        if (
            remaining_quantity == ZERO
            and order_quantity >= filled_quantity
        ):
            remaining_quantity = order_quantity - filled_quantity

        status_text = cls._text(
            data,
            "ord_stt",
            "status",
            "913",
        )
        event_type = cls._event_type(
            status_text=status_text,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining_quantity,
        )

        side_text = cls._text(
            data,
            "io_tp_nm",
            "side",
            "907",
        )

        return KiwoomOrderExecutionEvent(
            account_number=cls._text(
                data,
                "acnt_no",
                "account_number",
                "9201",
            ),
            broker_order_id=cls._text(
                data,
                "ord_no",
                "order_no",
                "9203",
            ),
            original_order_id=cls._optional_text(
                data,
                "orig_ord_no",
                "original_order_id",
                "904",
            ),
            exchange_code=cls._text(
                data,
                "dmst_stex_tp",
                "exchange_code",
                default="KRX",
            ),
            symbol=cls._text(
                data,
                "stk_cd",
                "symbol",
                "9001",
            ).lstrip("A"),
            side=cls._side(side_text),
            event_type=event_type,
            order_quantity=order_quantity,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining_quantity,
            fill_price=cls._optional_number(
                data,
                "cntr_prc",
                "fill_price",
                "910",
            ),
            average_fill_price=cls._optional_number(
                data,
                "avg_cntr_prc",
                "average_fill_price",
                "931",
            ),
            event_time=cls._event_time(
                cls._text(
                    data,
                    "cntr_tm",
                    "event_time",
                    "908",
                )
            ),
            received_at=datetime.now(timezone.utc),
            raw_data=payload,
        )

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("data", "values", "body", "item"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value

        if isinstance(payload.get("data"), list):
            rows = payload["data"]
            if rows and isinstance(rows[0], dict):
                return rows[0]

        return payload

    @staticmethod
    def _event_type(
        *,
        status_text: str,
        filled_quantity: Decimal,
        remaining_quantity: Decimal,
    ) -> KiwoomOrderEventType:
        upper = status_text.upper()

        if "취소" in status_text or "CANCEL" in upper:
            return KiwoomOrderEventType.CANCELLED
        if "거부" in status_text or "REJECT" in upper:
            return KiwoomOrderEventType.REJECTED
        if remaining_quantity == ZERO and filled_quantity > ZERO:
            return KiwoomOrderEventType.FILLED
        if filled_quantity > ZERO and remaining_quantity > ZERO:
            return KiwoomOrderEventType.PARTIALLY_FILLED
        if "접수" in status_text or "ACCEPT" in upper:
            return KiwoomOrderEventType.ACCEPTED
        return KiwoomOrderEventType.UNKNOWN

    @staticmethod
    def _side(value: str) -> str:
        upper = value.upper()
        if "매수" in value or "BUY" in upper:
            return "BUY"
        if "매도" in value or "SELL" in upper:
            return "SELL"
        return value or "UNKNOWN"

    @staticmethod
    def _event_time(value: str) -> datetime:
        digits = "".join(ch for ch in value if ch.isdigit())
        now = datetime.now(timezone.utc)

        if len(digits) >= 6:
            try:
                return now.replace(
                    hour=int(digits[0:2]),
                    minute=int(digits[2:4]),
                    second=int(digits[4:6]),
                    microsecond=0,
                )
            except ValueError:
                pass

        return now

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

    @classmethod
    def _optional_text(
        cls,
        payload: dict[str, Any],
        *keys: str,
    ) -> str | None:
        value = cls._text(payload, *keys)
        return value or None

    @staticmethod
    def _optional_number(
        payload: dict[str, Any],
        *keys: str,
    ) -> Decimal | None:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                try:
                    return Decimal(
                        str(value).replace(",", "").strip()
                    )
                except InvalidOperation:
                    continue
        return None

    @classmethod
    def _number(
        cls,
        payload: dict[str, Any],
        *keys: str,
    ) -> Decimal:
        value = cls._optional_number(payload, *keys)
        return value if value is not None else ZERO
