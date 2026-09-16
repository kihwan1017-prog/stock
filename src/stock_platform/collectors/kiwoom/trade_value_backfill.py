"""KIWOOM KRX price_daily.trade_value 백만원→원 단위 backfill (idempotent)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.collectors.kiwoom.trade_value_normalization import (
    KIWOOM_TRADE_VALUE_LEGACY_MAX_RATIO,
    KIWOOM_TRADE_VALUE_MILLION_KRW,
)


@dataclass(frozen=True)
class KiwoomTradeValueBackfillResult:
    """backfill 실행 결과 요약."""

    profile_sample_size: int
    ratio_cluster_lt_1e4: int
    ratio_cluster_near_1: int
    ratio_cluster_other: int
    rows_before: int
    affected_rows: int
    unchanged_rows: int
    failed_rows: int


_PROFILE_SQL = text(
    """
    SELECT
        COUNT(*) AS sample_size,
        COUNT(*) FILTER (
            WHERE p.trade_value > 0
              AND p.close_price > 0
              AND p.volume > 0
              AND (p.trade_value / (p.close_price * p.volume)) < 0.0001
        ) AS cluster_lt_1e4,
        COUNT(*) FILTER (
            WHERE p.trade_value > 0
              AND p.close_price > 0
              AND p.volume > 0
              AND (p.trade_value / (p.close_price * p.volume)) BETWEEN 0.1 AND 10
        ) AS cluster_near_1,
        COUNT(*) FILTER (
            WHERE p.trade_value > 0
              AND p.close_price > 0
              AND p.volume > 0
              AND NOT (
                  (p.trade_value / (p.close_price * p.volume)) < 0.0001
                  OR (p.trade_value / (p.close_price * p.volume)) BETWEEN 0.1 AND 10
              )
        ) AS cluster_other
    FROM market.price_daily p
    JOIN market.instrument i ON i.instrument_id = p.instrument_id
    WHERE i.exchange_code = 'KRX'
      AND p.source = 'KIWOOM'
    """
)

_COUNT_KIWOOM_KRX_SQL = text(
    """
    SELECT COUNT(*)
    FROM market.price_daily p
    JOIN market.instrument i ON i.instrument_id = p.instrument_id
    WHERE i.exchange_code = 'KRX'
      AND p.source = 'KIWOOM'
    """
)

_BACKFILL_SQL = text(
    """
    UPDATE market.price_daily p
    SET trade_value = p.trade_value * :million,
        updated_at = NOW()
    FROM market.instrument i
    WHERE p.instrument_id = i.instrument_id
      AND i.exchange_code = 'KRX'
      AND p.source = 'KIWOOM'
      AND p.trade_value > 0
      AND p.close_price > 0
      AND p.volume > 0
      AND (p.trade_value / (p.close_price * p.volume)) < :max_ratio
    """
)


def profile_kiwoom_krx_trade_value_ratios(session: Session) -> dict[str, int]:
    """KRX/KIWOOM trade_value/(close*volume) ratio 분포."""

    row = session.execute(_PROFILE_SQL).mappings().one()
    return {
        "sample_size": int(row["sample_size"] or 0),
        "cluster_lt_1e4": int(row["cluster_lt_1e4"] or 0),
        "cluster_near_1": int(row["cluster_near_1"] or 0),
        "cluster_other": int(row["cluster_other"] or 0),
    }


def backfill_kiwoom_krx_trade_values(session: Session) -> KiwoomTradeValueBackfillResult:
    """백만원 단위로 저장된 KIWOOM KRX 행만 ×1,000,000 (재실행 idempotent)."""

    profile_before = profile_kiwoom_krx_trade_value_ratios(session)
    rows_before = int(session.scalar(_COUNT_KIWOOM_KRX_SQL) or 0)
    needs_scale = profile_before["cluster_lt_1e4"]

    if needs_scale <= 0:
        return KiwoomTradeValueBackfillResult(
            profile_sample_size=profile_before["sample_size"],
            ratio_cluster_lt_1e4=profile_before["cluster_lt_1e4"],
            ratio_cluster_near_1=profile_before["cluster_near_1"],
            ratio_cluster_other=profile_before["cluster_other"],
            rows_before=rows_before,
            affected_rows=0,
            unchanged_rows=rows_before,
            failed_rows=0,
        )

    result = session.execute(
        _BACKFILL_SQL,
        {
            "million": str(KIWOOM_TRADE_VALUE_MILLION_KRW),
            "max_ratio": str(KIWOOM_TRADE_VALUE_LEGACY_MAX_RATIO),
        },
    )
    affected = int(result.rowcount or 0)
    session.commit()

    profile_after = profile_kiwoom_krx_trade_value_ratios(session)
    unchanged = max(0, rows_before - affected)

    return KiwoomTradeValueBackfillResult(
        profile_sample_size=profile_after["sample_size"],
        ratio_cluster_lt_1e4=profile_after["cluster_lt_1e4"],
        ratio_cluster_near_1=profile_after["cluster_near_1"],
        ratio_cluster_other=profile_after["cluster_other"],
        rows_before=rows_before,
        affected_rows=affected,
        unchanged_rows=unchanged,
        failed_rows=profile_after["cluster_lt_1e4"],
    )
