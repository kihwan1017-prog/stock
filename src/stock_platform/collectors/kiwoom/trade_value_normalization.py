"""키움 ka10081 거래대금(trde_prica) 단위 정규화.

공식 REST API(차트/투자자별 차트)에서 거래대금 필드는 **백만원** 단위다.
platform canonical: market.price_daily.trade_value = KRW 원.

단일 정규화 지점 — parser에서만 호출한다.
"""

from __future__ import annotations

from decimal import Decimal

# 키움 REST 명세: acc_trde_prica / trde_prica 단위 = 백만원
KIWOOM_TRADE_VALUE_MILLION_KRW = Decimal("1000000")

# backfill idempotency: trade_value/(close*volume) 이 값 미만이면 백만원 저장으로 판정
KIWOOM_TRADE_VALUE_LEGACY_MAX_RATIO = Decimal("0.0001")


def normalize_kiwoom_trade_value_to_krw(raw_amount: Decimal) -> Decimal:
    """KIWOOM raw 거래대금(백만원) → canonical KRW."""

    if raw_amount < 0:
        raw_amount = abs(raw_amount)
    return raw_amount * KIWOOM_TRADE_VALUE_MILLION_KRW


def kiwoom_trade_value_needs_million_won_backfill(
    *,
    trade_value: Decimal,
    close_price: Decimal,
    volume: Decimal,
) -> bool:
    """기존 DB 행이 백만원 단위로 저장됐는지 ratio로 판별 (재실행 idempotent)."""

    if trade_value <= 0 or close_price <= 0 or volume <= 0:
        return False
    ratio = trade_value / (close_price * volume)
    return ratio < KIWOOM_TRADE_VALUE_LEGACY_MAX_RATIO
