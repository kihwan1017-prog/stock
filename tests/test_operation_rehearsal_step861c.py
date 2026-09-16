"""STEP 8-6-1C — Paper Rehearsal Current Price 누락 수정 테스트."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operations.rehearsal.checks.paper import (
    REHEARSAL_TEST_PRICE,
    rehearsal_symbol,
    run_paper_checks,
)
from stock_platform.operations.rehearsal.mark_prices import (
    RehearsalMarkPriceRegistry,
    RehearsalPriceError,
)
from stock_platform.operations.rehearsal.models import (
    CheckStatus,
    RehearsalOptions,
)
from stock_platform.trading.account_models import PaperAccount, PaperPosition
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)
from stock_platform.trading.models import OrderSide


def test_rehearsal_symbol_is_uppercase_rh_prefix() -> None:
    run_id = "operation-rehearsal-20260726-114311-5c7eb17c"
    symbol = rehearsal_symbol(run_id)
    assert symbol.startswith("RH")
    assert symbol == symbol.upper()
    assert symbol == "RH115C7EB17C"


def test_mark_price_registry_registers_and_requires() -> None:
    registry = RehearsalMarkPriceRegistry()
    entry = registry.register(
        exchange_code="krx",
        symbol="rhabc1234567",
        current_price=Decimal("1000.00"),
        run_id="run-1",
    )
    assert entry.key == "KRX:RHABC1234567"
    assert entry.current_price == Decimal("1000.00")
    assert registry.require("KRX", "RHABC1234567").current_price == Decimal(
        "1000.00"
    )
    assert registry.as_prices_dict()["KRX:RHABC1234567"] == Decimal("1000.00")
    assert registry.cleanup_run("run-1") == 1
    with pytest.raises(RehearsalPriceError, match="Current price is missing"):
        registry.require("KRX", "RHABC1234567")


def test_mark_price_registry_rejects_non_rh_symbol() -> None:
    registry = RehearsalMarkPriceRegistry()
    with pytest.raises(RehearsalPriceError, match="RH\\*"):
        registry.register(
            exchange_code="KRX",
            symbol="005930",
            current_price=Decimal("1000"),
            run_id="run-1",
        )


def test_paper_engine_still_raises_when_price_missing() -> None:
    """가격 누락 시 기존 PaperAccountError 유지 (검증 우회 금지)."""

    class Repo:
        def __init__(self) -> None:
            self.account = PaperAccount(
                account_name="t",
                currency_code="KRW",
                initial_cash=Decimal("1000000"),
                available_cash=Decimal("1000000"),
                realized_profit_loss=Decimal("0"),
            )
            self.account.account_id = 1
            self.position = PaperPosition(
                account_id=1,
                exchange_code="KRX",
                symbol="RHTEST00001",
                quantity=Decimal("1"),
                average_entry_price=Decimal("1000"),
                highest_price=Decimal("1000"),
                realized_profit_loss=Decimal("0"),
            )

        def get_account(self, account_id):
            return self.account

        def list_positions(self, *, account_id):
            return [self.position]

        def commit(self):
            return None

    service = PaperAccountService(Repo())  # type: ignore[arg-type]
    with pytest.raises(PaperAccountError, match="Current price is missing"):
        service.value_account(account_id=1, prices={})


def test_registered_price_allows_buy_fill_equity_sell() -> None:
    """등록된 RH* 가격으로 buy → equity → sell → position 0."""

    class Repo:
        def __init__(self) -> None:
            self.account = PaperAccount(
                account_name="t",
                currency_code="KRW",
                initial_cash=Decimal("1000000"),
                available_cash=Decimal("1000000"),
                realized_profit_loss=Decimal("0"),
            )
            self.account.account_id = 1
            self.position = None
            self.trade_id = 0

        def get_account(self, account_id):
            return self.account if account_id == 1 else None

        def get_position(self, **kwargs):
            return self.position

        def save_position(self, position):
            self.position = position
            return position

        def save_trade(self, trade):
            self.trade_id += 1
            trade.trade_id = self.trade_id
            return trade

        def list_positions(self, *, account_id):
            if self.position is None or self.position.quantity <= 0:
                return []
            return [self.position]

        def commit(self):
            return None

    run_id = "operation-rehearsal-20260726-120000-aabbccddee"
    symbol = rehearsal_symbol(run_id)
    registry = RehearsalMarkPriceRegistry()
    registered = registry.register(
        exchange_code="KRX",
        symbol=symbol,
        current_price=REHEARSAL_TEST_PRICE,
        run_id=run_id,
    )
    repo = Repo()
    service = PaperAccountService(repo)  # type: ignore[arg-type]

    # 가격 등록 전 주문 금지 개념: require 실패
    empty = RehearsalMarkPriceRegistry()
    with pytest.raises(RehearsalPriceError):
        empty.require("KRX", symbol)

    service.apply_fill(
        account_id=1,
        exchange_code="KRX",
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        fill_price=registered.current_price,
    )
    assert repo.position is not None
    assert repo.position.symbol == symbol.upper()

    valuation = service.value_account(
        account_id=1,
        prices=registry.as_prices_dict(),
    )
    assert valuation.total_equity > 0

    service.apply_fill(
        account_id=1,
        exchange_code="KRX",
        symbol=symbol,
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        fill_price=registered.current_price,
    )
    assert repo.list_positions(account_id=1) == []
    assert registry.cleanup_run(run_id) == 1


def test_case_mismatch_was_root_cause_uppercase_prices_work() -> None:
    """과거 실패: prices 키가 소문자면 missing, 대문자면 성공."""

    class Repo:
        def __init__(self) -> None:
            self.account = PaperAccount(
                account_name="t",
                currency_code="KRW",
                initial_cash=Decimal("1000000"),
                available_cash=Decimal("999000"),
                realized_profit_loss=Decimal("0"),
            )
            self.account.account_id = 1
            self.position = PaperPosition(
                account_id=1,
                exchange_code="KRX",
                symbol="RH115C7EB17C",
                quantity=Decimal("1"),
                average_entry_price=Decimal("1000"),
                highest_price=Decimal("1000"),
                realized_profit_loss=Decimal("0"),
            )

        def get_account(self, account_id):
            return self.account

        def list_positions(self, *, account_id):
            return [self.position]

        def commit(self):
            return None

    service = PaperAccountService(Repo())  # type: ignore[arg-type]
    with pytest.raises(PaperAccountError, match="RH115C7EB17C"):
        service.value_account(
            account_id=1,
            prices={"KRX:RH115c7eb17c": Decimal("1000.00")},
        )
    valuation = service.value_account(
        account_id=1,
        prices={"KRX:RH115C7EB17C": Decimal("1000.00")},
    )
    assert valuation.positions[0].current_price == Decimal("1000.00")


def test_no_paper_mutation_skips_price_and_order() -> None:
    opts = RehearsalOptions(
        full=True,
        telegram="dry-run",
        allow_paper_mutation=False,
    )
    with patch(
        "stock_platform.database.session.get_session_factory"
    ) as factory:
        session = MagicMock()
        factory.return_value = MagicMock(return_value=session)
        results = run_paper_checks(opts, run_id="operation-rehearsal-x-1")
    fill = next(r for r in results if r.name == "order_fill_equity")
    assert fill.status == CheckStatus.NOT_APPLICABLE
    assert fill.detail.get("price_registered") is False
    assert fill.detail.get("order_executed") is False


def test_decimal_price_quantize() -> None:
    registry = RehearsalMarkPriceRegistry()
    entry = registry.register(
        exchange_code="KRX",
        symbol="RHDECIMAL01",
        current_price=Decimal("1000.001"),
        run_id="r",
    )
    assert entry.current_price == Decimal("1000.00")


def test_mid_failure_cleanup_attempts_position_zero() -> None:
    """중간 실패 시에도 cleanup 경로가 잔량 0을 목표로 한다."""

    class Repo:
        def __init__(self) -> None:
            self.account = PaperAccount(
                account_name="t",
                currency_code="KRW",
                initial_cash=Decimal("1000000"),
                available_cash=Decimal("1000000"),
                realized_profit_loss=Decimal("0"),
            )
            self.account.account_id = 1
            self.position = None
            self.trade_id = 0
            self.fail_on_value = True

        def get_account(self, account_id):
            return self.account

        def get_position(self, **kwargs):
            return self.position

        def save_position(self, position):
            self.position = position
            return position

        def save_trade(self, trade):
            self.trade_id += 1
            trade.trade_id = self.trade_id
            return trade

        def list_accounts(self):
            return [self.account]

        def list_positions(self, *, account_id):
            if self.position is None or self.position.quantity <= 0:
                return []
            return [self.position]

        def commit(self):
            return None

    repo = Repo()
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    run_id = "operation-rehearsal-20260726-999999-deadbeef01"
    symbol = rehearsal_symbol(run_id)

    original_value = service.value_account

    def boom(**kwargs):
        raise PaperAccountError("Current price is missing: KRX:OTHER")

    service.value_account = boom  # type: ignore[method-assign]

    registry = RehearsalMarkPriceRegistry()
    price = registry.register(
        exchange_code="KRX",
        symbol=symbol,
        current_price=REHEARSAL_TEST_PRICE,
        run_id=run_id,
    ).current_price

    service.apply_fill(
        account_id=1,
        exchange_code="KRX",
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        fill_price=price,
    )
    assert repo.position is not None

    # cleanup
    from stock_platform.operations.rehearsal.checks.paper import (
        _cleanup_rehearsal_position,
    )

    result = _cleanup_rehearsal_position(
        service=service,
        repo=repo,
        account_id=1,
        symbol=symbol,
        price=price,
    )
    assert result["cleaned"] is True
    assert repo.list_positions(account_id=1) == []
    # restore unused ref
    _ = original_value


def test_repeated_symbols_differ_by_run_id() -> None:
    a = rehearsal_symbol("operation-rehearsal-20260726-111111-aaaaaaaaaa")
    b = rehearsal_symbol("operation-rehearsal-20260726-222222-bbbbbbbbbb")
    assert a != b
    assert a.startswith("RH") and b.startswith("RH")


def test_run_paper_checks_mutation_path_registers_price() -> None:
    """실제 Paper 체크 경로: 가격 등록 후 buy/equity/sell (세션 mock)."""

    run_id = "operation-rehearsal-20260726-130000-feedface01"
    symbol = rehearsal_symbol(run_id)

    account = PaperAccount(
        account_name="rehearsal",
        currency_code="KRW",
        initial_cash=Decimal("1000000"),
        available_cash=Decimal("1000000"),
        realized_profit_loss=Decimal("0"),
        is_active=True,
    )
    account.account_id = 42
    account.deleted_at = None

    class Repo:
        def __init__(self) -> None:
            self.account = account
            self.position = None
            self.trade_id = 0

        def list_accounts(self):
            return [self.account]

        def get_account(self, account_id):
            return self.account if account_id == 42 else None

        def get_position(self, **kwargs):
            return self.position

        def save_position(self, position):
            self.position = position
            return position

        def save_trade(self, trade):
            self.trade_id += 1
            trade.trade_id = self.trade_id
            return trade

        def list_positions(self, *, account_id):
            if self.position is None or self.position.quantity <= 0:
                return []
            return [self.position]

        def commit(self):
            return None

    repo = Repo()
    session = MagicMock()
    factory = MagicMock(return_value=session)

    opts = RehearsalOptions(
        full=True,
        telegram="dry-run",
        allow_paper_mutation=True,
    )

    with (
        patch(
            "stock_platform.database.session.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.trading.account_repository.PaperAccountRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.trading.account_service.PaperAccountService",
            side_effect=lambda r: PaperAccountService(r),
        ),
        patch(
            "stock_platform.settlement.service.AccountDailySettlementService",
            return_value=SimpleNamespace(
                health_summary=lambda: {"ok": True}
            ),
        ),
    ):
        results = run_paper_checks(opts, run_id=run_id)

    fill = next(r for r in results if r.name == "order_fill_equity")
    assert fill.status == CheckStatus.PASS, fill.message
    assert fill.detail["symbol"] == symbol
    assert fill.detail["price_registered"] is True
    assert fill.detail["registered_test_price"] == "1000.00"
    assert fill.detail["buy_fill"] is True
    assert fill.detail["sell_fill"] is True
    assert fill.detail["final_position"] == 0
    assert fill.detail["cleanup_ok"] is True
    assert Decimal(fill.detail["cash_delta"]) == Decimal("0.00")
