"""카탈로그 activation / 계좌 링크는 LIVE·Runtime을 켜지 않는다."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    StrategyOwnershipError,
    assert_strategy_not_draft_derived,
)


def _user(*, user_id: int, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}",
        roles=["admin"] if is_admin else ["user"],
        permissions=["trading:read", "trading:write"],
    )


def _strategy(**kwargs):
    defaults = {
        "strategy_id": 17579,
        "owner_type": "USER",
        "user_id": 61,
        "visibility": "PRIVATE",
        "is_active": False,
        "deleted_at": None,
        "approved_at": None,
        "approved_by": None,
        "market_type": "STOCK",
        "source_draft_id": None,
        "source_strategy_id": 17486,
        "updated_by": None,
        "parameter_payload": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_clone_derived_activation_allowed_without_approved_at() -> None:
    session = MagicMock()
    row = _strategy(is_active=False, approved_at=None, source_draft_id=None)
    session.get.return_value = row
    updated = StrategyDefinitionService(session).admin_set_active(
        17579, is_active=True, actor="admin"
    )
    assert updated.is_active is True
    assert updated.approved_at is None
    assert_strategy_not_draft_derived(row)


def test_draft_derived_activation_blocked() -> None:
    session = MagicMock()
    row = _strategy(strategy_id=17486, user_id=7, source_draft_id=315)
    session.get.return_value = row
    with pytest.raises(HTTPException) as exc:
        StrategyDefinitionService(session).admin_set_active(
            17486, is_active=True, actor="admin"
        )
    assert exc.value.status_code == 409


def test_activation_does_not_imply_live_eligibility() -> None:
    session = MagicMock()
    row = _strategy(is_active=True, approved_at=None)
    session.get.return_value = row
    result = StrategyDefinitionService(session).evaluate_link_eligibility(
        _user(user_id=61),
        strategy_id=17579,
        user_broker_account_id=1381,
        paper_account_id=None,
        account_broker="KIWOOM",
    )
    assert result["link_eligible"] is True
    assert result["live_eligible"] is False
    assert result["link_created"] is False
    assert result["market_compatible"] is True


def test_link_to_uba_is_association_only() -> None:
    session = MagicMock()
    row = _strategy(is_active=True)
    session.get.return_value = row
    created = []

    def _add(entity) -> None:
        created.append(entity)
        entity.account_strategy_link_id = 9001

    session.add.side_effect = _add
    with patch(
        "stock_platform.strategy_deployment.ownership.assert_broker_account_access"
    ) as mocked:
        mocked.return_value = SimpleNamespace(
            user_broker_account_id=1381, user_id=61, broker_code="KIWOOM"
        )
        link = StrategyDefinitionService(session).link_to_account(
            _user(user_id=61),
            strategy_id=17579,
            paper_account_id=None,
            user_broker_account_id=1381,
            account_broker="KIWOOM",
            actor="kikicom",
        )
    assert mocked.called
    assert link.strategy_id == 17579
    assert link.user_broker_account_id == 1381
    assert link.paper_account_id is None
    assert link.is_active is True
    assert created[0] is link


def test_inactive_strategy_cannot_link() -> None:
    session = MagicMock()
    session.get.return_value = _strategy(is_active=False)
    with pytest.raises(StrategyOwnershipError):
        StrategyDefinitionService(session).link_to_account(
            _user(user_id=61),
            strategy_id=17579,
            paper_account_id=None,
            user_broker_account_id=1381,
            account_broker="KIWOOM",
            actor="kikicom",
        )


def test_upbit_clone_activation_keeps_approved_at_null() -> None:
    session = MagicMock()
    row = _strategy(
        strategy_id=17580,
        market_type="CRYPTO",
        source_strategy_id=17483,
        is_active=False,
        approved_at=None,
        source_draft_id=None,
    )
    session.get.return_value = row
    updated = StrategyDefinitionService(session).admin_set_active(
        17580, is_active=True, actor="admin"
    )
    assert updated.is_active is True
    assert updated.approved_at is None
    assert updated.market_type == "CRYPTO"


def test_upbit_link_eligibility_live_false() -> None:
    session = MagicMock()
    session.get.return_value = _strategy(
        strategy_id=17580,
        market_type="CRYPTO",
        source_strategy_id=17483,
        is_active=True,
        approved_at=None,
    )
    result = StrategyDefinitionService(session).evaluate_link_eligibility(
        _user(user_id=61),
        strategy_id=17580,
        user_broker_account_id=1380,
        paper_account_id=None,
        account_broker="UPBIT",
    )
    assert result["link_eligible"] is True
    assert result["live_eligible"] is False
    assert result["link_created"] is False
    assert result["blockers"] == []


def test_crypto_strategy_incompatible_with_kiwoom() -> None:
    session = MagicMock()
    session.get.return_value = _strategy(
        strategy_id=17580,
        market_type="CRYPTO",
        is_active=True,
        source_strategy_id=17483,
    )
    result = StrategyDefinitionService(session).evaluate_link_eligibility(
        _user(user_id=61),
        strategy_id=17580,
        user_broker_account_id=1381,
        paper_account_id=None,
        account_broker="KIWOOM",
    )
    assert result["link_eligible"] is False
    assert "MARKET_BROKER_INCOMPATIBLE" in result["blockers"]


def test_link_does_not_deactivate_existing_uba_strategy() -> None:
    session = MagicMock()
    session.get.return_value = _strategy(
        strategy_id=17580,
        market_type="CRYPTO",
        is_active=True,
        source_strategy_id=17483,
    )
    created = []

    def _add(entity) -> None:
        created.append(entity)
        entity.account_strategy_link_id = 2401

    session.add.side_effect = _add
    with patch(
        "stock_platform.strategy_deployment.ownership.assert_broker_account_access"
    ) as mocked:
        mocked.return_value = SimpleNamespace(
            user_broker_account_id=1380, user_id=61, broker_code="UPBIT"
        )
        StrategyDefinitionService(session).link_to_account(
            _user(user_id=61),
            strategy_id=17580,
            paper_account_id=None,
            user_broker_account_id=1380,
            account_broker="UPBIT",
            actor="kikicom",
        )
    assert len(created) == 1
    assert created[0].strategy_id == 17580
    assert created[0].user_broker_account_id == 1380
    session.execute.assert_not_called()
    session.scalars.assert_not_called()


def test_paper_run_1528_not_inherited_by_source_17483() -> None:
    from stock_platform.trading.paper_validation_policy import (
        REASON_SOURCE_EVIDENCE_NOT_INHERITED,
        RESULT_INSUFFICIENT,
        evaluate_paper_snapshot,
    )

    snapshot = {
        "run_id": 1528,
        "strategy_id": 17580,
        "run_type": "PAPER",
        "status_code": "COMPLETED",
        "symbol": "KRW-SOL",
        "period_start": "2023-07-20",
        "period_end": "2026-08-19",
        "result_payload": {
            "bars": 1127,
            "signals": {"BUY": 29},
            "fills": 58,
            "closed_trades": [{"net_pnl": "1"}] * 29,
            "buy_orders": 29,
            "sell_orders": 29,
            "order_ids": list(range(29 * 2)),
            "open_position": {"quantity": "0"},
            "final_cash": "10031591.43",
            "integrity_ok": True,
            "kiwoom_adapter_calls": 0,
            "upbit_adapter_calls": 0,
            "fee_total": "2915.97",
            "tax_total": "0",
            "realized_pnl": "34507.40",
        },
        "metric": {
            "total_trade_count": 29,
            "winning_trade_count": 14,
            "losing_trade_count": 15,
            "sharpe_ratio": "0.59626422",
            "maximum_drawdown_rate": "0.11033776",
            "profit_factor": "1.72291799",
            "win_rate": "48.27586207",
            "total_return_rate": "0.31591430",
            "net_profit_amount": "31591.43",
        },
    }
    inherited = evaluate_paper_snapshot(
        snapshot=snapshot,
        evaluated_strategy_id=17483,
    )
    assert inherited.result == RESULT_INSUFFICIENT
    assert REASON_SOURCE_EVIDENCE_NOT_INHERITED in inherited.reason_codes
    own = evaluate_paper_snapshot(
        snapshot=snapshot,
        evaluated_strategy_id=17580,
    )
    assert own.result == "PAPER_PASS"


def test_uba1380_runner_accepts_both_sol_and_xrp_signals() -> None:
    from datetime import datetime, timezone
    from decimal import Decimal

    from stock_platform.realtime.execution_models import (
        RealtimeExecutionConfig,
        RealtimeExecutionMode,
    )
    from stock_platform.realtime.execution_scope import (
        signal_matches_execution_scope,
    )
    from stock_platform.realtime.strategy_models import (
        RealtimeSignal,
        RealtimeSignalAction,
    )
    from stock_platform.strategy_deployment.runtime_scope import (
        AccountKind,
        StrategyRuntimeScope,
    )

    config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
    )
    now = datetime.now(timezone.utc)

    def _sig(*, strategy_id: int, symbol: str, uba: int, broker: str):
        return RealtimeSignal(
            exchange_code="UPBIT" if broker == "UPBIT" else "KRX",
            symbol=symbol,
            action=RealtimeSignalAction.BUY,
            signal_price=Decimal("10000"),
            short_average=None,
            long_average=None,
            change_rate=None,
            reason_code="TEST",
            generated_at=now,
            strategy_id=strategy_id,
            broker_code=broker,
            account_kind="USER_BROKER",
            account_id=uba,
            user_broker_account_id=uba,
            user_id=61,
        )

    assert signal_matches_execution_scope(
        _sig(strategy_id=17483, symbol="KRW-XRP", uba=1380, broker="UPBIT"),
        config,
    )
    assert signal_matches_execution_scope(
        _sig(strategy_id=17580, symbol="KRW-SOL", uba=1380, broker="UPBIT"),
        config,
    )
    assert not signal_matches_execution_scope(
        _sig(strategy_id=17579, symbol="005930", uba=1381, broker="KIWOOM"),
        config,
    )
    xrp_scope = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
        strategy_id=17483,
        strategy_version="1",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )
    sol_scope = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
        strategy_id=17580,
        strategy_version="1",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )
    assert xrp_scope.scope_key != sol_scope.scope_key
    assert "sid:17483" in xrp_scope.scope_key
    assert "sid:17580" in sol_scope.scope_key


def test_scanner_and_live_auto_start_defaults_off() -> None:
    from stock_platform.common.settings import Settings
    from stock_platform.realtime.live_runtime_control import (
        live_auto_start_allowed,
    )

    fields = Settings.model_fields
    assert fields["upbit_opportunity_scanner_mode"].default == "SHADOW_ONLY"
    assert fields["realtime_live_auto_start_enabled"].default is False
    assert fields["autotrading_ai_signal_gate_live_enabled"].default is False
    gate = live_auto_start_allowed(allow_live=True)
    assert gate["allowed"] is False
