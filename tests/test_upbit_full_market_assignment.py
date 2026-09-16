"""FULL_MARKET assignment service — SQLite/memory friendly unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    CONFIRM_ENABLE_FULL_MARKET,
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_AUTO,
    STATE_IDLE,
)
from stock_platform.operation.upbit_full_market.service import (
    UpbitFullMarketAssignmentService,
)


class _FakeAssignment:
    def __init__(self) -> None:
        self.assignment_id = 1
        self.user_broker_account_id = 1380
        self.broker_code = "UPBIT"
        self.strategy_id = 17483
        self.deployment_id = 868
        self.mode = MODE_FIXED_SYMBOL
        self.state = STATE_IDLE
        self.template_symbol = "KRW-XRP"
        self.current_symbol = "KRW-XRP"
        self.active_selection_id = None
        self.last_scanner_run_id = None
        self.ai_live_gate_mode = "ENFORCE"
        self.warmup_ready = False
        self.market_data_fresh = False
        self.signals_paused = False
        self.cooldown_until = None
        self.selection_lease_token = None
        self.selection_lease_until = None
        self.block_reason = None
        self.last_error = None
        self.policy_json = {}
        self.enabled_at = None
        self.enabled_by = None
        self.disabled_at = None
        self.disabled_by = None


def test_entry_allowed_fixed_delegates() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    svc = UpbitFullMarketAssignmentService(session)
    ok, reason = svc.entry_allowed(1380, symbol="KRW-XRP")
    assert ok is True
    assert reason == "FIXED_SYMBOL_DELEGATE"


def test_entry_blocked_when_warmup_incomplete() -> None:
    row = _FakeAssignment()
    row.mode = MODE_FULL_MARKET_AUTO
    row.warmup_ready = False
    row.market_data_fresh = True
    row.signals_paused = False
    session = MagicMock()
    session.scalar.return_value = row
    svc = UpbitFullMarketAssignmentService(session)
    # has_open_strategy_position도 scalar 사용 — 두 번째 호출 None
    session.scalar.side_effect = [row, None]
    ok, reason = svc.entry_allowed(1380, symbol="KRW-ETH")
    assert ok is False
    assert reason == "WARMUP_INCOMPLETE"


def test_enable_requires_confirmation() -> None:
    session = MagicMock()
    uba = SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    session.get.return_value = uba
    row = _FakeAssignment()
    session.scalar.return_value = row
    svc = UpbitFullMarketAssignmentService(session)
    bad = svc.enable_full_market(
        1380,
        confirmation_text="wrong",
        actor="admin",
    )
    assert bad["ok"] is False
    assert bad["error"] == "CONFIRMATION_MISMATCH"

    good = svc.enable_full_market(
        1380,
        confirmation_text=CONFIRM_ENABLE_FULL_MARKET,
        actor="admin",
        strategy_id=17483,
        deployment_id=868,
        template_symbol="KRW-XRP",
    )
    assert good["ok"] is True
    assert row.mode == MODE_FULL_MARKET_AUTO


def test_kiwoom_uba_rejected() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="KIWOOM")
    svc = UpbitFullMarketAssignmentService(session)
    out = svc.enable_full_market(
        1381,
        confirmation_text=CONFIRM_ENABLE_FULL_MARKET,
        actor="admin",
    )
    assert out["ok"] is False
    assert out["error"] == "BROKER_NOT_UPBIT"


def test_dry_consume_fixed_mode_no_select() -> None:
    row = _FakeAssignment()
    session = MagicMock()
    session.scalar.return_value = row
    svc = UpbitFullMarketAssignmentService(session)
    out = svc.consume_scanner_candidates(
        1380,
        candidates=[
            {
                "symbol": "KRW-ETH",
                "rank": 1,
                "recommendation": "ALLOW",
                "score": 9,
                "confidence": 0.9,
                "trade_value_24h": 1e10,
                "market_data_timestamp": datetime.now(timezone.utc),
            }
        ],
        scanner_run_id="run1",
        dry_run=True,
    )
    assert out["ok"] is False
    assert out["reason"] == "MODE_FIXED_SYMBOL"
    assert out["orders_created"] == 0
