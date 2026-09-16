"""PAPER SHADOW observer — isolated. PROD DB/주문 없음."""

from __future__ import annotations

import os

import pytest

from stock_platform.operation.paper_shadow_observer.dry_pipeline import (
    dry_ai_gate,
    dry_risk,
    observe_one,
)
from stock_platform.operation.paper_shadow_observer.guard import (
    ShadowOrderIsolationError,
    blocked_broker_order,
    blocked_create_order,
    blocked_enqueue_outbox,
    blocked_submit_order,
)
from stock_platform.operation.paper_shadow_observer.quality import classify_quality
from stock_platform.operation.paper_shadow_observer.store import redact


def test_order_paths_are_blocked() -> None:
    with pytest.raises(ShadowOrderIsolationError):
        blocked_submit_order()
    with pytest.raises(ShadowOrderIsolationError):
        blocked_create_order()
    with pytest.raises(ShadowOrderIsolationError):
        blocked_enqueue_outbox()
    with pytest.raises(ShadowOrderIsolationError):
        blocked_broker_order()


def test_risk_deny_preserves_no_entry() -> None:
    trading = {"ok": True, "recommendation": "ALLOW", "confidence": 0.8}
    gate = dry_ai_gate(trading)
    assert gate["decision"] == "ALLOW"
    risk = dry_risk(gate=gate, trading=trading, extra={"kill_switch": True})
    assert risk["decision"] == "DENY"
    assert risk["final_entry"] == "ENTRY_NOT_ALLOWED"


def test_trading_allow_gate_allow_risk_deny() -> None:
    trading = {"ok": True, "recommendation": "ALLOW", "confidence": 0.9}
    gate = dry_ai_gate(trading)
    risk = dry_risk(gate=gate, trading=trading, extra={"risk_exceeded": True})
    assert gate["decision"] == "ALLOW"
    assert risk["final_entry"] == "ENTRY_NOT_ALLOWED"


def test_fail_closed_does_not_allow(monkeypatch) -> None:
    def boom(_inp, _symbol):
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
    assert record["outbox_created"] == 0
    assert record["broker_order_call"] == 0
    assert record["fallback"] is True


def test_secret_redaction() -> None:
    payload = redact({
        "symbol": "KRW-BTC",
        "api_key": "should-not-store",
        "vault_token": "nope",
        "nested": {"password": "x", "tone": "BULLISH"},
    })
    assert payload["api_key"] == "REDACTED"
    assert payload["vault_token"] == "REDACTED"
    assert payload["nested"]["password"] == "REDACTED"
    assert payload["nested"]["tone"] == "BULLISH"


def test_usdt_quality_is_telemetry_not_hard_block() -> None:
    quality = classify_quality(
        symbol="KRW-USDT",
        change_rate=0.001,
        range_pct=0.002,
        fee_churn_risk="HIGH",
        recommendation="ALLOW",
    )
    assert quality["stable_or_pegged_asset"] is True
    assert quality["low_volatility_allow"] is True
    assert quality["blocked_by_hardcode"] is False


def test_jsonl_rotation_and_stale_pid(tmp_path, monkeypatch) -> None:
    from stock_platform.operation.paper_shadow_observer.store import rotate_jsonl_if_needed
    from stock_platform.operation.paper_shadow_observer.runner import (
        acquire_pid_file,
        pid_is_alive,
    )

    target = tmp_path / "observations.jsonl"
    target.write_bytes(b"x" * 100)
    assert rotate_jsonl_if_needed(target, max_bytes=50, keep=2) is True
    assert (tmp_path / "observations.jsonl.1").is_file()
    assert pid_is_alive(os.getpid()) is True
    stale = tmp_path / "obs.pid"
    stale.write_text("999999", encoding="utf-8")
    assert acquire_pid_file(stale) is True
    live = tmp_path / "live.pid"
    live.write_text(str(os.getpid()), encoding="utf-8")
    assert acquire_pid_file(live) is False


def test_observe_success_never_creates_orders() -> None:
    record = observe_one(
        {
            "market": "KRW-ETH",
            "trade_price": 4000,
            "signed_change_rate": 0.04,
            "high_price": 4200,
            "low_price": 3900,
            "acc_trade_price_24h": 1e10,
        },
        run_analysis=lambda _i, _s: {
            "ok": True,
            "tone": "BULLISH",
            "confidence": 0.7,
            "market_summary": "상승",
            "asset_summary": "ETH",
        },
        run_trading=lambda _i, _a: {
            "ok": True,
            "recommendation": "ALLOW",
            "confidence": 0.72,
            "reason_codes": ["TREND"],
            "risk_flags": [],
            "reason_ko": "추세 정합",
            "fee_churn_risk": "LOW",
            "affects_real": False,
            "model": "qwen3.5:4b",
        },
    )
    assert record["trading_recommendation"] == "ALLOW"
    assert record["ai_gate"]["decision"] == "ALLOW"
    assert record["risk_dry"]["decision"] == "ALLOW"
    assert record["final_entry"] == "ENTRY_NOT_SUBMITTED"
    assert record["order_created"] == 0
    assert record["outbox_created"] == 0
    assert record["broker_order_call"] == 0
    assert record["affects_real"] is False
