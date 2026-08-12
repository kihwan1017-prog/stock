"""UPBIT AI Signal Gate — Fail Closed focused tests (실주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.realtime.ai_signal_gate import (
    clear_ai_signal_gate_cache_for_tests,
    evaluate_ai_signal_gate,
)
from stock_platform.realtime.ai_signal_gate_models import AiSignalGateDecision
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


@pytest.fixture(autouse=True)
def _clear_gate_cache():
    clear_ai_signal_gate_cache_for_tests()
    yield
    clear_ai_signal_gate_cache_for_tests()


def _signal(**kwargs) -> RealtimeSignal:
    base = dict(
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("500"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="MA_CROSS_BUY",
        generated_at=datetime.now(timezone.utc),
        fingerprint="fp-xrp-1",
        broker_code="UPBIT",
    )
    base.update(kwargs)
    return RealtimeSignal(**base)


def _settings(**overrides):
    base = dict(
        autotrading_ai_signal_gate_enabled=True,
        autotrading_ai_signal_gate_live_enabled=False,
        autotrading_ai_signal_gate_shadow_enabled=True,
        autotrading_ai_analysis_ttl_seconds=900.0,
        autotrading_ai_live_fail_closed=True,
        autotrading_ai_min_confidence=0.4,
        autotrading_ai_reduce_ratio=0.5,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _fresh_analysis(**overrides):
    data = {
        "market_analysis_id": 1,
        "symbol": "KRW-XRP",
        "analysis_at": datetime.now(timezone.utc),
        "recommendation": "ALLOW",
        "confidence": 0.8,
        "summary": "ok",
        "risk_level": "LOW",
        "news_sentiment": "NEUTRAL",
        "trend": "UP",
        "momentum": "POSITIVE",
        "volatility": "LOW",
        "provider": "ollama",
        "model": "qwen3.5:4b",
        "analysis_status": "VALIDATED_ANALYSIS",
        "timeframe": "1m",
    }
    data.update(overrides)
    return data


def test_gate_disabled_allows(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(autotrading_ai_signal_gate_enabled=False),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="LIVE"
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_DISABLED"


def test_allow_with_fresh_analysis(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="PAPER"
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_ALLOW"


def test_hold_blocks_order(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="PAPER"
    )
    assert result.decision == AiSignalGateDecision.HOLD


def test_stale_analysis_hold_live(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(
            autotrading_ai_analysis_ttl_seconds=60.0,
            autotrading_ai_signal_gate_live_enabled=True,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(
            analysis_at=datetime.now(timezone.utc) - timedelta(hours=2)
        ),
    )
    monkeypatch.setattr(
        "stock_platform.order.live_shadow.is_live_shadow_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "stock_platform.order.live_dry_run.is_live_dry_run_mode",
        lambda: False,
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="LIVE"
    )
    assert result.decision == AiSignalGateDecision.HOLD
    assert result.reason_code == "AI_ANALYSIS_STALE"
    assert result.stale is True


def test_missing_analysis_live_fail_closed(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(autotrading_ai_signal_gate_live_enabled=True),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "stock_platform.order.live_shadow.is_live_shadow_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "stock_platform.order.live_dry_run.is_live_dry_run_mode",
        lambda: False,
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="LIVE"
    )
    assert result.decision == AiSignalGateDecision.HOLD
    assert result.reason_code == "AI_ANALYSIS_MISSING"


def test_missing_analysis_paper_fallback_allow(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: None,
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="PAPER"
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert "FALLBACK_ALLOW" in result.reason_code


def test_low_confidence_hold(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(autotrading_ai_min_confidence=0.7),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(confidence=0.2),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="PAPER"
    )
    assert result.decision == AiSignalGateDecision.HOLD


def test_malformed_recommendation_hold(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="???"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="PAPER"
    )
    assert result.decision == AiSignalGateDecision.HOLD


def test_reduce_sets_multiplier(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(autotrading_ai_reduce_ratio=0.5),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="REDUCE"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="PAPER"
    )
    assert result.decision == AiSignalGateDecision.REDUCE
    assert result.size_multiplier == Decimal("0.5")


def test_duplicate_fingerprint_reuses_cache(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    calls = {"n": 0}

    def _load(*a, **k):
        calls["n"] += 1
        return _fresh_analysis()

    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        _load,
    )
    sig = _signal(fingerprint="dup-1")
    r1 = evaluate_ai_signal_gate(MagicMock(), sig, environment="PAPER")
    r2 = evaluate_ai_signal_gate(MagicMock(), sig, environment="PAPER")
    assert r1.decision == r2.decision == AiSignalGateDecision.ALLOW
    assert calls["n"] == 1


def test_sell_goes_through_gate_hold(monkeypatch):
    """일반 SELL(비 exit reason)은 Gate HOLD 적용."""

    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="STRATEGY_SELL",
            fingerprint="sell-hold",
        ),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.HOLD
    assert result.reason_code == "AI_GATE_HOLD"


def test_stop_loss_bypasses_ai_hold(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="STOP_LOSS",
            fingerprint="sl-bypass",
            strategy_id=17483,
            account_id=1380,
        ),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_BYPASS_STOP_LOSS"
    assert result.detail.get("ai_gate_bypassed") is True


def test_take_profit_bypasses_ai_hold(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="TAKE_PROFIT",
            fingerprint="tp-bypass",
        ),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_BYPASS_TAKE_PROFIT"


def test_ma_dead_cross_bypasses_ai_hold(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="MA_DEAD_CROSS",
            fingerprint="dead-bypass",
        ),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert (
        result.reason_code
        == "AI_GATE_BYPASS_STRATEGY_POSITION_REDUCING_SELL"
    )


def test_kill_switch_reason_bypasses_ai_hold(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="KILL_SWITCH",
            fingerprint="kill-bypass",
        ),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_BYPASS_RISK_EXIT"


def test_stop_loss_bypasses_even_when_analysis_stale(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(
            autotrading_ai_analysis_ttl_seconds=60.0,
            autotrading_ai_signal_gate_live_enabled=True,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(
            recommendation="HOLD",
            analysis_at=datetime.now(timezone.utc) - timedelta(hours=2),
        ),
    )
    monkeypatch.setattr(
        "stock_platform.order.live_shadow.is_live_shadow_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "stock_platform.order.live_dry_run.is_live_dry_run_mode",
        lambda: False,
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="STOP_LOSS",
            fingerprint="sl-stale-bypass",
        ),
        environment="LIVE",
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_BYPASS_STOP_LOSS"



def test_live_gate_stays_off_by_default(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(
            autotrading_ai_signal_gate_enabled=True,
            autotrading_ai_signal_gate_live_enabled=False,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.order.live_shadow.is_live_shadow_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "stock_platform.order.live_dry_run.is_live_dry_run_mode",
        lambda: False,
    )
    result = evaluate_ai_signal_gate(
        MagicMock(), _signal(), environment="LIVE"
    )
    assert result.reason_code == "AI_GATE_DISABLED"


def _executor_with_gate(monkeypatch, *, gate_decision, environment="PAPER"):
    """Kill/Risk/Safety 통과 후 OrderExecutionService까지 mock (Paper Gate)."""

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.get_settings",
        lambda: SimpleNamespace(
            kiwoom_account_number="ACC",
            upbit_account_ref="UPBIT-REF",
            autotrading_ai_signal_gate_enabled=True,
            autotrading_ai_signal_gate_live_enabled=False,
            autotrading_ai_live_fail_closed=True,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation=gate_decision),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.PersistentKillSwitchGuard",
        lambda session: SimpleNamespace(
            require_order_allowed=lambda **kwargs: None
        ),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.DatabaseBackedRiskOrderGuard",
        lambda session, broker_code=None: SimpleNamespace(
            check=lambda **kwargs: SimpleNamespace(
                allowed=True, blocked_reason=None
            )
        ),
    )

    class _Lock:
        def is_trading_paused(self, **kwargs):
            return False

    monkeypatch.setattr(
        "stock_platform.broker.recovery_lock.RecoveryAccountLockService",
        lambda session: _Lock(),
    )

    executor = RiskIntegratedRealtimeOrderExecutor.__new__(
        RiskIntegratedRealtimeOrderExecutor
    )
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        masked_account_ref="UBA-1380",
        account_alias="UBA-1380",
        broker_code="UPBIT",
    )
    session.scalar.return_value = 0
    executor._session = session
    mode = (
        RealtimeExecutionMode.LIVE
        if environment == "LIVE"
        else RealtimeExecutionMode.PAPER
    )
    executor._execution_config = RealtimeExecutionConfig(
        account_id=1,
        order_amount=Decimal("10000"),
        mode=mode,
        user_broker_account_id=1380 if environment == "LIVE" else None,
    )
    guard = MagicMock()
    guard.evaluate.return_value = SimpleNamespace(
        allowed=True, reason_code=None
    )
    guard._config = SimpleNamespace(live_unlock_token=None)
    executor._safety_guard = guard
    return executor, guard


def test_e2e_allow_reaches_mock_order(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="ALLOW")
    submits: list = []

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            submits.append(command)
            return SimpleNamespace(
                allowed=True,
                order_id=999,
                status_code="ACCEPTED",
                quantity=command.quantity,
                price=command.price,
                reason_code=None,
            )

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    monkeypatch.setattr(
        "stock_platform.realtime.autotrading_idempotency.build_autotrading_idempotency_key",
        lambda *a, **k: "idem-test",
    )
    result = executor.execute(
        _signal(
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            user_id=61,
            fingerprint="e2e-allow",
        )
    )
    assert len(submits) == 1
    assert result.order_id == 999


def test_e2e_hold_zero_orders(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="HOLD")
    called = {"n": 0}

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            called["n"] += 1
            raise AssertionError("HOLD must not create order")

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    result = executor.execute(
        _signal(
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-hold",
        )
    )
    assert called["n"] == 0
    assert result.reason_code == "AI_GATE_HOLD"


def test_e2e_reduce_halves_order_amount(monkeypatch):
    executor, guard = _executor_with_gate(monkeypatch, gate_decision="REDUCE")
    submits: list = []

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            submits.append(command)
            return SimpleNamespace(
                allowed=True,
                order_id=1001,
                status_code="ACCEPTED",
                quantity=command.quantity,
                price=command.price,
                reason_code=None,
            )

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    monkeypatch.setattr(
        "stock_platform.realtime.autotrading_idempotency.build_autotrading_idempotency_key",
        lambda *a, **k: "idem-reduce",
    )
    result = executor.execute(
        _signal(
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-reduce",
            signal_price=Decimal("500"),
        )
    )
    assert len(submits) == 1
    assert submits[0].quantity == Decimal("10")
    assert guard.evaluate.call_args.kwargs["order_amount"] == Decimal("5000")
    assert result.order_id == 1001


def test_e2e_sell_hold_zero_orders(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="HOLD")
    called = {"n": 0}

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            called["n"] += 1

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    result = executor.execute(
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="STRATEGY_SELL",
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-sell-hold",
        )
    )
    assert called["n"] == 0
    assert result.reason_code == "AI_GATE_HOLD"


def test_e2e_hold_stop_loss_reaches_order(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="HOLD")
    submits: list = []

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            submits.append(command)
            return SimpleNamespace(
                allowed=True,
                order_id=2001,
                status_code="ACCEPTED",
                quantity=command.quantity,
                price=command.price,
                reason_code=None,
            )

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    monkeypatch.setattr(
        "stock_platform.realtime.autotrading_idempotency.build_autotrading_idempotency_key",
        lambda *a, **k: "idem-sl",
    )
    # holdings clip: held 5, order_amount 10000 @500 → qty 20 → clip to 5
    executor._session.scalar.return_value = Decimal("5")
    result = executor.execute(
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="STOP_LOSS",
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-sl-hold",
            signal_price=Decimal("500"),
            strategy_id=17483,
        )
    )
    assert len(submits) == 1
    assert submits[0].quantity == Decimal("5")
    assert result.order_id == 2001


def test_e2e_hold_take_profit_reaches_order(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="HOLD")
    submits: list = []

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            submits.append(command)
            return SimpleNamespace(
                allowed=True,
                order_id=2002,
                status_code="ACCEPTED",
                quantity=command.quantity,
                price=command.price,
                reason_code=None,
            )

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    monkeypatch.setattr(
        "stock_platform.realtime.autotrading_idempotency.build_autotrading_idempotency_key",
        lambda *a, **k: "idem-tp",
    )
    executor._session.scalar.return_value = Decimal("100")
    result = executor.execute(
        _signal(
            action=RealtimeSignalAction.SELL,
            reason_code="TAKE_PROFIT",
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-tp-hold",
            signal_price=Decimal("500"),
        )
    )
    assert len(submits) == 1
    assert result.order_id == 2002


def test_exit_policy_unit():
    from stock_platform.realtime.ai_signal_gate_exit_policy import (
        should_bypass_ai_gate,
    )

    buy = _signal(action=RealtimeSignalAction.BUY, reason_code="STOP_LOSS")
    assert should_bypass_ai_gate(buy) == (False, None)
    sl = _signal(action=RealtimeSignalAction.SELL, reason_code="STOP_LOSS")
    assert should_bypass_ai_gate(sl)[1] == "AI_GATE_BYPASS_STOP_LOSS"



def test_e2e_kill_switch_still_blocks(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="ALLOW")

    def _raise(**kwargs):
        raise PermissionError("kill")

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.PersistentKillSwitchGuard",
        lambda session: SimpleNamespace(require_order_allowed=_raise),
    )
    called = {"n": 0}

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            called["n"] += 1

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    result = executor.execute(
        _signal(
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-kill",
        )
    )
    assert called["n"] == 0
    assert result.reason_code == "GLOBAL_KILL_SWITCH_ACTIVE"


def test_paper_broker_upbit_exchange_applies_gate(monkeypatch):
    """Paper scope broker_code=PAPER + exchange UPBIT → Gate 적용."""

    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(broker_code="PAPER", market_type="CRYPTO"),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.HOLD
    assert result.reason_code != "AI_GATE_BROKER_SKIP"


def test_krx_paper_broker_skips_gate(monkeypatch):
    """KRX Paper 전략에는 UPBIT Gate 미적용."""

    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should skip")),
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(
            exchange_code="KRX",
            symbol="005930",
            broker_code="PAPER",
            market_type="STOCK",
        ),
        environment="PAPER",
    )
    assert result.decision == AiSignalGateDecision.ALLOW
    assert result.reason_code == "AI_GATE_BROKER_SKIP"


def test_live_upbit_gate_applies_when_live_enabled(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(autotrading_ai_signal_gate_live_enabled=True),
    )
    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        lambda *a, **k: _fresh_analysis(recommendation="HOLD"),
    )
    monkeypatch.setattr(
        "stock_platform.order.live_shadow.is_live_shadow_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "stock_platform.order.live_dry_run.is_live_dry_run_mode",
        lambda: False,
    )
    result = evaluate_ai_signal_gate(
        MagicMock(),
        _signal(broker_code="UPBIT"),
        environment="LIVE",
    )
    assert result.decision == AiSignalGateDecision.HOLD


def test_allow_duplicate_fingerprint_cache(monkeypatch):
    """동일 fingerprint 재평가 시 캐시 — Gate 결과 안정."""

    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate.get_settings",
        lambda: _settings(),
    )
    calls = {"n": 0}

    def _load(*_a, **_k):
        calls["n"] += 1
        return _fresh_analysis(recommendation="ALLOW")

    monkeypatch.setattr(
        "stock_platform.realtime.ai_signal_gate._load_latest_analysis",
        _load,
    )
    sig = _signal(fingerprint="fp-dup-allow", broker_code="PAPER", market_type="CRYPTO")
    first = evaluate_ai_signal_gate(MagicMock(), sig, environment="PAPER")
    second = evaluate_ai_signal_gate(MagicMock(), sig, environment="PAPER")
    assert first.decision == AiSignalGateDecision.ALLOW
    assert second.decision == AiSignalGateDecision.ALLOW
    assert calls["n"] == 1


def test_e2e_risk_fail_blocks(monkeypatch):
    executor, _ = _executor_with_gate(monkeypatch, gate_decision="ALLOW")
    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.DatabaseBackedRiskOrderGuard",
        lambda session, broker_code=None: SimpleNamespace(
            check=lambda **kwargs: SimpleNamespace(
                allowed=False, blocked_reason="DAILY_ORDER_LIMIT"
            )
        ),
    )
    called = {"n": 0}

    class _FakeOES:
        def __init__(self, session):
            pass

        def submit(self, command):
            called["n"] += 1

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService",
        _FakeOES,
    )
    result = executor.execute(
        _signal(
            account_kind="PAPER",
            account_id=1,
            scope_key="paper:1",
            fingerprint="e2e-risk",
        )
    )
    assert called["n"] == 0
    assert result.reason_code == "DAILY_ORDER_LIMIT"

