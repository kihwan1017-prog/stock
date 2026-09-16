"""STEP 8-5-9 — Scope 인식 Strategy Signal."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategySignal:
    signal_id: str
    fingerprint: str
    scope_key: str
    user_id: int
    account_kind: str
    account_id: int
    strategy_id: int
    strategy_version: str
    broker_code: str
    market_type: str
    symbol: str
    signal_type: str
    generated_at: datetime
    event_time: datetime
    reference_price: Decimal
    confidence: float | None = None
    reason_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def build_id(*, scope_key: str, symbol: str) -> str:
        return (
            f"sig_{uuid.uuid4().hex[:16]}_"
            f"{hashlib.sha256((scope_key + '|' + symbol).encode()).hexdigest()[:8]}"
        )

    @staticmethod
    def build_fingerprint(
        *,
        scope_key: str,
        symbol: str,
        signal_type: str,
        reason_code: str,
        event_time: datetime,
        sequence: int | None = None,
        opportunity_id: str | None = None,
    ) -> str:
        # opportunity_id: portfolio selection/waiting 등 natural opportunity 구분
        # (symbol+event_time만 쓰면 새 selection 첫 PASS가 잘못 suppress될 수 있음)
        raw = "|".join(
            [
                scope_key,
                symbol.upper(),
                signal_type,
                reason_code,
                event_time.astimezone(timezone.utc).isoformat(),
                str(sequence if sequence is not None else ""),
                str(opportunity_id or ""),
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
