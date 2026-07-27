"""Paper Trading 리허설 — RH* 마크가격 등록 + buy/fill/equity/sell cleanup."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.mark_prices import (
    RehearsalMarkPriceRegistry,
    RehearsalPriceError,
)
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
    RehearsalOptions,
)
from stock_platform.trading.models import OrderSide

REHEARSAL_SYMBOL_PREFIX = "RH"
# Paper Decimal 규칙에 맞춘 고정 테스트 가격
REHEARSAL_TEST_PRICE = Decimal("1000.00")
REHEARSAL_TEST_QTY = Decimal("1")


def rehearsal_symbol(run_id: str) -> str:
    """운영 종목과 구분되는 리허설 전용 심볼 (Paper 엔진 upper 정규화와 일치)."""

    token = "".join(ch for ch in run_id if ch.isalnum())[-10:].upper()
    return f"{REHEARSAL_SYMBOL_PREFIX}{token}"[:30]


def _cleanup_all_rehearsal_positions(
    *,
    service: Any,
    repo: Any,
    account_id: int,
    price: Decimal,
) -> dict[str, Any]:
    """계정 내 모든 RH* 잔량을 매도 정리 (이전 run 누수 방지)."""

    positions = repo.list_positions(account_id=account_id)
    sold = 0
    symbols: list[str] = []
    for pos in positions:
        if not str(pos.symbol).upper().startswith(REHEARSAL_SYMBOL_PREFIX):
            continue
        qty = Decimal(str(pos.quantity))
        if qty <= 0:
            continue
        mark = price
        avg = Decimal(str(pos.average_entry_price or 0))
        if avg > 0:
            mark = avg
        service.apply_fill(
            account_id=account_id,
            exchange_code=pos.exchange_code,
            symbol=pos.symbol,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price=mark,
        )
        sold += 1
        symbols.append(str(pos.symbol).upper())
    remaining = [
        p
        for p in repo.list_positions(account_id=account_id)
        if str(p.symbol).upper().startswith(REHEARSAL_SYMBOL_PREFIX)
        and Decimal(str(p.quantity)) > 0
    ]
    return {
        "sold_lots": sold,
        "symbols": symbols,
        "remaining": len(remaining),
        "cleaned": len(remaining) == 0,
    }


def _cleanup_rehearsal_position(
    *,
    service: Any,
    repo: Any,
    account_id: int,
    symbol: str,
    price: Decimal,
) -> dict[str, Any]:
    """RH* 잔량 포지션을 매도해 0으로 만든다."""

    positions = repo.list_positions(account_id=account_id)
    sold = 0
    for pos in positions:
        if pos.symbol.upper() != symbol.upper():
            continue
        qty = Decimal(str(pos.quantity))
        if qty <= 0:
            continue
        service.apply_fill(
            account_id=account_id,
            exchange_code=pos.exchange_code,
            symbol=pos.symbol,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price=price,
        )
        sold += 1
    remaining = [
        p
        for p in repo.list_positions(account_id=account_id)
        if p.symbol.upper() == symbol.upper() and p.quantity > 0
    ]
    return {
        "sold_lots": sold,
        "remaining": len(remaining),
        "cleaned": len(remaining) == 0,
    }


def run_paper_checks(
    options: RehearsalOptions,
    *,
    run_id: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    symbol = rehearsal_symbol(run_id)
    exchange_code = "KRX"

    def _list_accounts() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.database.session import get_session_factory
        from stock_platform.trading.account_repository import (
            PaperAccountRepository,
        )

        session = get_session_factory()()
        try:
            repo = PaperAccountRepository(session)
            accounts = repo.list_accounts()
            active = [
                a for a in accounts if getattr(a, "deleted_at", None) is None
            ]
            if not active:
                return (
                    CheckStatus.WARNING,
                    "no paper accounts",
                    {"count": 0, "run_id": run_id},
                )
            return (
                CheckStatus.PASS,
                f"paper_accounts={len(active)}",
                {
                    "count": len(active),
                    "sample_id": int(active[0].account_id),
                    "run_id": run_id,
                    "symbol": symbol,
                },
            )
        finally:
            session.close()

    results.append(
        run_check(suite="paper", name="account_list", fn=_list_accounts)
    )

    def _order_fill_value() -> tuple[CheckStatus, str, dict[str, Any]]:
        if not options.allow_paper_mutation:
            return (
                CheckStatus.NOT_APPLICABLE,
                "paper mutation disabled (--no-paper-mutation)",
                {
                    "run_id": run_id,
                    "symbol": symbol,
                    "price_registered": False,
                    "order_executed": False,
                },
            )

        from stock_platform.database.session import get_session_factory
        from stock_platform.trading.account_repository import (
            PaperAccountRepository,
        )
        from stock_platform.trading.account_service import PaperAccountService

        registry = RehearsalMarkPriceRegistry()
        session = get_session_factory()()
        detail: dict[str, Any] = {
            "run_id": run_id,
            "symbol": symbol,
            "exchange_code": exchange_code,
            "cleanup_attempted": False,
            "cleanup_ok": False,
            "price_registered": False,
            "order_executed": False,
        }
        try:
            repo = PaperAccountRepository(session)
            service = PaperAccountService(repo)
            accounts = [
                a
                for a in repo.list_accounts()
                if getattr(a, "deleted_at", None) is None
                and getattr(a, "is_active", True)
            ]
            if not accounts:
                return (
                    CheckStatus.WARNING,
                    "skip fill — no active paper account",
                    detail,
                )

            # 타 종목 오픈 포지션이 없는 계정을 우선 선택
            def _foreign_open_count(account_id: int) -> int:
                return sum(
                    1
                    for pos in repo.list_positions(account_id=account_id)
                    if Decimal(str(pos.quantity)) > 0
                    and not str(pos.symbol).upper().startswith(
                        REHEARSAL_SYMBOL_PREFIX
                    )
                )

            accounts.sort(
                key=lambda item: (
                    _foreign_open_count(int(item.account_id)),
                    int(item.account_id),
                )
            )
            account = accounts[0]
            account_id = int(account.account_id)
            cash_before = Decimal(str(account.available_cash))
            detail["account_id"] = account_id
            detail["cash_before"] = str(cash_before)

            # 이전 실패로 남은 모든 RH* 포지션 정리 (시세 누수 방지)
            prior_cleanup = _cleanup_all_rehearsal_positions(
                service=service,
                repo=repo,
                account_id=account_id,
                price=REHEARSAL_TEST_PRICE,
            )
            detail["prior_rh_cleanup"] = prior_cleanup

            # 1) 현재가 등록 (주문 전 필수)
            try:
                registered = registry.register(
                    exchange_code=exchange_code,
                    symbol=symbol,
                    current_price=REHEARSAL_TEST_PRICE,
                    run_id=run_id,
                )
            except RehearsalPriceError as exc:
                detail["current_price_missing"] = True
                return (
                    CheckStatus.FAIL,
                    f"mark price register failed: {exc}",
                    detail,
                )

            detail["price_registered"] = True
            detail["registered_test_price"] = str(registered.current_price)
            detail["price_key"] = registered.key
            detail["price_source"] = registered.source

            # 등록 확인 — 없으면 주문 금지
            try:
                registry.require(exchange_code, symbol)
            except RehearsalPriceError as exc:
                detail["current_price_missing"] = True
                return (
                    CheckStatus.FAIL,
                    str(exc),
                    detail,
                )

            price = registered.current_price

            def _valuation_prices() -> dict[str, Decimal]:
                """RH*는 레지스트리(+잔여 RH* 마크), 기존 종목은 평균단가."""

                prices = registry.as_prices_dict()
                for pos in repo.list_positions(account_id=account_id):
                    if Decimal(str(pos.quantity)) <= 0:
                        continue
                    key = (
                        f"{str(pos.exchange_code).upper()}:"
                        f"{str(pos.symbol).upper()}"
                    )
                    if key in prices:
                        continue
                    sym = str(pos.symbol).upper()
                    if sym.startswith(REHEARSAL_SYMBOL_PREFIX):
                        # 잔여 RH* — 테스트 가격으로 마크 (누락 시 equity FAIL 방지)
                        prices[key] = REHEARSAL_TEST_PRICE
                        continue
                    avg = Decimal(str(pos.average_entry_price))
                    if avg > 0:
                        prices[key] = avg.quantize(Decimal("0.01"))
                return prices

            valuation_equity: Decimal | None = None
            try:
                # 2) buy fill
                service.apply_fill(
                    account_id=account_id,
                    exchange_code=exchange_code,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=REHEARSAL_TEST_QTY,
                    fill_price=price,
                )
                detail["order_executed"] = True
                detail["buy_fill"] = True

                # 3) equity (엔진 가격 검증 유지 — registry + 기존 포지션 마크)
                valuation_prices = _valuation_prices()
                detail["valuation_price_keys"] = sorted(
                    valuation_prices.keys()
                )
                valuation = service.value_account(
                    account_id=account_id,
                    prices=valuation_prices,
                )
                valuation_equity = valuation.total_equity
                detail["total_equity"] = str(valuation.total_equity)
                detail["unrealized_pnl"] = str(
                    valuation.unrealized_profit_loss
                )
                detail["position_count"] = len(valuation.positions)

                # 4) sell cleanup
                service.apply_fill(
                    account_id=account_id,
                    exchange_code=exchange_code,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=REHEARSAL_TEST_QTY,
                    fill_price=price,
                )
                detail["sell_fill"] = True
            except Exception as exc:
                detail["error"] = f"{type(exc).__name__}: {exc}"
                detail["current_price_missing"] = (
                    "Current price is missing" in str(exc)
                )
                detail["cleanup_attempted"] = True
                cleanup = _cleanup_rehearsal_position(
                    service=service,
                    repo=repo,
                    account_id=account_id,
                    symbol=symbol,
                    price=price,
                )
                detail["cleanup"] = cleanup
                detail["cleanup_ok"] = bool(cleanup.get("cleaned"))
                removed = registry.cleanup_run(run_id)
                detail["price_cleanup_removed"] = removed
                if not detail["cleanup_ok"]:
                    return (
                        CheckStatus.FAIL,
                        (
                            f"{type(exc).__name__}: {exc}; "
                            "cleanup failed"
                        ),
                        detail,
                    )
                return (
                    CheckStatus.FAIL,
                    f"{type(exc).__name__}: {exc}",
                    detail,
                )

            # 정상 경로 cleanup 검증
            detail["cleanup_attempted"] = True
            cleanup = _cleanup_rehearsal_position(
                service=service,
                repo=repo,
                account_id=account_id,
                symbol=symbol,
                price=price,
            )
            # sell 이미 완료되어 remaining=0 이어야 함
            detail["cleanup"] = cleanup
            detail["cleanup_ok"] = bool(cleanup.get("cleaned"))
            removed = registry.cleanup_run(run_id)
            detail["price_cleanup_removed"] = removed
            detail["final_position"] = 0 if detail["cleanup_ok"] else None

            if not detail["cleanup_ok"]:
                return (
                    CheckStatus.FAIL,
                    "rehearsal position not cleaned up",
                    detail,
                )

            account_after = repo.get_account(account_id)
            cash_after = Decimal(str(account_after.available_cash))
            delta = cash_after - cash_before
            detail["cash_after"] = str(cash_after)
            detail["cash_delta"] = str(delta)
            detail["total_equity"] = str(
                valuation_equity
                if valuation_equity is not None
                else "0"
            )

            return (
                CheckStatus.PASS,
                "order/fill/equity cleaned",
                detail,
            )
        finally:
            # 레지스트리 잔여 정리 (세션 종료와 무관)
            try:
                registry.cleanup_run(run_id)
            except Exception:  # noqa: BLE001
                pass
            session.close()

    results.append(
        run_check(suite="paper", name="order_fill_equity", fn=_order_fill_value)
    )

    def _settlement_health() -> tuple[CheckStatus, str, dict[str, Any]]:
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.settlement.service import (
                AccountDailySettlementService,
            )

            session = get_session_factory()()
            try:
                summary = AccountDailySettlementService(session).health_summary()
                return (
                    CheckStatus.PASS,
                    "settlement health ok",
                    {
                        "run_id": run_id,
                        **(
                            summary
                            if isinstance(summary, dict)
                            else {"raw": str(summary)}
                        ),
                    },
                )
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            return (
                CheckStatus.WARNING,
                f"settlement health unavailable: {type(exc).__name__}",
                {"run_id": run_id},
            )

    results.append(
        run_check(suite="paper", name="settlement", fn=_settlement_health)
    )
    return results
