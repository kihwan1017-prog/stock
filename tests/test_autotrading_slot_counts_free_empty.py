"""후보 슬롯 free_count는 EMPTY 기준 (하드코딩 capacity 금지)."""

from __future__ import annotations

from unittest.mock import MagicMock

from stock_platform.trading.autotrading_health_service import _slot_counts


def test_slot_counts_free_equals_empty_not_hardcoded_five() -> None:
    session = MagicMock()
    # OPEN0 + WAITING9 + EMPTY1 → free=1 (옛 로직이면 max(0,5-9)=0 오탐)
    rows = [
        {"status": "WAITING_SIGNAL", "n": 9},
        {"status": "EMPTY", "n": 1},
    ]
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session.execute.return_value = result

    out = _slot_counts(session, uba_id=1380)
    assert out["waiting_count"] == 9
    assert out["empty_count"] == 1
    assert out["open_count"] == 0
    assert out["free_slot_count"] == 1
