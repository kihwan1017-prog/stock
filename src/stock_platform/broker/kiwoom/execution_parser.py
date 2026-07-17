from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)


class KiwoomExecutionParser:
    """
    키움 실시간 주문체결(서비스 타입 00) 메시지를 내부 이벤트로 변환합니다.

    키움 WebSocket 응답은 data 내부에 필드 ID 기반 values가 포함될 수 있으므로
    운영 적용 전 공식 문서의 현재 FID 매핑을 확인해 FIELD_ALIASES를 조정하세요.
    """

    FIELD_ALIASES = {
        "broker_order_id": (
            "ord_no",
            "order_no",
            "9203",
        ),
        "broker_execution_id": (
            "cntr_no",
            "execution_no",
            "909",
        ),
        "symbol": (
            "stk_cd",
            "symbol",
            "9001",
        ),
        "side_code": (
            "io_tp_nm",
            "side",
            "907",
        ),
        "execution_price": (
            "cntr_pric",
            "execution_price",
            "910",
        ),
        "execution_quantity": (
            "cntr_qty",
            "execution_quantity",
            "911",
        ),
        "remaining_quantity": (
            "oso_qty",
            "remaining_quantity",
            "902",
        ),
        "execution_time": (
            "cntr_tm",
            "execution_time",
            "908",
        ),
    }

    def parse_message(
        self,
        message: dict[str, Any],
    ) -> list[KiwoomExecutionEvent]:
        if not self._is_execution_message(message):
            return []

        rows = self._extract_rows(message)
        events: list[KiwoomExecutionEvent] = []

        for row in rows:
            normalized = self._normalize_row(row)
            order_id = self._pick(
                normalized,
                self.FIELD_ALIASES[
                    "broker_order_id"
                ],
            )
            execution_id = self._pick(
                normalized,
                self.FIELD_ALIASES[
                    "broker_execution_id"
                ],
            )

            if not order_id or not execution_id:
                continue

            events.append(
                KiwoomExecutionEvent(
                    broker_order_id=str(order_id),
                    broker_execution_id=str(
                        execution_id
                    ),
                    symbol=str(
                        self._pick(
                            normalized,
                            self.FIELD_ALIASES[
                                "symbol"
                            ],
                        )
                        or ""
                    ).lstrip("A"),
                    side_code=self._optional_text(
                        self._pick(
                            normalized,
                            self.FIELD_ALIASES[
                                "side_code"
                            ],
                        )
                    ),
                    execution_price=self._decimal(
                        self._pick(
                            normalized,
                            self.FIELD_ALIASES[
                                "execution_price"
                            ],
                        )
                    ),
                    execution_quantity=self._decimal(
                        self._pick(
                            normalized,
                            self.FIELD_ALIASES[
                                "execution_quantity"
                            ],
                        )
                    ),
                    remaining_quantity=(
                        self._optional_decimal(
                            self._pick(
                                normalized,
                                self.FIELD_ALIASES[
                                    "remaining_quantity"
                                ],
                            )
                        )
                    ),
                    executed_at=self._parse_time(
                        self._pick(
                            normalized,
                            self.FIELD_ALIASES[
                                "execution_time"
                            ],
                        )
                    ),
                    raw_payload=row,
                )
            )

        return events

    @staticmethod
    def _is_execution_message(
        message: dict[str, Any],
    ) -> bool:
        service = str(
            message.get("type")
            or message.get("service_type")
            or message.get("trnm")
            or ""
        ).upper()

        return (
            service in {"00", "REAL", "REALTIME"}
            or "data" in message
        )

    @staticmethod
    def _extract_rows(
        message: dict[str, Any],
    ) -> list[dict[str, Any]]:
        data = message.get("data", message)

        if isinstance(data, list):
            return [
                item
                for item in data
                if isinstance(item, dict)
            ]

        if isinstance(data, dict):
            nested = (
                data.get("items")
                or data.get("values")
                or data.get("data")
            )

            if isinstance(nested, list):
                return [
                    item
                    for item in nested
                    if isinstance(item, dict)
                ]

            return [data]

        return []

    @staticmethod
    def _normalize_row(
        row: dict[str, Any],
    ) -> dict[str, Any]:
        values = row.get("values")

        if isinstance(values, dict):
            return {**row, **values}

        return row

    @staticmethod
    def _pick(
        row: dict[str, Any],
        aliases: tuple[str, ...],
    ) -> Any:
        for key in aliases:
            if key in row and row[key] not in (
                None,
                "",
            ):
                return row[key]
        return None

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        parsed = (
            KiwoomExecutionParser
            ._optional_decimal(value)
        )
        return parsed or Decimal("0")

    @staticmethod
    def _optional_decimal(
        value: Any,
    ) -> Decimal | None:
        if value in (None, ""):
            return None

        text = (
            str(value)
            .replace(",", "")
            .replace("+", "")
            .strip()
        )

        try:
            return abs(Decimal(text))
        except InvalidOperation:
            return None

    @staticmethod
    def _optional_text(
        value: Any,
    ) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    @staticmethod
    def _parse_time(value: Any) -> datetime:
        now = datetime.now(timezone.utc)

        if value in (None, ""):
            return now

        text = str(value).strip()

        for fmt in (
            "%Y%m%d%H%M%S",
            "%H%M%S",
        ):
            try:
                parsed = datetime.strptime(
                    text,
                    fmt,
                )

                if fmt == "%H%M%S":
                    parsed = parsed.replace(
                        year=now.year,
                        month=now.month,
                        day=now.day,
                    )

                return parsed.replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

        return now
