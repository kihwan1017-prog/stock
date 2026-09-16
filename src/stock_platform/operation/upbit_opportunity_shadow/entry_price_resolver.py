"""Shadow canonical entry price — detected_at 시점 DB 1m candle 기준.

Scanner API snapshot 가격과 DB candle 불일치 시 DB candle close 우선.
REAL 주문/정책과 무관 — research/shadow 전용.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.candle_loader import (
    list_minute_bars_db,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    as_utc,
    floor_minute,
)

# candidate 가 DB candle 대비 이 비율 초과 시 stale 로 간주
DEFAULT_MAX_CANDIDATE_DEVIATION_PCT = 2.0

QUALITY_CANONICAL = "CANONICAL_DB_CANDLE"
QUALITY_CANDIDATE_MATCH = "CANDIDATE_MATCHES_DB"
QUALITY_CANDIDATE_FALLBACK = "CANDIDATE_FALLBACK_NO_DB"
QUALITY_CANDIDATE_REJECTED = "CANDIDATE_STALE_REJECTED"

SOURCE_DB_DETECTED_CANDLE = "market.candle_minute.detected_candle_close"
SOURCE_CANDIDATE_SCANNER = "scanner_candidate_price"


@dataclass(frozen=True, slots=True)
class EntryPriceResolution:
  """canonical shadow entry price + provenance."""

  price: Decimal
  detected_at: datetime
  candle_at: datetime | None
  source: str
  quality: str
  candidate_price: Decimal | None
  deviation_pct: float | None
  ok: bool
  reason: str | None = None

  def to_provenance_dict(self) -> dict[str, Any]:
    return {
      "schema": "shadow_entry_price_provenance_v1",
      "price": float(self.price),
      "detected_at": as_utc(self.detected_at).isoformat(),
      "candle_at": (
        as_utc(self.candle_at).isoformat() if self.candle_at else None
      ),
      "source": self.source,
      "quality": self.quality,
      "candidate_price": (
        float(self.candidate_price) if self.candidate_price is not None else None
      ),
      "deviation_pct": self.deviation_pct,
      "ok": self.ok,
      "reason": self.reason,
    }


def _dec(value: Any) -> Decimal | None:
  if value is None or value == "":
    return None
  try:
    return Decimal(str(value))
  except Exception:  # noqa: BLE001
    return None


def _deviation_pct(candidate: Decimal, canonical: Decimal) -> float | None:
  if canonical <= 0:
    return None
  return float(abs(candidate - canonical) / canonical * Decimal("100"))


def resolve_canonical_entry_price(
  session: Session,
  *,
  symbol: str,
  detected_at: datetime,
  candidate_price: Decimal | float | None,
  max_candidate_deviation_pct: float = DEFAULT_MAX_CANDIDATE_DEVIATION_PCT,
) -> EntryPriceResolution:
  """detected_at 분봉 close 를 canonical entry 로 사용.

  DB candle 없으면 candidate 폴백(quality=CANDIDATE_FALLBACK_NO_DB).
  candidate 가 DB 대비 max_candidate_deviation_pct 초과면 DB 우선.
  """

  detected = as_utc(detected_at)
  candle_start = floor_minute(detected)
  candidate = _dec(candidate_price)

  bars = list_minute_bars_db(
    session,
    symbol=str(symbol).upper(),
    start_at=candle_start,
    end_at=candle_start,
    timeframe=1,
  )
  candle_close: Decimal | None = None
  candle_at: datetime | None = None
  if bars:
    bar = bars[0]
    candle_at = as_utc(bar.candle_at)
    candle_close = bar.close

  if candle_close is not None and candle_close > 0:
    if candidate is not None and candidate > 0:
      dev = _deviation_pct(candidate, candle_close)
      if dev is not None and dev <= float(max_candidate_deviation_pct):
        return EntryPriceResolution(
          price=candidate,
          detected_at=detected,
          candle_at=candle_at,
          source=SOURCE_DB_DETECTED_CANDLE,
          quality=QUALITY_CANDIDATE_MATCH,
          candidate_price=candidate,
          deviation_pct=dev,
          ok=True,
        )
      # stale / API-DB mismatch → DB canonical
      return EntryPriceResolution(
        price=candle_close,
        detected_at=detected,
        candle_at=candle_at,
        source=SOURCE_DB_DETECTED_CANDLE,
        quality=QUALITY_CANDIDATE_REJECTED,
        candidate_price=candidate,
        deviation_pct=dev,
        ok=True,
        reason="CANDIDATE_DEVIATION_EXCEEDED",
      )
    return EntryPriceResolution(
      price=candle_close,
      detected_at=detected,
      candle_at=candle_at,
      source=SOURCE_DB_DETECTED_CANDLE,
      quality=QUALITY_CANONICAL,
      candidate_price=candidate,
      deviation_pct=None,
      ok=True,
    )

  if candidate is not None and candidate > 0:
    return EntryPriceResolution(
      price=candidate,
      detected_at=detected,
      candle_at=None,
      source=SOURCE_CANDIDATE_SCANNER,
      quality=QUALITY_CANDIDATE_FALLBACK,
      candidate_price=candidate,
      deviation_pct=None,
      ok=True,
      reason="NO_DB_CANDLE_AT_DETECTED",
    )

  return EntryPriceResolution(
    price=Decimal("0"),
    detected_at=detected,
    candle_at=None,
    source=SOURCE_CANDIDATE_SCANNER,
    quality=QUALITY_CANDIDATE_FALLBACK,
    candidate_price=None,
    deviation_pct=None,
    ok=False,
    reason="NO_ENTRY_PRICE",
  )


def assess_stored_entry_price_quality(
  session: Session,
  *,
  symbol: str,
  detected_at: datetime,
  stored_entry_price: Decimal | float,
  max_deviation_pct: float = DEFAULT_MAX_CANDIDATE_DEVIATION_PCT,
) -> dict[str, Any]:
  """기존 row 분석용 — stored entry vs DB candle (UPDATE 금지)."""

  stored = _dec(stored_entry_price)
  if stored is None or stored <= 0:
    return {
      "flag": "INVALID_PRICE_SOURCE",
      "reason": "NO_STORED_PRICE",
    }

  resolved = resolve_canonical_entry_price(
    session,
    symbol=symbol,
    detected_at=detected_at,
    candidate_price=stored,
    max_candidate_deviation_pct=max_deviation_pct,
  )
  if not resolved.ok or resolved.candle_at is None:
    return {
      "flag": "UNKNOWN",
      "stored_entry_price": float(stored),
      "reason": resolved.reason,
    }

  dev = resolved.deviation_pct
  if dev is not None and dev > float(max_deviation_pct):
    return {
      "flag": "INVALID_PRICE_SOURCE",
      "stored_entry_price": float(stored),
      "canonical_candle_close": float(resolved.price),
      "candle_at": as_utc(resolved.candle_at).isoformat(),
      "deviation_pct": dev,
      "reason": "STORED_ENTRY_DEVIATES_FROM_DB_CANDLE",
    }

  return {
    "flag": "VALID",
    "stored_entry_price": float(stored),
    "canonical_candle_close": float(resolved.price),
    "candle_at": as_utc(resolved.candle_at).isoformat(),
    "deviation_pct": dev,
  }
