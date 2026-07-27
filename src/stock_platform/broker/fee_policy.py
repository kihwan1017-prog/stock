from __future__ import annotations

from decimal import Decimal


ZERO = Decimal("0")


class UpbitFeePolicy:
    """
    업비트 수수료 단순 정책 (STEP9 Paper/백테스트용).

    실제 등급·프로모션은 반영하지 않으며 보수적 기본값만 사용.
    """

    DEFAULT_TAKER_RATE = Decimal("0.0005")  # 0.05%
    DEFAULT_MAKER_RATE = Decimal("0.0005")

    def __init__(
        self,
        *,
        taker_rate: Decimal | None = None,
        maker_rate: Decimal | None = None,
    ) -> None:
        self.taker_rate = taker_rate or self.DEFAULT_TAKER_RATE
        self.maker_rate = maker_rate or self.DEFAULT_MAKER_RATE

    def fee_amount(
        self,
        *,
        notional: Decimal,
        is_maker: bool = False,
    ) -> Decimal:
        if notional <= ZERO:
            return ZERO
        rate = self.maker_rate if is_maker else self.taker_rate
        return (notional * rate).quantize(Decimal("0.0001"))


class KrxFeePolicy:
    """국내 주식 단순 수수료+세금 자리표시 (백테스트용)."""

    COMMISSION_RATE = Decimal("0.00015")
    SELL_TAX_RATE = Decimal("0.0023")

    def fee_amount(
        self,
        *,
        notional: Decimal,
        side: str = "BUY",
    ) -> Decimal:
        if notional <= ZERO:
            return ZERO
        commission = notional * self.COMMISSION_RATE
        tax = (
            notional * self.SELL_TAX_RATE
            if side.upper() == "SELL"
            else ZERO
        )
        return (commission + tax).quantize(Decimal("1"))


def fee_policy_for_exchange(exchange_code: str):
    code = (exchange_code or "").upper()
    if code in {"UPBIT", "CRYPTO"}:
        return UpbitFeePolicy()
    return KrxFeePolicy()
