# -*- coding: utf-8 -*-
"""WRK-014 durable exit intent — focused unit tests (no broker/LIVE)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_exit_intent.constants import (
    DEFAULT_MAX_RETRIES,
    STATUS_COMPLETED,
    STATUS_CONDITION_CLEARED,
    STATUS_COOLDOWN,
    STATUS_EXHAUSTED,
    STATUS_ORDER_PENDING,
)
from stock_platform.operation.upbit_exit_intent.entities import (
    UpbitExitIntentEntity,
)
from stock_platform.operation.upbit_exit_intent.service import (
    UpbitExitIntentService,
)


def _row(**kwargs) -> UpbitExitIntentEntity:
    now = datetime.now(timezone.utc)
    base = dict(
        exit_intent_id=1,
        user_broker_account_id=1380,
        symbol="KRW-ADA",
        exit_reason="MA_DEAD_CROSS",
        status="CONFIRMED",
        retry_count=0,
        max_retry_count=DEFAULT_MAX_RETRIES,
        initial_confirmed_at=now,
        detail_json={},
        event_log_json=[],
        created_at=now,
        updated_at=now,
    )
    base.update(kwargs)
    ent = UpbitExitIntentEntity()
    for k, v in base.items():
        setattr(ent, k, v)
    return ent


def test_create_idempotent_active(session_mock: MagicMock | None = None) -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    existing = _row(status="ORDER_PENDING")
    with patch.object(svc, "get_active", return_value=existing):
        out = svc.create_on_confirmed(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            signal_id="sig1",
        )
    assert out is existing
    session.add.assert_not_called()


def test_link_order_initial_does_not_increment_retry() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(status="CONFIRMED", retry_count=0)
    with patch.object(svc, "get_by_id", return_value=row):
        out = svc.link_order(exit_intent_id=1, order_id=100, is_retry=False)
    assert out is not None
    assert out.retry_count == 0
    assert out.initial_order_id == 100
    assert out.status == STATUS_ORDER_PENDING


def test_link_order_retry_increments() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(status="COOLDOWN", retry_count=0, initial_order_id=100)
    with patch.object(svc, "get_by_id", return_value=row):
        out = svc.link_order(exit_intent_id=1, order_id=101, is_retry=True)
    assert out is not None
    assert out.retry_count == 1
    assert out.last_order_id == 101


def test_zero_fill_cancel_sets_cooldown() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_ORDER_PENDING,
        initial_order_id=1926,
        last_order_id=1926,
    )
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "_broker_qty", return_value=Decimal("33.3")),
    ):
        out = svc.on_terminal_sell_cancel(
            order_id=1926,
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            filled_quantity=Decimal("0"),
        )
    assert out is not None
    assert out.status == STATUS_COOLDOWN
    assert out.next_retry_at is not None
    assert out.retry_count == 0  # not incremented until retry order


def test_prepare_retry_waits_before_cooldown() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_COOLDOWN,
        next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        initial_order_id=1,
        last_order_id=1,
        retry_count=0,
    )
    with patch.object(svc, "get_active", return_value=row):
        out = svc.prepare_retry_or_none(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            short_ma=Decimal("99"),
            long_ma=Decimal("100"),
        )
    assert out["action"] == "wait"


def test_prepare_retry_condition_cleared() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_COOLDOWN,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        initial_order_id=1,
        last_order_id=1,
        retry_count=0,
    )
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "_broker_qty", return_value=Decimal("10")),
        patch.object(svc, "_has_open_sell", return_value=False),
        patch.object(
            svc,
            "state_condition_still_true",
            return_value=(False, {"confirmed": False}),
        ),
    ):
        out = svc.prepare_retry_or_none(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            short_ma=Decimal("101"),
            long_ma=Decimal("100"),
        )
    assert out["action"] == "cleared"
    assert row.status == STATUS_CONDITION_CLEARED


def test_prepare_retry_emit_when_due_and_true() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_COOLDOWN,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        initial_order_id=1,
        last_order_id=1,
        retry_count=1,
        max_retry_count=3,
    )
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "_broker_qty", return_value=Decimal("6")),
        patch.object(svc, "_has_open_sell", return_value=False),
        patch.object(
            svc,
            "state_condition_still_true",
            return_value=(True, {"confirmed": True}),
        ),
    ):
        out = svc.prepare_retry_or_none(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            short_ma=Decimal("99"),
            long_ma=Decimal("100"),
        )
    assert out["action"] == "emit_retry"
    assert out["remaining_quantity"] == "6"


def test_prepare_retry_blocked_open_sell() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_COOLDOWN,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        initial_order_id=1,
        last_order_id=1,
        retry_count=0,
    )
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "_broker_qty", return_value=Decimal("10")),
        patch.object(svc, "_has_open_sell", return_value=True),
    ):
        out = svc.prepare_retry_or_none(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            short_ma=Decimal("99"),
            long_ma=Decimal("100"),
        )
    assert out["action"] == "blocked_open_sell"


def test_prepare_retry_exhausted_at_max() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_COOLDOWN,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        initial_order_id=1,
        last_order_id=1,
        retry_count=3,
        max_retry_count=3,
    )
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "_broker_qty", return_value=Decimal("10")),
        patch.object(svc, "_has_open_sell", return_value=False),
        patch.object(
            svc,
            "state_condition_still_true",
            return_value=(True, {"confirmed": True}),
        ),
        patch.object(svc, "_notify_exhausted"),
    ):
        out = svc.prepare_retry_or_none(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            short_ma=Decimal("99"),
            long_ma=Decimal("100"),
        )
    assert out["action"] == "exhausted"
    assert row.status == STATUS_EXHAUSTED


def test_qty_zero_completes() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    row = _row(
        status=STATUS_COOLDOWN,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        initial_order_id=1,
    )
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "_broker_qty", return_value=Decimal("0")),
    ):
        out = svc.prepare_retry_or_none(
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            short_ma=Decimal("99"),
            long_ma=Decimal("100"),
        )
    assert out["action"] == "completed"
    assert row.status == STATUS_COMPLETED


def test_no_historical_backfill_on_cancel_without_active() -> None:
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    with patch.object(svc, "get_active", return_value=None):
        out = svc.on_terminal_sell_cancel(
            order_id=1926,
            user_broker_account_id=1380,
            symbol="KRW-ADA",
            filled_quantity=Decimal("0"),
        )
    assert out is None


def test_retry4_not_emitted_semantics() -> None:
    """Max retries=3 → after retry_count=3 exhausted; no 4th."""

    assert DEFAULT_MAX_RETRIES == 3
    # total attempts = 1 initial + 3 retries = 4
    max_total = 1 + DEFAULT_MAX_RETRIES
    assert max_total == 4


def test_why_still_holding_labels() -> None:
    row = _row(status=STATUS_COOLDOWN, retry_count=1, max_retry_count=3)
    text = UpbitExitIntentService.why_still_holding_ko(row)
    assert "재시도" in text
    exh = _row(status=STATUS_EXHAUSTED, retry_count=3, max_retry_count=3)
    assert "한도" in UpbitExitIntentService.why_still_holding_ko(exh)
