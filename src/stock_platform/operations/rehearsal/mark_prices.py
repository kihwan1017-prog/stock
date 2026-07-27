"""Paper 리허설용 마크 가격 등록부 (RH* 전용).

PaperAccountService.value_account 는 prices dict를 요구한다.
엔진 내부 fallback 없이, 리허설 준비 단계에서만 RH* 가격을 등록한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


class RehearsalPriceError(ValueError):
    """리허설 마크 가격 준비/조회 실패."""


@dataclass(frozen=True, slots=True)
class RehearsalMarkPrice:
    exchange_code: str
    symbol: str
    current_price: Decimal
    run_id: str
    source: str
    registered_at: datetime

    @property
    def key(self) -> str:
        return f"{self.exchange_code}:{self.symbol}"


class RehearsalMarkPriceRegistry:
    """실행 단위 in-memory 마크 가격 레지스트리."""

    def __init__(self) -> None:
        self._by_key: dict[str, RehearsalMarkPrice] = {}

    @staticmethod
    def normalize_key(exchange_code: str, symbol: str) -> str:
        return f"{exchange_code.strip().upper()}:{symbol.strip().upper()}"

    def register(
        self,
        *,
        exchange_code: str,
        symbol: str,
        current_price: Decimal,
        run_id: str,
        source: str = "OPERATION_REHEARSAL",
    ) -> RehearsalMarkPrice:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol.startswith("RH"):
            raise RehearsalPriceError(
                "rehearsal mark price only allowed for RH* symbols"
            )
        if current_price <= 0:
            raise RehearsalPriceError("current_price must be positive")

        entry = RehearsalMarkPrice(
            exchange_code=exchange_code.strip().upper(),
            symbol=normalized_symbol,
            current_price=current_price.quantize(Decimal("0.01")),
            run_id=run_id,
            source=source,
            registered_at=datetime.now(timezone.utc),
        )
        self._by_key[entry.key] = entry
        return entry

    def get(
        self, exchange_code: str, symbol: str
    ) -> RehearsalMarkPrice | None:
        return self._by_key.get(
            self.normalize_key(exchange_code, symbol)
        )

    def require(
        self, exchange_code: str, symbol: str
    ) -> RehearsalMarkPrice:
        entry = self.get(exchange_code, symbol)
        if entry is None:
            key = self.normalize_key(exchange_code, symbol)
            raise RehearsalPriceError(
                f"Current price is missing: {key}"
            )
        return entry

    def as_prices_dict(self) -> dict[str, Decimal]:
        return {
            key: entry.current_price
            for key, entry in self._by_key.items()
        }

    def cleanup_run(self, run_id: str) -> int:
        removable = [
            key
            for key, entry in self._by_key.items()
            if entry.run_id == run_id
        ]
        for key in removable:
            del self._by_key[key]
        return len(removable)

    def clear(self) -> None:
        self._by_key.clear()
