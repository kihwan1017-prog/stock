"""Kiwoom MARKET_HOURS ARM auto-renew — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    CONFIRM_ENABLE,
    CONFIRM_ENABLE_MARKET_HOURS,
    MODE_HOURS_24,
    MODE_MARKET_HOURS,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)
from stock_platform.trading.market_hours_authorization import (
    krx_market_hours_state,
)


class _FakeRow:
    def __init__(self, **kwargs: Any) -> None:
        self.live_unattended_authorization_id = 1
        self.user_broker_account_id = 1381
        self.broker_code = "KIWOOM"
        self.status_code = "ACTIVE"
        self.enabled = True
        self.entry_authorized = True
        self.protective_exit_authorized = True
        self.auto_renew_enabled = True
        self.authorized_until = datetime.now(timezone.utc) + timedelta(hours=2)
        self.renewal_interval_seconds = 3600
        self.renewal_margin_seconds = 600
        self.arm_lease_ttl_seconds = 3600
        self.activation_renew_hours = 8
        self.max_authorization_horizon_hours = 8
        self.last_renewed_at = None
        self.last_renewal_actor = None
        self.last_renewal_detail = {
            "authorization_mode": MODE_MARKET_HOURS,
        }
        self.source_activation_id = 20
        self.approved_by = "admin"
        self.approved_at = datetime.now(timezone.utc)
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_authorization_mode_from_detail_and_broker() -> None:
    kiwoom = _FakeRow()
    assert (
        LiveUnattendedAuthorizationService._authorization_mode(kiwoom)
        == MODE_MARKET_HOURS
    )
    upbit = _FakeRow(
        broker_code="UPBIT",
        last_renewal_detail={"authorization_mode": MODE_HOURS_24},
    )
    assert (
        LiveUnattendedAuthorizationService._authorization_mode(upbit)
        == MODE_HOURS_24
    )
    # broker fallback when mode missing
    bare = _FakeRow(broker_code="KIWOOM", last_renewal_detail={})
    assert (
        LiveUnattendedAuthorizationService._authorization_mode(bare)
        == MODE_MARKET_HOURS
    )


def test_preserve_mode_detail_keeps_authorization_mode() -> None:
    row = _FakeRow()
    out = LiveUnattendedAuthorizationService._preserve_mode_detail(
        row, {"arm_renewed": True}
    )
    assert out["authorization_mode"] == MODE_MARKET_HOURS
    assert out["arm_renewed"] is True


def test_enable_rejects_wrong_confirm_for_market_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        trading_paused=False,
    )
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1381,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,  # 24H phrase — wrong
            reason="test",
            authorization_mode=MODE_MARKET_HOURS,
        )
    assert exc.value.code == "CONFIRMATION_REQUIRED"


def test_enable_rejects_upbit_for_market_hours() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        is_active=True,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE_MARKET_HOURS,
            reason="test",
            authorization_mode=MODE_MARKET_HOURS,
        )
    assert exc.value.code == "BROKER_NOT_SUPPORTED"


def test_horizon_auto_renew_skipped_for_market_hours() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    row = _FakeRow(auto_renew_enabled=True)
    uba = SimpleNamespace(broker_code="KIWOOM", user_id=61)
    result = svc._try_horizon_auto_renew(row, uba, actor="TEST")
    assert result["horizon_renewed"] is False
    assert result["reason"] == "MARKET_HOURS_NO_HORIZON_ROLL"


def test_renew_due_no_active_lease() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    monkey_get = MagicMock(return_value=None)
    svc.get_active = monkey_get  # type: ignore[method-assign]
    assert svc.renew_due_for_uba(1381) == {
        "renewed": False,
        "reason": "NO_ACTIVE_LEASE",
    }


def test_renew_due_market_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    row = _FakeRow()
    svc.get_active = MagicMock(return_value=row)  # type: ignore[method-assign]
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        "stock_platform.trading.market_hours_authorization.krx_market_hours_state",
        lambda *_a, **_k: {
            "in_regular_session": False,
            "past_close": True,
            "is_trading_day": True,
        },
    )
    expired: list[str] = []

    def _expire(r, *, actor, reason):  # noqa: ANN001
        expired.append(reason)

    svc._expire_authorization = _expire  # type: ignore[method-assign]
    svc._emit_market_hours_renew_telegram = MagicMock()  # type: ignore[method-assign]
    result = svc.renew_due_for_uba(1381)
    assert result["reason"] == "MARKET_CLOSED"
    assert "MARKET_HOURS_SESSION_ENDED" in expired


def test_renew_due_not_due_outside_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    row = _FakeRow(renewal_margin_seconds=600)
    svc.get_active = MagicMock(return_value=row)  # type: ignore[method-assign]
    far = datetime.now(timezone.utc) + timedelta(hours=2)
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=far,
    )
    monkeypatch.setattr(
        "stock_platform.trading.market_hours_authorization.krx_market_hours_state",
        lambda *_a, **_k: {
            "in_regular_session": True,
            "past_close": False,
            "is_trading_day": True,
        },
    )
    svc.evaluate_renewal_gates = MagicMock(  # type: ignore[method-assign]
        return_value={"ok": True, "blockers": [], "checks": {}}
    )
    monkeypatch.setattr(
        "stock_platform.broker.live_transition_service.LiveTradingTransitionService.peek_active",
        lambda *a, **k: None,
    )
    result = svc.renew_due_for_uba(1381)
    assert result["reason"] == "NOT_DUE"


def test_phrase_meta_market_hours() -> None:
    meta = LiveUnattendedAuthorizationService._required_phrase_meta(
        "KIWOOM", authorization_mode=MODE_MARKET_HOURS
    )
    assert meta["required_confirmation_text"] == CONFIRM_ENABLE_MARKET_HOURS
    assert meta["authorization_mode"] == MODE_MARKET_HOURS


def test_krx_market_hours_state_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dec:
        is_trading_day = True
        session_type = "REGULAR"
        reason_code = "OK"
        regular_open_at = __import__("datetime").time(9, 0)
        regular_close_at = __import__("datetime").time(15, 30)

    monkeypatch.setattr(
        "stock_platform.operation.calendar_service.TradingCalendarService.evaluate",
        lambda self, **kw: _Dec(),
    )
    # 장중 시각 고정
    noon = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)  # 13:00 KST
    state = krx_market_hours_state(MagicMock(), now=noon)
    assert state["is_trading_day"] is True
    assert state["in_regular_session"] is True
    assert state["regular_close_at"] == "15:30"
