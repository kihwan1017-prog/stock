"""UPBIT managed-symbol reentry — WAITING false-positive + occupancy suppress."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.trading.symbol_ownership.constants import (
    SKIP_AUTO_ALREADY_MANAGED,
)
from stock_platform.trading.symbol_ownership.decision import (
    OwnershipFacts,
    decide_ownership,
)


def test_waiting_signal_not_terminal_managed_reject() -> None:
    d = decide_ownership(
        OwnershipFacts(auto_slot_active=True, auto_slot_occupies_entry=False)
    )
    assert d.entry_allowed is True
    assert d.entry_skip_reason is None


def test_open_slot_blocks_reentry() -> None:
    d = decide_ownership(
        OwnershipFacts(auto_slot_active=True, auto_slot_occupies_entry=True)
    )
    assert d.entry_allowed is False
    assert d.entry_skip_reason == SKIP_AUTO_ALREADY_MANAGED


def test_binding_blocks_even_without_occupying_slot() -> None:
    d = decide_ownership(
        OwnershipFacts(
            auto_binding_qty=Decimal("10"),
            auto_slot_active=False,
            auto_slot_occupies_entry=False,
        )
    )
    assert d.entry_allowed is False
    assert d.entry_skip_reason == SKIP_AUTO_ALREADY_MANAGED


def test_closed_free_allows_reentry() -> None:
    d = decide_ownership(OwnershipFacts())
    assert d.entry_allowed is True
    assert d.owner == "FREE"


def test_begin_entry_no_longer_ignores_already_managed() -> None:
    """소스 계약: blanket ignore 제거."""

    from pathlib import Path

    src = Path(
        "src/stock_platform/operation/upbit_full_market/portfolio_service.py"
    ).read_text(encoding="utf-8")
    assert 'skip_reason != "AUTO_SYMBOL_ALREADY_MANAGED"' not in src
    assert "SKIP_AUTO_ALREADY_MANAGED" in src


def test_live_safety_gate_still_present() -> None:
    from pathlib import Path

    src = Path(
        "src/stock_platform/order/live_safety_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "SymbolOwnershipService" in src
    assert "entry_gate" in src


def test_manual_holding_still_excluded() -> None:
    d = decide_ownership(OwnershipFacts(broker_position_qty=Decimal("1")))
    assert d.entry_allowed is False
    assert d.entry_skip_reason == "MANUAL_SYMBOL_EXCLUDED"
