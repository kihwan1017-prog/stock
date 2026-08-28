"""AUTO-only entry slot vs broker-all — research shadow only.

ENTRY SLOT ownership 과 ACCOUNT RISK exposure 를 분리한다.
Production max_positions / safety 정책은 변경하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class SlotCountMode(str, Enum):
    """슬롯 소비 모드."""

    BROKER_ALL = "BROKER_ALL"  # qty>0 전체 (production 동일)
    AUTO_ONLY = "AUTO_ONLY"  # AUTO open/pending 만 슬롯 소비


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """보유/대기 한 줄 (연구용)."""

    symbol: str
    quantity: float
    ownership: str  # AUTO | MANUAL | UNKNOWN
    is_pending_entry: bool = False


def count_entry_slots(
    holdings: Sequence[HoldingRow],
    *,
    mode: SlotCountMode,
) -> int:
    """엔트리 슬롯을 소비하는 포지션/대기 수."""

    n = 0
    for h in holdings:
        if h.is_pending_entry:
            if mode == SlotCountMode.AUTO_ONLY and h.ownership != "AUTO":
                continue
            n += 1
            continue
        if h.quantity <= 0:
            continue
        if mode == SlotCountMode.BROKER_ALL:
            n += 1
        elif h.ownership == "AUTO":
            n += 1
    return n


def account_risk_exposure_notional(
    holdings: Sequence[HoldingRow],
    *,
    mark_prices: dict[str, float],
) -> float:
    """MANUAL 포함 전체 account exposure (리스크). 슬롯과 무관."""

    total = 0.0
    for h in holdings:
        if h.quantity <= 0:
            continue
        px = float(mark_prices.get(h.symbol.upper(), 0.0) or 0.0)
        total += abs(float(h.quantity) * px)
    return total


def simulate_auto_only_admission(
    *,
    holdings: Sequence[HoldingRow],
    max_positions: int,
    candidate_is_auto: bool = True,
) -> dict[str, object]:
    """동일 max_positions 하에서 BROKER_ALL vs AUTO_ONLY 수락 여부 비교."""

    broker_used = count_entry_slots(holdings, mode=SlotCountMode.BROKER_ALL)
    auto_used = count_entry_slots(holdings, mode=SlotCountMode.AUTO_ONLY)
    broker_ok = broker_used < max_positions
    auto_ok = auto_used < max_positions and candidate_is_auto
    return {
        "max_positions": max_positions,
        "broker_all_slots_used": broker_used,
        "auto_only_slots_used": auto_used,
        "broker_all_would_admit": broker_ok,
        "auto_only_would_admit": auto_ok,
        "additional_opportunity": (not broker_ok) and auto_ok,
        "manual_still_in_risk_exposure": True,
        "real_policy_changed": False,
    }
