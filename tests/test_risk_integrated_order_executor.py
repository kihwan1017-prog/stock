from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
    resolve_execution_environment,
    resolve_portfolio_order_amount_krw,
    resolve_signal_broker_code,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


def _signal(**kwargs) -> RealtimeSignal:
    base = dict(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("100000000"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="TEST",
        generated_at=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return RealtimeSignal(**base)


def test_resolve_broker_code_from_signal() -> None:
    assert (
        resolve_signal_broker_code(
            _signal(broker_code="upbit", exchange_code="KRX")
        )
        == "UPBIT"
    )


def test_resolve_broker_code_from_exchange_upbit() -> None:
    assert resolve_signal_broker_code(_signal(broker_code=None)) == "UPBIT"


def test_resolve_broker_code_from_exchange_krx() -> None:
    assert (
        resolve_signal_broker_code(
            _signal(exchange_code="KRX", broker_code=None, symbol="005930")
        )
        == "KIWOOM"
    )


def test_resolve_environment_paper_default() -> None:
    cfg = RealtimeExecutionConfig(account_id=7, mode=RealtimeExecutionMode.PAPER)
    assert resolve_execution_environment(cfg, _signal()) == "PAPER"


def test_resolve_portfolio_order_amount_prefers_approved() -> None:
    amount = resolve_portfolio_order_amount_krw(
        {
            "approved_amount_krw": 10000,
            "final_order_amount_krw": 9000,
            "reserved_amount_krw": 8000,
            "allocated_amount_krw": 7000,
        }
    )
    assert amount == Decimal("10000")


def test_resolve_portfolio_order_amount_fallback_chain() -> None:
    assert resolve_portfolio_order_amount_krw(
        {"final_order_amount_krw": 9000, "reserved_amount_krw": 8000}
    ) == Decimal("9000")
    assert resolve_portfolio_order_amount_krw(
        {"reserved_amount_krw": 8000, "allocated_amount_krw": 7000}
    ) == Decimal("8000")
    assert resolve_portfolio_order_amount_krw(
        {"allocated_amount_krw": 7000}
    ) == Decimal("7000")


def test_resolve_portfolio_order_amount_none_when_canonical_absent() -> None:
    assert resolve_portfolio_order_amount_krw({}) is None
    assert resolve_portfolio_order_amount_krw({"ok": True, "already": True}) is None


def test_paper_signal_does_not_require_kiwoom_account(
    monkeypatch,
) -> None:
    """P0-1: Paper/Upbit는 전역 kiwoom_account_number 없어도 차단되지 않는다."""

    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.get_settings",
        lambda: SimpleNamespace(kiwoom_account_number=""),
    )

    executor = RiskIntegratedRealtimeOrderExecutor.__new__(
        RiskIntegratedRealtimeOrderExecutor
    )
    executor._session = MagicMock()
    executor._execution_config = RealtimeExecutionConfig(
        account_id=1,
        order_amount=Decimal("100000"),
        mode=RealtimeExecutionMode.PAPER,
    )
    guard = MagicMock()
    guard.evaluate.return_value = SimpleNamespace(
        allowed=False, reason_code="SAFETY_BLOCKED_FOR_TEST"
    )
    executor._safety_guard = guard

    # Kill switch / risk 는 통과시키고 safety에서 멈추게 함
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
    executor._session.scalar.return_value = 0

    result = executor.execute(
        _signal(
            scope_key="u1:p1",
            account_kind="PAPER",
            account_id=1,
            broker_code="UPBIT",
        )
    )

    assert result.reason_code != "RISK_ACCOUNT_NUMBER_MISSING"
    assert result.reason_code == "SAFETY_BLOCKED_FOR_TEST"


def test_live_missing_account_number_still_blocks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.get_settings",
        lambda: SimpleNamespace(kiwoom_account_number=""),
    )

    executor = RiskIntegratedRealtimeOrderExecutor.__new__(
        RiskIntegratedRealtimeOrderExecutor
    )
    executor._session = MagicMock()
    executor._session.get.return_value = None
    executor._execution_config = RealtimeExecutionConfig(
        account_id=1,
        order_amount=Decimal("100000"),
        mode=RealtimeExecutionMode.LIVE,
        user_broker_account_id=99,
    )
    executor._safety_guard = object()

    result = executor.execute(
        _signal(
            exchange_code="KRX",
            symbol="005930",
            broker_code="KIWOOM",
            account_kind="USER_BROKER",
            account_id=99,
            scope_key="live:1",
        )
    )

    assert result.order_status == "SKIPPED"
    # UBA 행이 없으면 계좌번호 해석 전에 fail-closed
    assert result.reason_code in {
        "UBA_INACTIVE",
        "RISK_ACCOUNT_NUMBER_MISSING",
    }
