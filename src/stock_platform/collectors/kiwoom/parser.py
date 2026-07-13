from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.collectors.kiwoom.dto import DailyPriceDTO


class KiwoomDailyParseError(ValueError):
    """키움 일봉 응답을 해석할 수 없을 때 발생한다."""


class KiwoomDailyParser:
    """
    ka10081 응답을 DailyPriceDTO로 변환한다.

    키움 문서/버전에 따라 최상위 배열 키가 달라질 가능성을 고려해
    알려진 키를 우선 확인하고, 마지막에는 일봉 형태의 배열을 탐색한다.
    """

    _LIST_KEYS = (
        "stk_dt_pole_chart_qry",
        "stk_dt_chart_qry",
        "stk_daily_chart",
        "daily_chart",
        "output",
        "data",
    )

    _DATE_KEYS = ("dt", "date", "trade_date", "base_dt")
    _OPEN_KEYS = ("open_pric", "open_price", "open")
    _HIGH_KEYS = ("high_pric", "high_price", "high")
    _LOW_KEYS = ("low_pric", "low_price", "low")
    _CLOSE_KEYS = ("cur_prc", "close_pric", "close_price", "close")
    _VOLUME_KEYS = ("trde_qty", "volume", "acc_trde_qty")
    _TRADE_VALUE_KEYS = (
        "trde_prica",
        "acc_trde_prica",
        "trade_value",
        "amount",
    )
    _CHANGE_RATE_KEYS = (
        "flu_rt",
        "pred_pre_rt",
        "change_rate",
    )

    def parse(self, response: dict[str, Any]) -> list[DailyPriceDTO]:
        rows = self._find_rows(response)

        parsed: list[DailyPriceDTO] = []
        for index, row in enumerate(rows):
            try:
                parsed.append(self._parse_row(row))
            except (KeyError, ValueError, InvalidOperation) as exc:
                raise KiwoomDailyParseError(
                    f"Invalid daily row at index {index}: {exc}"
                ) from exc

        return parsed

    def _find_rows(
        self,
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        for key in self._LIST_KEYS:
            value = response.get(key)
            if self._looks_like_rows(value):
                return list(value)

        discovered = self._search_nested(response)
        if discovered is not None:
            return discovered

        return []

    def _search_nested(
        self,
        value: Any,
    ) -> list[dict[str, Any]] | None:
        if self._looks_like_rows(value):
            return list(value)

        if isinstance(value, dict):
            for nested in value.values():
                result = self._search_nested(nested)
                if result is not None:
                    return result

        if isinstance(value, list):
            for nested in value:
                result = self._search_nested(nested)
                if result is not None:
                    return result

        return None

    def _looks_like_rows(self, value: Any) -> bool:
        if not isinstance(value, list):
            return False

        if not value:
            return True

        first = value[0]
        if not isinstance(first, dict):
            return False

        has_date = any(key in first for key in self._DATE_KEYS)
        has_close = any(key in first for key in self._CLOSE_KEYS)
        return has_date and has_close

    def _parse_row(self, row: dict[str, Any]) -> DailyPriceDTO:
        trade_date = datetime.strptime(
            self._pick_text(row, self._DATE_KEYS),
            "%Y%m%d",
        ).date()

        open_price = self._absolute_decimal(
            self._pick(row, self._OPEN_KEYS)
        )
        high_price = self._absolute_decimal(
            self._pick(row, self._HIGH_KEYS)
        )
        low_price = self._absolute_decimal(
            self._pick(row, self._LOW_KEYS)
        )
        close_price = self._absolute_decimal(
            self._pick(row, self._CLOSE_KEYS)
        )

        volume = self._absolute_decimal(
            self._pick_optional(row, self._VOLUME_KEYS, "0")
        )
        trade_value = self._absolute_decimal(
            self._pick_optional(
                row,
                self._TRADE_VALUE_KEYS,
                "0",
            )
        )

        change_rate_raw = self._pick_optional(
            row,
            self._CHANGE_RATE_KEYS,
            None,
        )
        change_rate = (
            self._decimal(change_rate_raw)
            if change_rate_raw not in (None, "")
            else None
        )

        if high_price < low_price:
            raise ValueError(
                f"high_price({high_price}) is below low_price({low_price})"
            )

        return DailyPriceDTO(
            trade_date=trade_date,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
            trade_value=trade_value,
            change_rate=change_rate,
        )

    @staticmethod
    def _pick(
        row: dict[str, Any],
        keys: Iterable[str],
    ) -> Any:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return row[key]
        raise KeyError(f"missing one of fields: {tuple(keys)}")

    @classmethod
    def _pick_text(
        cls,
        row: dict[str, Any],
        keys: Iterable[str],
    ) -> str:
        return str(cls._pick(row, keys)).strip()

    @staticmethod
    def _pick_optional(
        row: dict[str, Any],
        keys: Iterable[str],
        default: Any,
    ) -> Any:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return row[key]
        return default

    @classmethod
    def _absolute_decimal(cls, value: Any) -> Decimal:
        return abs(cls._decimal(value))

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        raw = str(value).strip().replace(",", "").replace("%", "")
        if not raw:
            return Decimal("0")
        return Decimal(raw)
