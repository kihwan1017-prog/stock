# -*- coding: utf-8 -*-
"""Long-hold checkpoint helpers (observability only)."""

from __future__ import annotations

from typing import Any

# 6h, 12h, 24h, then every +24h
BASE_CHECKPOINTS_HOURS = (6, 12, 24)
REPEAT_AFTER_HOURS = 24


def select_latest_checkpoint(hold_seconds: float | int | None) -> str | None:
    """이미 지난 checkpoint 중 최신 1개만.

    40h → 24H (6/12/24를 한꺼번에 보내지 않음).
    """

    if hold_seconds is None:
        return None
    try:
        hours = float(hold_seconds) / 3600.0
    except (TypeError, ValueError):
        return None
    if hours < BASE_CHECKPOINTS_HOURS[0]:
        return None
    reached: list[int] = []
    for h in BASE_CHECKPOINTS_HOURS:
        if hours + 1e-9 >= h:
            reached.append(h)
    # 24h 이후 48, 72, ...
    h = REPEAT_AFTER_HOURS * 2  # 48
    while hours + 1e-9 >= h:
        reached.append(h)
        h += REPEAT_AFTER_HOURS
    if not reached:
        return None
    return f"{reached[-1]}H"


def long_hold_badge(hold_seconds: float | int | None) -> dict[str, Any] | None:
    """Admin UI badge — Time Exit과 혼동 금지."""

    cp = select_latest_checkpoint(hold_seconds)
    if cp is None:
        return None
    hours = int(cp.replace("H", ""))
    if hours >= 24:
        label = "24h+ 장기보유"
        level = "long"
    elif hours >= 12:
        label = "12h+ 경고"
        level = "warn"
    else:
        label = "6h+ 주의"
        level = "caution"
    return {
        "checkpoint": cp,
        "label": label,
        "level": level,
        "tooltip": "장기보유 감시 기준이며 자동 청산 기준이 아닙니다.",
    }


def dedupe_key(*, position_id: int | str, checkpoint: str) -> str:
    return f"LONG_HOLD:{position_id}:{checkpoint}"
