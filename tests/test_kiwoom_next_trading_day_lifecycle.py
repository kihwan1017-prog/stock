"""Kiwoom next-trading-day lifecycle — focused regression tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.kiwoom_trading_day_lifecycle import (
    CONFIRM_DISABLE_NEXT_DAY,
    CONFIRM_ENABLE_NEXT_DAY,
    PHASE_BLOCKED,
    PHASE_SAFE_IDLE,
    PHASE_TRADING,
    PHASE_WAITING_MARKET,
    KiwoomTradingDayLifecycleService,
)
from stock_platform.trading.live_unattended_authorization_service import (
    LiveUnattendedError,
    MODE_MARKET_HOURS,
)
from stock_platform.trading.kiwoom_entry_provenance import (
    BROKER_IMPORTED_POSITION,
    MISSING_LOCAL_BUY_HISTORY,
    classify_sell_entry_provenance,
)


class _FakeAuthRow:
    def __init__(self, **kwargs: Any) -> None:
        self.live_unattended_authorization_id = 99
        self.user_broker_account_id = 1381
        self.broker_code = "KIWOOM"
        self.status_code = "EXPIRED"
        self.enabled = False
        self.entry_authorized = False
        self.protective_exit_authorized = False
        self.auto_renew_enabled = True
        self.authorized_until = datetime.now(timezone.utc) - timedelta(hours=1)
        self.source_activation_id = 20
        self.last_renewal_detail = {
            "authorization_mode": MODE_MARKET_HOURS,
            "next_trading_day_auto_start": True,
        }
        self.updated_at = datetime.now(timezone.utc)
        for k, v in kwargs.items():
            setattr(self, k, v)


def _mh(
    *,
    trading: bool = True,
    in_session: bool = True,
    before: bool = False,
    past: bool = False,
) -> dict[str, Any]:
    return {
        "is_trading_day": trading,
        "in_regular_session": in_session,
        "before_open": before,
        "past_close": past,
        "calendar_date": "2026-08-25",
        "regular_close_at": "15:30",
        "regular_open_at_utc": "2026-08-25T00:00:00+00:00",
    }


def test_weekend_holiday_stays_safe_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    consent = _FakeAuthRow()
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    session.get.return_value = uba
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(trading=False, in_session=False),
    )
    out = svc.tick_uba(1381)
    assert out["phase"] == PHASE_SAFE_IDLE
    assert out["action"] == "WAIT_TRADING_DAY"


def test_before_open_waiting_market(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    consent = _FakeAuthRow()
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    session.get.return_value = uba
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(
            trading=True, in_session=False, before=True, past=False
        ),
    )
    out = svc.tick_uba(1381)
    assert out["phase"] == PHASE_WAITING_MARKET


def test_precheck_blocks_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        trading_paused=False,
    )
    session.get.return_value = uba
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: None)
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(),
    )
    monkeypatch.setattr(
        svc._unattended,
        "evaluate_restore_gates",
        lambda _id: {"ok": True, "blockers": [], "checks": {}},
    )
    with patch(
        "stock_platform.order.live_open_order_exposure.evaluate_live_open_order_exposure",
        return_value=SimpleNamespace(
            unknown_open_count=0,
            remote_unmapped_count=0,
            remote_state_ok=True,
            as_detail=lambda: {},
        ),
    ):
        out = svc.evaluate_auto_start_precheck(1381)
    assert out["ok"] is False
    assert "NEXT_DAY_OPT_IN_OFF" in out["blockers"]
    assert out["gate_count"] >= 10


def test_precheck_blocks_unknown_order(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        trading_paused=False,
    )
    session.get.return_value = uba
    consent = _FakeAuthRow()
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(),
    )
    monkeypatch.setattr(
        svc._unattended,
        "evaluate_restore_gates",
        lambda _id: {"ok": True, "blockers": [], "checks": {}},
    )
    with patch(
        "stock_platform.order.live_open_order_exposure.evaluate_live_open_order_exposure",
        return_value=SimpleNamespace(
            unknown_open_count=1,
            remote_unmapped_count=0,
            remote_state_ok=True,
            as_detail=lambda: {"unknown_open_orders": 1},
        ),
    ):
        # deployment link mock
        session.scalar.return_value = SimpleNamespace(
            strategy_id=17579, account_strategy_link_id=1
        )
        out = svc.evaluate_auto_start_precheck(1381)
    assert out["ok"] is False
    assert "UNKNOWN_ORDER" in out["blockers"]


def test_opt_in_confirm_phrase() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
    )
    consent = _FakeAuthRow(next_trading_day_auto_start=False)
    consent.last_renewal_detail = {
        "authorization_mode": MODE_MARKET_HOURS,
        "next_trading_day_auto_start": False,
    }
    session.get.return_value = uba
    svc = KiwoomTradingDayLifecycleService(session)
    with patch.object(svc, "get_latest_authorization", return_value=consent):
        with patch.object(
            svc,
            "status_dict",
            side_effect=lambda uba_id: {
                "next_trading_day_auto_start": bool(
                    consent.last_renewal_detail.get(
                        "next_trading_day_auto_start"
                    )
                ),
                "user_broker_account_id": uba_id,
            },
        ):
            with pytest.raises(LiveUnattendedError) as exc:
                svc.set_next_trading_day_auto_start(
                    1381,
                    enabled=True,
                    actor="admin",
                    confirmation_text="WRONG",
                )
            assert exc.value.code == "CONFIRMATION_REQUIRED"

            out = svc.set_next_trading_day_auto_start(
                1381,
                enabled=True,
                actor="admin",
                confirmation_text=CONFIRM_ENABLE_NEXT_DAY,
                reason="test",
            )
            assert (
                consent.last_renewal_detail["next_trading_day_auto_start"]
                is True
            )
            assert out["next_trading_day_auto_start"] is True

            svc.set_next_trading_day_auto_start(
                1381,
                enabled=False,
                actor="admin",
                confirmation_text=CONFIRM_DISABLE_NEXT_DAY,
            )
            assert (
                consent.last_renewal_detail["next_trading_day_auto_start"]
                is False
            )


def test_idempotent_trading_phase_schedules_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    consent = _FakeAuthRow()
    active = _FakeAuthRow(
        status_code="ACTIVE",
        enabled=True,
        entry_authorized=True,
        authorized_until=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    session.get.return_value = uba
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    monkeypatch.setattr(svc._unattended, "get_active", lambda _id: active)
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(),
    )
    scheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(
        svc,
        "_schedule_stack_restore",
        lambda uba_id, actor: scheduled.append({"uba": uba_id, "actor": actor})
        or {"scheduled": True},
    )
    out1 = svc.tick_uba(1381)
    out2 = svc.tick_uba(1381)
    assert out1["phase"] == PHASE_TRADING
    assert out2["phase"] == PHASE_TRADING
    assert out1["action"] == "ENSURE_STACK"
    assert len(scheduled) == 2  # idempotent ensure, no duplicate lease


def test_eod_past_close_safe_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    consent = _FakeAuthRow()
    session.get.return_value = uba
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    monkeypatch.setattr(svc._unattended, "get_active", lambda _id: None)
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(
            trading=True, in_session=False, before=False, past=True
        ),
    )
    out = svc.tick_uba(1381)
    assert out["phase"] == PHASE_SAFE_IDLE
    assert out["action"] == "EOD_IDLE"


def test_market_open_blocked_on_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    consent = _FakeAuthRow()
    session.get.return_value = uba
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    monkeypatch.setattr(svc._unattended, "get_active", lambda _id: None)
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(),
    )
    monkeypatch.setattr(
        svc,
        "evaluate_auto_start_precheck",
        lambda _id: {
            "ok": False,
            "blockers": ["KILL_SWITCH_ACTIVE"],
            "gate_count": 13,
        },
    )
    out = svc.tick_uba(1381)
    assert out["phase"] == PHASE_BLOCKED
    assert out["action"] == "FAIL_CLOSED"


def test_preserve_next_day_flag_on_mode_detail() -> None:
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    row = _FakeAuthRow()
    out = LiveUnattendedAuthorizationService._preserve_mode_detail(
        row, {"arm_renewed": True}
    )
    assert out["authorization_mode"] == MODE_MARKET_HOURS
    assert out["next_trading_day_auto_start"] is True
    assert out["arm_renewed"] is True


def test_provenance_classify_missing_buy() -> None:
    session = MagicMock()
    sell = SimpleNamespace(
        order_id=1822,
        side_code="SELL",
        symbol="034310",
        user_broker_account_id=1381,
        strategy_id=17579,
    )
    session.get.return_value = sell
    session.scalars.return_value.all.side_effect = [
        [],  # buys
        [],  # bindings
    ]
    out = classify_sell_entry_provenance(session, sell_order_id=1822)
    assert out["classification"] in {
        MISSING_LOCAL_BUY_HISTORY,
        BROKER_IMPORTED_POSITION,
    }
    assert out["historical_mutation_allowed"] is False


def test_fill_position_write_sell_uses_exit_order_id() -> None:
    """SELL fill은 entry_order_id=None, exit_order_id=order_id."""

    from decimal import Decimal

    from stock_platform.broker.kiwoom.fill_position_write import (
        apply_kiwoom_fill_position_write,
    )

    session = MagicMock()
    order = SimpleNamespace(
        user_broker_account_id=1381,
        order_id=1822,
        broker_code="KIWOOM",
        strategy_id=17579,
        strategy_deployment_id=869,
        symbol="034310",
        side_code="SELL",
    )
    event = SimpleNamespace(
        filled_quantity=Decimal("1"),
        quantity=Decimal("1"),
        fill_price=Decimal("12860"),
        price=Decimal("12860"),
        side="SELL",
        broker_order_id="B1",
    )
    captured: dict[str, Any] = {}

    class _Ledger:
        def apply_execution(self, **_kw: Any) -> dict[str, Any]:
            return {"applied": True}

    class _Risk:
        def ensure_binding_from_fill(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def compute_and_persist(self, **_kw: Any) -> None:
            return None

    with patch(
        "stock_platform.broker.kiwoom.fill_position_write.LiveFillLedgerService",
        return_value=_Ledger(),
    ), patch(
        "stock_platform.risk_engine.strategy_owned_risk_service.StrategyOwnedRiskService",
        return_value=_Risk(),
    ):
        apply_kiwoom_fill_position_write(
            session, order=order, event=event, commit=False
        )

    assert captured.get("entry_order_id") is None
    assert captured.get("exit_order_id") == 1822
    assert captured.get("side") == "SELL"


def test_overnight_start_schedules_account_sync_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    consent = _FakeAuthRow()
    session.get.return_value = uba
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    monkeypatch.setattr(svc._unattended, "get_active", lambda _id: None)
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(),
    )
    monkeypatch.setattr(
        svc,
        "evaluate_auto_start_precheck",
        lambda _id: {"ok": True, "blockers": [], "gate_count": 13},
    )
    scheduled: list[dict[str, Any]] = []
    monkeypatch.setattr(
        svc,
        "_schedule_auto_start_pipeline",
        lambda uba_id, actor, mode: scheduled.append(
            {"uba": uba_id, "mode": mode}
        )
        or {"scheduled": True, "pipeline": mode},
    )
    out = svc.tick_uba(1381)
    assert out["action"] == "PIPELINE_SCHEDULED"
    assert out["phase"] == "ACCOUNT_SYNC"
    assert scheduled[0]["mode"] == "OVERNIGHT_START"


def test_preview_marks_session_closed_as_expected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code="KIWOOM",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    session.get.return_value = uba
    consent = _FakeAuthRow()
    svc = KiwoomTradingDayLifecycleService(session)
    monkeypatch.setattr(svc, "get_latest_authorization", lambda _id: consent)
    monkeypatch.setattr(
        svc,
        "status_dict",
        lambda _id: {
            "next_trading_day_auto_start": True,
            "source_activation_id": 20,
            "live": False,
            "arm": False,
        },
    )
    monkeypatch.setattr(
        "stock_platform.trading.kiwoom_trading_day_lifecycle.krx_market_hours_state",
        lambda *_a, **_k: _mh(
            trading=True, in_session=False, before=False, past=True
        ),
    )
    monkeypatch.setattr(
        svc,
        "evaluate_auto_start_precheck",
        lambda _id: {
            "ok": False,
            "blockers": ["MARKET_SESSION_NOT_OPEN"],
            "gate_count": 13,
        },
    )

    class _Cal:
        def next_trading_day(self, **_kw: Any) -> Any:
            from datetime import date

            return date(2026, 8, 25)

        def evaluate(self, **_kw: Any) -> Any:
            from datetime import time as time_cls

            return SimpleNamespace(
                is_trading_day=True,
                holiday_name=None,
                regular_open_at=time_cls(9, 0),
                regular_close_at=time_cls(15, 30),
            )

    monkeypatch.setattr(
        "stock_platform.operation.calendar_service.TradingCalendarService",
        lambda *_a, **_k: _Cal(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.calendar_repository.TradingCalendarRepository",
        lambda *_a, **_k: MagicMock(),
    )
    out = svc.preview_next_session(1381)
    assert out["mutation"] is False
    assert out["greenfield_bypass"] is False
    assert out["successor_eligible"] is True
    assert "MARKET_SESSION_NOT_OPEN" in out["precheck"]["expected_until_open"]
    assert out["account_sync_at_start"] == "LIVE_KIWOOM_ACCOUNT_STATE_SYNC"
    assert out["next_session"]["next_trading_date"] == "2026-08-25"
