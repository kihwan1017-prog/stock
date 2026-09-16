"""Strategy-owned Daily Loss vs Account Safety — focused tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.broker.kiwoom.equity_policy import (
    KIWOOM_EQUITY_V2_SETTLEMENT_AWARE,
    compute_kiwoom_equity_for_risk,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    OWNERSHIP_MANUAL,
    OWNERSHIP_STRATEGY,
    StrategyPositionBindingEntity,
)
from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
)
from stock_platform.risk_engine.uba_daily_loss_service import (
    daily_loss_from_pnl,
    snapshot_equity,
)


def _svc_with_bindings(bindings: list) -> StrategyOwnedRiskService:
    session = MagicMock()

    def _scalars(stmt):  # noqa: ANN001
        # 단순 mock: 호출 순서에 따라 리스트 반환 — tests는 직접 서비스 메서드 호출
        return iter(bindings)

    session.scalars = MagicMock(side_effect=lambda *_a, **_k: _scalars(None))
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    return StrategyOwnedRiskService(session)


def test_manual_holding_loss_excluded_from_strategy_daily_loss() -> None:
    """수동 보유 MTM은 strategy loss에 넣지 않음 — binding/order 없으면 0."""

    session = MagicMock()
    session.scalars = MagicMock(return_value=iter([]))
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    svc = StrategyOwnedRiskService(session)
    snap = svc.compute_and_persist(
        user_broker_account_id=99,
        broker_code="KIWOOM",
        strategy_id=1001,
        deployment_id=2002,
        loss_limit=Decimal("100000"),
        mark_prices={"000250": Decimal("1")},  # manual symbol ignored
    )
    assert snap.current_loss_amount == Decimal("0.00")
    assert snap.current_pnl == Decimal("0.00")
    assert snap.open_binding_count == 0


def test_strategy_owned_unrealized_loss_included() -> None:
    open_b = StrategyPositionBindingEntity(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        deployment_id=20,
        symbol="034310",
        status=BINDING_STATUS_OPEN,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("1"),
        entry_price=Decimal("10000"),
        realized_pnl=Decimal("0"),
        fees=Decimal("0"),
    )
    session = MagicMock()
    # orders empty, opens once, closed empty, daily row None
    session.scalars = MagicMock(
        side_effect=[
            iter([]),  # orders
            iter([open_b]),  # opens
            iter([]),  # closed
        ]
    )
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    svc = StrategyOwnedRiskService(session)
    snap = svc.compute_and_persist(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        deployment_id=20,
        loss_limit=Decimal("100000"),
        mark_prices={"034310": Decimal("9000")},
    )
    assert snap.unrealized_pnl == Decimal("-1000.00")
    assert snap.current_loss_amount == Decimal("1000.00")


def test_strategy_owned_realized_loss_included() -> None:
    closed = StrategyPositionBindingEntity(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        symbol="034310",
        status=BINDING_STATUS_CLOSED,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("10000"),
        realized_pnl=Decimal("-500"),
        fees=Decimal("0"),
        closed_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.scalars = MagicMock(
        side_effect=[
            iter([]),
            iter([]),
            iter([closed]),
        ]
    )
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    svc = StrategyOwnedRiskService(session)
    snap = svc.compute_and_persist(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        loss_limit=Decimal("100000"),
    )
    assert snap.realized_pnl == Decimal("-500.00")
    assert snap.current_loss_amount == Decimal("500.00")


def test_same_symbol_manual_plus_strategy_quantity_split() -> None:
    svc = StrategyOwnedRiskService(MagicMock())
    session = svc._session
    open_b = SimpleNamespace(
        symbol="034310",
        owned_quantity=Decimal("1"),
        status=BINDING_STATUS_OPEN,
    )
    session.scalars = MagicMock(return_value=iter([open_b]))
    classified = StrategyOwnedRiskService(session).classify_snapshot_positions(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        symbols=["034310", "000250"],
    )
    assert classified["034310"] == OWNERSHIP_STRATEGY
    assert classified["000250"] == OWNERSHIP_MANUAL


def test_strategy_loss_zero_with_no_auto_trades() -> None:
    session = MagicMock()
    session.scalars = MagicMock(return_value=iter([]))
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    hit, detail = StrategyOwnedRiskService(session).strategy_daily_loss_breached(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        deployment_id=20,
        limit=Decimal("100000"),
    )
    assert hit is False
    assert detail["current_loss_amount"] == "0.00"


def test_strategy_loss_limit_blocks() -> None:
    open_b = StrategyPositionBindingEntity(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        symbol="X",
        status=BINDING_STATUS_OPEN,
        owned_quantity=Decimal("1"),
        entry_price=Decimal("200000"),
        realized_pnl=Decimal("0"),
        fees=Decimal("0"),
    )
    session = MagicMock()
    session.scalars = MagicMock(
        side_effect=[iter([]), iter([open_b]), iter([])]
    )
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    snap = StrategyOwnedRiskService(session).compute_and_persist(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        loss_limit=Decimal("100000"),
        mark_prices={"X": Decimal("50000")},
    )
    assert snap.current_loss_amount == Decimal("150000.00")
    assert snap.status_code == "LIMIT_REACHED"



def test_account_hard_safety_kill_blocks() -> None:
    session = MagicMock()
    kill = MagicMock()
    kill.is_active_for_scopes = MagicMock(return_value=True)
    import stock_platform.risk_engine.strategy_owned_risk_service as mod

    original = StrategyOwnedRiskService.account_hard_safety_blocks_entry

    def _patched(self, *, user_broker_account_id: int):  # noqa: ANN001
        return True, {"reason": "KILL_SWITCH_ACTIVE", "scope": "ACCOUNT_SAFETY"}

    StrategyOwnedRiskService.account_hard_safety_blocks_entry = _patched  # type: ignore[method-assign]
    try:
        blocked, detail = StrategyOwnedRiskService(session).account_hard_safety_blocks_entry(
            user_broker_account_id=1
        )
        assert blocked is True
        assert detail["reason"] == "KILL_SWITCH_ACTIVE"
    finally:
        StrategyOwnedRiskService.account_hard_safety_blocks_entry = original  # type: ignore[method-assign]


def test_settlement_aware_account_equity_regression() -> None:
    account = SimpleNamespace(
        broker_code="KIWOOM",
        deposit_amount=Decimal("164342"),
        total_evaluation_amount=Decimal("4707617"),
        raw_data={
            "deposit": {
                "entr": "164342",
                "d2_entra": "435768",
                "prsm_dpst_aset_amt": "5133337",
            },
            "balance": {"tot_evlt_amt": "4707617"},
        },
    )
    v2 = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert v2.equity_for_risk == Decimal("5133337.00")


def test_upbit_snapshot_equity_unchanged() -> None:
    account = SimpleNamespace(
        broker_code="UPBIT",
        deposit_amount=Decimal("100"),
        total_evaluation_amount=Decimal("900"),
        total_profit_loss=Decimal("-1"),
    )
    assert snapshot_equity(account) == Decimal("1000.00")


def test_paper_daily_loss_from_pnl_unchanged() -> None:
    assert daily_loss_from_pnl(Decimal("-50")) == Decimal("50")
    assert daily_loss_from_pnl(Decimal("10")) == Decimal("0")
