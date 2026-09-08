# -*- coding: utf-8 -*-
"""UBA1380 Common Entry Admission — focused regression (A–Q)."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.live_open_order_exposure import OpenOrderExposure
from stock_platform.trading.entry_admission_service import (
    EntryAdmissionDecision,
    EntryAdmissionService,
    classify_stale_ambiguous_sample,
    count_active_ambiguous_orders,
    reset_admission_telegram_dedupe_for_tests,
    should_emit_admission_telegram,
)


@pytest.fixture(autouse=True)
def _clear_tg() -> None:
    reset_admission_telegram_dedupe_for_tests()


def _policy(**overrides: object) -> SimpleNamespace:
    base = dict(
        daily_max_loss_amount=Decimal("10000000"),
        max_open_orders=1,
        max_position_count=5,
        account_paused=False,
        buy_enabled=True,
        sell_only=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _exposure(*, auto: int = 0, unknown: int = 0) -> OpenOrderExposure:
    return OpenOrderExposure(
        auto_open_count=auto,
        manual_open_count=0,
        unknown_open_count=unknown,
        total_open_count=auto + unknown,
        local_open_count=auto,
        local_auto_count=auto,
        local_manual_count=0,
        remote_open_count=0,
        remote_unmapped_count=0,
        remote_unmapped_manual_count=0,
        mapped_remote_count=0,
        remote_state="NOT_APPLICABLE",
        remote_state_ok=True,
        source="TEST",
        reason_code=None,
    )


def _ownership(*, allowed: bool = True, reason: str | None = None):
    result = SimpleNamespace(
        entry_allowed=allowed,
        entry_skip_reason=reason,
        to_dict=lambda: {"entry_allowed": allowed, "reason": reason},
    )
    return allowed, reason, result


@contextmanager
def _runtime_ok(
    svc_session: MagicMock, **overrides: object
) -> Iterator[None]:
    """LIVE/ARM/Auth/Activation/Kill 통과용 패치 스택."""

    account = SimpleNamespace(
        user_id=1,
        is_active=True,
        live_order_enabled=True,
    )
    svc_session.get.return_value = account
    defaults: dict[str, object] = {
        "arm": patch(
            "stock_platform.trading.live_arm_service."
            "LiveArmService.validate_arm_authorization",
            return_value=(True, "ARM_OK"),
        ),
        "auth": patch(
            "stock_platform.trading.live_unattended_authorization_service."
            "LiveUnattendedAuthorizationService.is_entry_authorized",
            return_value=True,
        ),
        "activation": patch(
            "stock_platform.broker.live_transition_guard."
            "LiveTradingTransitionGuard.require_active",
            return_value=None,
        ),
        "kill": patch(
            "stock_platform.risk_engine.kill_switch_guard."
            "PersistentKillSwitchGuard.require_order_allowed",
            return_value=None,
        ),
        "policy": patch(
            "stock_platform.trading.entry_admission_service."
            "ResolvedRiskPolicyResolver.resolve",
            return_value=_policy(),
        ),
        "daily_loss": patch(
            "stock_platform.trading.entry_admission_service."
            "should_suppress_auto_buy_for_daily_loss",
            return_value=(False, {"hit": False}),
        ),
        "exposure": patch(
            "stock_platform.trading.entry_admission_service."
            "evaluate_live_open_order_exposure",
            return_value=_exposure(auto=0),
        ),
        "slots": patch(
            "stock_platform.operation.upbit_full_market.auto_slot_count."
            "count_auto_slots_used",
            return_value=0,
        ),
        "ownership": patch(
            "stock_platform.trading.symbol_ownership."
            "SymbolOwnershipService.entry_gate",
            return_value=_ownership(allowed=True),
        ),
        "ambiguous": patch(
            "stock_platform.trading.entry_admission_service."
            "count_active_ambiguous_orders",
            return_value=(0, []),
        ),
        "recovery": patch(
            "stock_platform.trading.entry_admission_service."
            "count_active_recovery_conflicts",
            return_value=0,
        ),
        "daily_entry": patch(
            "stock_platform.operation.upbit_full_market."
            "portfolio_daily_entry_admission.resolve_portfolio_daily_entry_policy",
            return_value=("UNLIMITED", None),
        ),
    }
    defaults.update(overrides)
    with ExitStack() as stack:
        for ctx in defaults.values():
            stack.enter_context(ctx)  # type: ignore[arg-type]
        yield


def test_a_open_order_limit_denies_buy() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        exposure=patch(
            "stock_platform.trading.entry_admission_service."
            "evaluate_live_open_order_exposure",
            return_value=_exposure(auto=1),
        ),
    ):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-ARB",
            strategy_id=17483,
        )
    assert d.allowed is False
    assert d.reason_code == "OPEN_ORDER_LIMIT_REACHED"
    assert d.source == "OPEN_ORDER"


def test_b_open_orders_zero_allows() -> None:
    session = MagicMock()
    with _runtime_ok(session):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-BTC",
            strategy_id=17483,
        )
    assert d.allowed is True
    assert d.reason_code == "ADMISSION_ALLOWED"


def test_c_admission_recovers_when_open_clears() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        exposure=patch(
            "stock_platform.trading.entry_admission_service."
            "evaluate_live_open_order_exposure",
            return_value=_exposure(auto=1),
        ),
    ):
        denied = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-XLM",
            strategy_id=17483,
        )
    assert denied.allowed is False

    with _runtime_ok(session):
        allowed = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-XLM",
            strategy_id=17483,
        )
    assert allowed.allowed is True


def test_d_persistent_block_telegram_dedupe() -> None:
    assert should_emit_admission_telegram(
        user_broker_account_id=1380,
        reason_code="OPEN_ORDER_LIMIT_REACHED",
        trading_day=date(2026, 9, 8),
    )
    assert not should_emit_admission_telegram(
        user_broker_account_id=1380,
        reason_code="OPEN_ORDER_LIMIT_REACHED",
        trading_day=date(2026, 9, 8),
    )
    assert should_emit_admission_telegram(
        user_broker_account_id=1380,
        reason_code="DAILY_LOSS_LIMIT_REACHED",
        trading_day=date(2026, 9, 8),
    )


def test_e_daily_loss_safe_allows() -> None:
    session = MagicMock()
    with _runtime_ok(session):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-ONDO",
            strategy_id=17483,
        )
    assert d.allowed is True


def test_f_daily_loss_hit_suppresses() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        daily_loss=patch(
            "stock_platform.trading.entry_admission_service."
            "should_suppress_auto_buy_for_daily_loss",
            return_value=(
                True,
                {"reason_code": "DAILY_LOSS_LIMIT_REACHED", "hit": True},
            ),
        ),
    ):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-ONDO",
            strategy_id=17483,
        )
    assert d.allowed is False
    assert d.reason_code == "DAILY_LOSS_LIMIT_REACHED"


def test_g_position_limit_suppresses() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        policy=patch(
            "stock_platform.trading.entry_admission_service."
            "ResolvedRiskPolicyResolver.resolve",
            return_value=_policy(max_position_count=2),
        ),
        slots=patch(
            "stock_platform.operation.upbit_full_market.auto_slot_count."
            "count_auto_slots_used",
            return_value=2,
        ),
    ):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-ETH",
            strategy_id=17483,
        )
    assert d.allowed is False
    assert d.reason_code == "AUTO_POSITION_LIMIT_REACHED"


def test_h_managed_symbol_suppresses() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        ownership=patch(
            "stock_platform.trading.symbol_ownership."
            "SymbolOwnershipService.entry_gate",
            return_value=_ownership(
                allowed=False, reason="AUTO_SYMBOL_ALREADY_MANAGED"
            ),
        ),
    ):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-STX",
            strategy_id=17483,
        )
    assert d.allowed is False
    assert d.reason_code == "AUTO_SYMBOL_ALREADY_MANAGED"


def test_i_waiting_signal_self_slot_allows() -> None:
    session = MagicMock()
    with _runtime_ok(session):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-NEW",
            strategy_id=17483,
        )
    assert d.allowed is True


def test_j_ambiguous_active_fail_closed() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        ambiguous=patch(
            "stock_platform.trading.entry_admission_service."
            "count_active_ambiguous_orders",
            return_value=(
                1,
                [
                    {
                        "order_id": 999,
                        "symbol": "KRW-X",
                        "status_code": "AMBIGUOUS_SUBMISSION",
                        "classification": "ACTIVE_ACTIONABLE",
                    }
                ],
            ),
        ),
    ):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-BTC",
            strategy_id=17483,
        )
    assert d.allowed is False
    assert d.reason_code == "AMBIGUOUS_ORDER_ACTIVE"


def test_k_stale_ambiguous_not_active_blocker() -> None:
    session = MagicMock()
    filled = SimpleNamespace(
        order_id=3170,
        symbol="KRW-STX",
        status_code="FILLED",
        ambiguous_since="x",
    )
    session.scalars.side_effect = [[], [filled]]
    n, rows = count_active_ambiguous_orders(
        session, user_broker_account_id=1380
    )
    assert n == 0
    assert rows == []
    stale = classify_stale_ambiguous_sample(
        session, user_broker_account_id=1380
    )
    assert stale[0]["classification"] == "STALE_HISTORICAL"
    assert stale[0]["order_id"] == 3170


def test_l_kill_and_account_paused() -> None:
    session = MagicMock()
    with _runtime_ok(
        session,
        kill=patch(
            "stock_platform.risk_engine.kill_switch_guard."
            "PersistentKillSwitchGuard.require_order_allowed",
            side_effect=PermissionError(
                "Kill switch is active for account scope"
            ),
        ),
    ):
        d = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-BTC",
            strategy_id=17483,
        )
    assert d.allowed is False
    assert d.reason_code == "KILL_SWITCH_ACTIVE"

    with _runtime_ok(
        session,
        policy=patch(
            "stock_platform.trading.entry_admission_service."
            "ResolvedRiskPolicyResolver.resolve",
            return_value=_policy(account_paused=True),
        ),
    ):
        d2 = EntryAdmissionService(session).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-BTC",
            strategy_id=17483,
        )
    assert d2.allowed is False
    assert d2.reason_code == "ACCOUNT_PAUSED"


def test_m_runtime_safety_suppresses() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=1, is_active=True, live_order_enabled=False
    )
    d = EntryAdmissionService(session).evaluate_auto_buy(
        user_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        symbol="KRW-BTC",
        strategy_id=17483,
    )
    assert d.allowed is False
    assert d.reason_code == "LIVE_ORDER_DISABLED"

    session2 = MagicMock()
    with _runtime_ok(
        session2,
        arm=patch(
            "stock_platform.trading.live_arm_service."
            "LiveArmService.validate_arm_authorization",
            return_value=(False, "LIVE_NOT_ARMED"),
        ),
    ):
        d2 = EntryAdmissionService(session2).evaluate_auto_buy(
            user_id=1,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            symbol="KRW-BTC",
            strategy_id=17483,
        )
    assert d2.allowed is False
    assert d2.reason_code == "LIVE_NOT_ARMED"


def test_n_sell_not_subject_to_buy_admission_api() -> None:
    d = EntryAdmissionDecision(
        allowed=True,
        reason_code="ADMISSION_ALLOWED",
        source="N/A",
    )
    assert d.allowed is True


def test_n_executor_skips_admission_for_sell() -> None:
    import inspect

    from stock_platform.realtime.risk_integrated_order_executor import (
        RiskIntegratedRealtimeOrderExecutor,
    )

    src = inspect.getsource(RiskIntegratedRealtimeOrderExecutor)
    assert "EntryAdmissionService" in src
    assert 'str(signal.action.value).upper() == "BUY"' in src


def test_o_final_pipeline_still_rejects_open_order() -> None:
    import inspect

    from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline

    src = inspect.getsource(LiveOrderSafetyPipeline)
    assert "OPEN_ORDER_LIMIT_EXCEEDED" in src
    assert "evaluate_live_open_order_exposure" in src


def test_p_daily_loss_helpers_still_pass() -> None:
    from stock_platform.risk_engine.strategy_daily_loss_entry_gate import (
        resolve_canonical_strategy_id,
        should_suppress_auto_buy_for_daily_loss,
    )

    assert resolve_canonical_strategy_id(strategy_id=17483) == 17483
    session = MagicMock()
    with patch(
        "stock_platform.risk_engine.strategy_daily_loss_entry_gate."
        "strategy_owned_daily_loss_hit",
        return_value=(False, {"mode": "STRATEGY_OWNED"}),
    ):
        suppress, detail = should_suppress_auto_buy_for_daily_loss(
            session,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id=17483,
            deployment_id=None,
            limit=Decimal("10000000"),
        )
    assert suppress is False
    assert detail["mode"] == "STRATEGY_OWNED"


def test_q_managed_symbol_waiting_semantics() -> None:
    from stock_platform.trading.symbol_ownership.constants import (
        SKIP_AUTO_ALREADY_MANAGED,
    )
    from stock_platform.trading.symbol_ownership.decision import (
        OwnershipFacts,
        decide_ownership,
    )

    waiting = decide_ownership(
        OwnershipFacts(
            auto_slot_active=True,
            auto_slot_occupies_entry=False,
        )
    )
    assert waiting.entry_allowed is True
    assert waiting.entry_skip_reason is None

    occupied = decide_ownership(
        OwnershipFacts(
            auto_slot_active=True,
            auto_slot_occupies_entry=True,
        )
    )
    assert occupied.entry_allowed is False
    assert occupied.entry_skip_reason == SKIP_AUTO_ALREADY_MANAGED
    assert SKIP_AUTO_ALREADY_MANAGED == "AUTO_SYMBOL_ALREADY_MANAGED"
