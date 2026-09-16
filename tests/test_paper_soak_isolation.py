"""PAPER/LIVE 격리 + fail-closed. PROD DB 없음."""

from __future__ import annotations

import pytest

from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.operation.paper_shadow_observer.dry_pipeline import (
    dry_ai_gate,
    dry_risk,
    observe_one,
)
from stock_platform.operation.paper_shadow_observer.guard import (
    ShadowOrderIsolationError,
    blocked_submit_order,
)
from stock_platform.order.outbox_adapter_resolver import resolve_outbox_adapter


def test_paper_env_uses_paper_adapter() -> None:
    adapter = BrokerAdapterFactory.create(BrokerEnvironment.PAPER, "PAPER")
    assert isinstance(adapter, PaperBrokerAdapter)


def test_paper_env_kiwoom_code_still_paper_adapter() -> None:
    adapter = BrokerAdapterFactory.create(BrokerEnvironment.PAPER, "KIWOOM")
    assert isinstance(adapter, PaperBrokerAdapter)


def test_outbox_paper_default_is_paper_adapter() -> None:
    adapter = resolve_outbox_adapter({"environment": "PAPER", "broker_code": "PAPER"})
    assert isinstance(adapter, PaperBrokerAdapter)


def test_live_factory_requires_global_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.common import settings as settings_mod

    fake = settings_mod.get_settings()
    monkeypatch.setattr(fake, "global_live_order_enabled", False)
    monkeypatch.setattr(settings_mod, "get_settings", lambda: fake)
    with pytest.raises(PermissionError, match="GLOBAL_LIVE_ORDER"):
        BrokerAdapterFactory.create(BrokerEnvironment.LIVE, "UPBIT", session=object())


def test_risk_deny_blocks_entry() -> None:
    trading = {"ok": True, "recommendation": "ALLOW", "confidence": 0.9}
    gate = dry_ai_gate(trading)
    risk = dry_risk(gate=gate, trading=trading, extra={"risk_exceeded": True})
    assert risk["decision"] == "DENY"
    assert risk["final_entry"] == "ENTRY_NOT_ALLOWED"


def test_llm_failure_fail_closed() -> None:
    def boom(*_a, **_k):
        raise TimeoutError("unreachable")

    record = observe_one(
        {"market": "KRW-BTC", "trade_price": 1000, "signed_change_rate": 0.02},
        run_analysis=boom,
        run_trading=lambda *_a, **_k: {"ok": False, "error": "malformed"},
    )
    assert record["trading_recommendation"] != "ALLOW"
    assert record["ai_gate"]["decision"] == "HOLD"
    assert record["risk_dry"]["final_entry"] == "ENTRY_NOT_ALLOWED"
    assert record["order_created"] == 0


def test_llm_cannot_submit_order() -> None:
    with pytest.raises(ShadowOrderIsolationError):
        blocked_submit_order()
