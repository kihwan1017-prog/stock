# -*- coding: utf-8 -*-
"""Activation continuity within auth horizon — unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.activation_horizon_alignment import (
    compute_horizon_activation_refresh_hours,
    projected_successor_expires_at,
)
from stock_platform.trading.live_unattended_authorization_service import (
    LiveUnattendedAuthorizationService,
    STATUS_ACTIVE,
)


def test_activation_never_beyond_auth_horizon() -> None:
    now = datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)
    auth_until = datetime(2026, 9, 7, 22, 55, tzinfo=timezone.utc)  # earlier than now+8h
    # use auth still in future
    auth_until = now + timedelta(hours=4)
    projected = projected_successor_expires_at(
        now=now, renew_hours=8, authorized_until=auth_until
    )
    assert projected <= auth_until
    hours = compute_horizon_activation_refresh_hours(
        authorized_until=auth_until,
        activation_renew_hours=8,
        now=now,
    )
    assert hours <= 4


def test_ensure_activation_continuity_blocks_kill() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    row = SimpleNamespace(
        user_broker_account_id=1380,
        authorized_until=datetime.now(timezone.utc) + timedelta(hours=5),
        status_code=STATUS_ACTIVE,
        enabled=True,
        activation_renew_hours=8,
        arm_lease_ttl_seconds=3600,
        renewal_margin_seconds=600,
        last_renewal_detail={},
    )
    uba = SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    with patch(
        "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
    ) as ks:
        ks.return_value.is_active_for_scopes.return_value = True
        out = svc.ensure_activation_continuity_within_auth(
            row, uba, actor="TEST"
        )
    assert out["refreshed"] is False
    assert out["reason"] == "KILL_SWITCH_ACTIVE"
