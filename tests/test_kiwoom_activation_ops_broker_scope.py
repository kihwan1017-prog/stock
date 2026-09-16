"""KIWOOM activation SoT must not hardcode UPBIT broker_code."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.trading.upbit_24x7_control import (
    _activation_active,
    runtime_status_for_uba,
)
from stock_platform.strategy_deployment.runtime_scope import RuntimeLifecycleStatus


def test_activation_active_uses_uba_broker(monkeypatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        broker_code="KIWOOM", user_broker_account_id=1381
    )
    session.get.return_value = uba
    captured: dict = {}

    class _Svc:
        def __init__(self, _s):
            pass

        def peek_active(self, *, broker_code, user_broker_account_id):
            captured["broker_code"] = broker_code
            captured["uba"] = user_broker_account_id
            return SimpleNamespace(
                activation_status="ACTIVE",
                live_trading_transition_id=73,
            )

    monkeypatch.setattr(
        "stock_platform.broker.live_transition_service.LiveTradingTransitionService",
        _Svc,
    )
    out = _activation_active(session, 1381)
    assert out["ok"] is True
    assert captured["broker_code"] == "KIWOOM"
    assert out["broker_code"] == "KIWOOM"
    assert out["transition_id"] == 73


def test_runtime_status_for_uba_respects_broker(monkeypatch) -> None:
    class _Entry:
        def __init__(self, broker, status):
            self.scope = SimpleNamespace(broker_code=broker, scope_key=f"k-{broker}")
            self.status = status
            self.last_error = None
            self.last_heartbeat_at = None

        def as_dict(self):
            return {"broker": self.scope.broker_code, "status": self.status.value}

    class _Mgr:
        def list_entries(self, **_k):
            return [
                _Entry("UPBIT", RuntimeLifecycleStatus.STOPPED),
                _Entry("KIWOOM", RuntimeLifecycleStatus.RUNNING),
            ]

    monkeypatch.setattr(
        "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager",
        _Mgr(),
    )
    st = runtime_status_for_uba(
        user_broker_account_id=1381, broker_code="KIWOOM"
    )
    assert st["status"] == "RUNNING"
    assert st["broker_code"] == "KIWOOM"
    assert len(st["entries"]) == 1
