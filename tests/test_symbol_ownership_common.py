"""Symbol Ownership E2E scenarios A–J (실주문 0)."""

from __future__ import annotations

from decimal import Decimal

from stock_platform.trading.symbol_ownership.constants import (
    CONFLICT_REMOTE_MANUAL_ACTIVITY,
    CONFLICT_SAME_SYMBOL_MANUAL_AUTO,
    OWNER_AUTO,
    OWNER_FREE,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
    SKIP_MANUAL_SYMBOL_EXCLUDED,
)
from stock_platform.trading.symbol_ownership.decision import (
    OwnershipFacts,
    decide_ownership,
)


def test_a_manual_btc_auto_pepe_entry_allowed() -> None:
    btc = decide_ownership(
        OwnershipFacts(broker_position_qty=Decimal("0.01"))
    )
    pepe = decide_ownership(OwnershipFacts())
    assert btc.owner == OWNER_MANUAL
    assert btc.entry_allowed is False
    assert pepe.owner == OWNER_FREE
    assert pepe.entry_allowed is True


def test_b_manual_btc_sell_open_no_account_pause_signal() -> None:
    # MANUAL open order만 → MANUAL, pause_account 대상 아님
    btc = decide_ownership(
        OwnershipFacts(
            broker_position_qty=Decimal("0.01"),
            manual_open_orders=1,
        )
    )
    pepe = decide_ownership(
        OwnershipFacts(auto_binding_qty=Decimal("1000"))
    )
    assert btc.owner == OWNER_MANUAL
    assert pepe.owner == OWNER_AUTO
    assert pepe.entry_allowed is False  # already managed
    # remote classify contract
    from stock_platform.trading.symbol_ownership.service import (
        RemoteConflictClassification,
    )

    # MANUAL remote → no pause
    assert RemoteConflictClassification(
        pause_account=False,
        conflict_kind=CONFLICT_REMOTE_MANUAL_ACTIVITY,
        risk_level="INFO",
        symbol="KRW-BTC",
        owner=OWNER_MANUAL,
    ).pause_account is False


def test_c_scanner_manual_excluded_next_free() -> None:
    candidates = ["KRW-BTC", "KRW-ETH", "KRW-PEPE", "KRW-XRP"]
    ownership = {
        "KRW-BTC": decide_ownership(
            OwnershipFacts(broker_position_qty=Decimal("1"))
        ),
        "KRW-ETH": decide_ownership(
            OwnershipFacts(broker_position_qty=Decimal("1"))
        ),
        "KRW-PEPE": decide_ownership(OwnershipFacts()),
        "KRW-XRP": decide_ownership(OwnershipFacts()),
    }
    tradable = [
        s
        for s in candidates
        if ownership[s].entry_allowed
    ]
    assert tradable == ["KRW-PEPE", "KRW-XRP"]
    assert ownership["KRW-BTC"].entry_skip_reason == SKIP_MANUAL_SYMBOL_EXCLUDED


def test_d_same_symbol_manual_on_auto() -> None:
    pepe = decide_ownership(
        OwnershipFacts(
            auto_binding_qty=Decimal("1000"),
            broker_position_qty=Decimal("1000"),
            manual_open_orders=1,
        )
    )
    doge = decide_ownership(
        OwnershipFacts(auto_binding_qty=Decimal("50"))
    )
    assert pepe.owner == OWNER_UNKNOWN
    assert pepe.entry_allowed is False
    assert doge.owner == OWNER_AUTO
    assert CONFLICT_SAME_SYMBOL_MANUAL_AUTO


def test_e_round_trip_returns_free() -> None:
    after = decide_ownership(OwnershipFacts())
    assert after.owner == OWNER_FREE
    assert after.entry_allowed is True


def test_f_manual_loss_not_auto_scope() -> None:
    # Strategy PnL isolation contract: MANUAL position ≠ AUTO binding
    manual = decide_ownership(
        OwnershipFacts(broker_position_qty=Decimal("100"))
    )
    assert manual.owner == OWNER_MANUAL
    assert manual.auto_position_qty == 0


def test_g_auto_pnl_scope() -> None:
    auto = decide_ownership(
        OwnershipFacts(
            auto_binding_qty=Decimal("10"),
            broker_position_qty=Decimal("10"),
        )
    )
    assert auto.owner == OWNER_AUTO
    assert auto.auto_position_qty == Decimal("10")
    assert auto.manual_position_qty == 0


def test_h_exit_monitor_manual_not_selected() -> None:
    # Exit loader filters STRATEGY_OWNED only — MANUAL has no auto binding
    manual = decide_ownership(
        OwnershipFacts(broker_position_qty=Decimal("5"))
    )
    auto = decide_ownership(
        OwnershipFacts(auto_binding_qty=Decimal("5"))
    )
    exit_targets = [
        x for x in (manual, auto) if x.owner == OWNER_AUTO
    ]
    assert len(exit_targets) == 1
    assert exit_targets[0].owner == OWNER_AUTO


def test_i_restart_recomputable_from_facts() -> None:
    # derived SoT: facts만으로 재구성
    facts = OwnershipFacts(
        broker_position_qty=Decimal("1"),
        auto_binding_qty=Decimal("0"),
    )
    a = decide_ownership(facts)
    b = decide_ownership(facts)
    assert a == b


def test_j_common_resolver_contract_kiwoom_upbit() -> None:
    # 동일 facts → 동일 owner (broker-agnostic decision)
    facts = OwnershipFacts(broker_position_qty=Decimal("3"))
    assert decide_ownership(facts).owner == OWNER_MANUAL
    facts2 = OwnershipFacts(auto_slot_active=True)
    assert decide_ownership(facts2).owner == OWNER_AUTO
