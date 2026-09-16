"""Paper historical replay — 기존 evaluator + PAPER OES + Paper fill.

새 Backtest 엔진을 만들지 않는다. LIVE/KIWOOM/UPBIT adapter 경로는
호출하지 않는다. skip_risk_checks=False.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.auth.models import AuthUser  # noqa: F401 — paper_account.user_id FK
from stock_platform.risk.persistence_models import (  # noqa: F401
    PositionPlanEntity,
)
from stock_platform.strategy_deployment.entities import (  # noqa: F401
    StrategyDeploymentEntity,
)
from stock_platform.trading.account_models import PaperAccount
from stock_platform.trading.models import PaperOrder  # noqa: F401
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    RuleBasedBacktestAdapter,
    compile_specification,
)
from stock_platform.backtest.models import BacktestPrice
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.database.session import get_session_factory
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import PriceDailyService
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.order.paper_outbox_fill_service import PaperOutboxFillService
from stock_platform.performance.models import (
    PerformanceRunStatus,
    PerformanceRunType,
    StrategyPerformanceMetrics,
)
from stock_platform.performance.repository import StrategyPerformanceRepository
from stock_platform.performance.service import StrategyPerformanceService
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)
from stock_platform.trading.user_account_service import UserAccountService


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
FEE_RATIO = Decimal("0.00015")
SELL_TAX_RATIO = Decimal("0.0018")
UPBIT_FEE_RATIO = UpbitFeePolicy.DEFAULT_TAKER_RATE
UPBIT_SELL_TAX_RATIO = ZERO
CRYPTO_EXCHANGES = frozenset({"UPBIT", "CRYPTO"})
SLIPPAGE_RATIO = Decimal("0")
PAPER_REPLAY_HOLDOUT_POLICY = "NOT_DEFINED"
FILL_CONVENTION = "SAME_BAR_CLOSE_MATCHING_BACKTEST"
ACCEPTANCE_POLICY = "NOT_DEFINED"
RUN_TYPE = PerformanceRunType.PAPER


class PaperHistoricalReplayError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class ReplayBarDecision:
    index: int
    trade_date: date
    side: str | None
    reason: str
    fill_price: Decimal | None
    skipped_cooldown: bool = False


@dataclass(slots=True)
class ReplayClosedTrade:
    entry_date: date
    exit_date: date
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    fee_amount: Decimal
    tax_amount: Decimal
    slippage_amount: Decimal
    net_profit_loss: Decimal
    exit_reason: str


def evaluate_bar(
    adapter: RuleBasedBacktestAdapter,
    prices: list[BacktestPrice],
    index: int,
    *,
    in_position: bool,
    entry_price: Decimal,
    cooldown_remaining: int,
    warmup_bars: int,
) -> ReplayBarDecision:
    """한 bar만 평가한다. index 이후 close는 신호에 쓰지 않는다(adapter 계약)."""

    price = prices[index]
    if index < max(0, warmup_bars - 1):
        return ReplayBarDecision(
            index=index,
            trade_date=price.trade_date,
            side=None,
            reason="WARMUP",
            fill_price=None,
        )
    if not in_position:
        if cooldown_remaining > 0:
            return ReplayBarDecision(
                index=index,
                trade_date=price.trade_date,
                side=None,
                reason="COOLDOWN",
                fill_price=None,
                skipped_cooldown=True,
            )
        should_enter, reason = adapter.should_enter(prices=prices, index=index)
        if not should_enter:
            return ReplayBarDecision(
                index=index,
                trade_date=price.trade_date,
                side=None,
                reason=reason,
                fill_price=None,
            )
        fill_price = price.close_price * (ONE + SLIPPAGE_RATIO)
        return ReplayBarDecision(
            index=index,
            trade_date=price.trade_date,
            side="BUY",
            reason=reason,
            fill_price=fill_price,
        )

    should_exit, reason = adapter.should_exit(
        prices=prices,
        index=index,
        entry_price=entry_price,
    )
    if not should_exit:
        return ReplayBarDecision(
            index=index,
            trade_date=price.trade_date,
            side=None,
            reason=reason,
            fill_price=None,
        )
    if reason == "STOP_LOSS":
        raw = entry_price * (ONE - adapter.config.stop_loss_ratio)
    elif reason == "TAKE_PROFIT":
        raw = entry_price * (ONE + adapter.config.take_profit_ratio)
    else:
        raw = price.close_price
    fill_price = raw * (ONE - SLIPPAGE_RATIO)
    mapped = "MA_DEAD_CROSS" if reason == "RULE_EXIT" else reason
    return ReplayBarDecision(
        index=index,
        trade_date=price.trade_date,
        side="SELL",
        reason=mapped,
        fill_price=fill_price,
    )


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _sharpe(daily_returns: list[Decimal]) -> Decimal | None:
    if len(daily_returns) < 2:
        return None
    mean = sum(daily_returns, ZERO) / Decimal(len(daily_returns))
    var = sum(((r - mean) ** 2 for r in daily_returns), ZERO) / Decimal(
        len(daily_returns)
    )
    stdev = var.sqrt() if var > ZERO else ZERO
    if stdev <= ZERO:
        return None
    return (mean / stdev) * Decimal("252").sqrt()


def _cost_ratios(exchange_code: str) -> tuple[Decimal, Decimal]:
    """KRX는 수수료+매도세, UPBIT는 보수적 taker 수수료만(거래세 없음)."""

    if str(exchange_code or "").upper() in CRYPTO_EXCHANGES:
        return UPBIT_FEE_RATIO, UPBIT_SELL_TAX_RATIO
    return FEE_RATIO, SELL_TAX_RATIO


def _qty_step(exchange_code: str) -> Decimal:
    if str(exchange_code or "").upper() in CRYPTO_EXCHANGES:
        return Decimal("0.00000001")
    return Decimal("1")


def _size_buy_quantity(
    *,
    available_cash: Decimal,
    price: Decimal,
    position_ratio: Decimal,
    max_order_amount: Decimal | None,
    exchange_code: str = "KRX",
) -> tuple[Decimal, Decimal]:
    """KRX는 정수주, UPBIT는 소수 수량. 수수료를 예산에 포함한다."""

    if price <= ZERO or available_cash <= ZERO:
        return ZERO, ZERO
    budget = (available_cash * position_ratio).quantize(Decimal("0.01"))
    if max_order_amount is not None and max_order_amount > ZERO:
        budget = min(budget, max_order_amount)
    fee_ratio, _tax = _cost_ratios(exchange_code)
    unit_cost = price * (ONE + fee_ratio)
    quantity = (budget / unit_cost).quantize(
        _qty_step(exchange_code), rounding=ROUND_DOWN
    )
    if quantity <= ZERO:
        return ZERO, ZERO
    gross = (quantity * price).quantize(Decimal("0.01"))
    return quantity, gross


def _paper_replay_buy_budget_cap(
    session: Session,
    *,
    owner_user_id: int,
    strategy_max_order_amount: Decimal | None,
) -> Decimal | None:
    """PAPER replay BUY 명목을 ResolvedRisk(시스템+사용자, UBA 없음)로 cap.

    LIVE UBA 한도를 Paper에 복사하지 않는다. skip_risk_checks도 쓰지 않는다.
    """

    from stock_platform.risk_engine.resolved_policy import (
        ResolvedRiskPolicyResolver,
    )

    resolved = ResolvedRiskPolicyResolver(session).resolve(
        user_id=int(owner_user_id),
        user_broker_account_id=None,
    )
    caps: list[Decimal] = []
    if strategy_max_order_amount is not None and strategy_max_order_amount > ZERO:
        caps.append(strategy_max_order_amount)
    for raw in (
        resolved.max_order_amount,
        resolved.max_position_amount,
        resolved.max_total_investment_amount,
        resolved.daily_max_order_amount,
    ):
        if raw is None:
            continue
        value = Decimal(str(raw))
        if value > ZERO:
            caps.append(value)
    if not caps:
        return strategy_max_order_amount
    return min(caps)


class PaperHistoricalReplayService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._performance = StrategyPerformanceService(session)
        self._performance_repo = StrategyPerformanceRepository(session)
        self._accounts = PaperAccountService(PaperAccountRepository(session))
        self._user_accounts = UserAccountService(session)
        self._prices = PriceDailyService(PriceDailyRepository(session))
        self._kiwoom_adapter_calls = 0
        self._upbit_adapter_calls = 0

    def run(
        self,
        *,
        strategy_definition_id: int,
        symbol: str,
        exchange_code: str = "KRX",
        actor_user_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        definition = self._session.get(
            StrategyDefinitionEntity, int(strategy_definition_id)
        )
        if definition is None or definition.deleted_at is not None:
            raise PaperHistoricalReplayError("NOT_FOUND", "strategy definition 없음")
        owner_id = int(definition.user_id) if definition.user_id is not None else None
        if owner_id is None:
            raise PaperHistoricalReplayError(
                "OWNER_REQUIRED", "strategy owner user_id 없음"
            )

        specification = compile_specification(self._session, int(strategy_definition_id))
        if not specification.get("compilable"):
            raise PaperHistoricalReplayError(
                "NOT_COMPILABLE",
                ",".join(specification.get("errors") or ["compile failed"]),
            )

        payload = definition.parameter_payload or {}
        indicator_cfg = payload.get("indicator_configuration") or {}
        warmup_bars = int(indicator_cfg.get("warmup_bars") or 0)
        cooldown_bars = int(indicator_cfg.get("cooldown_bars") or 0)
        risk_params = payload.get("risk_parameters") or {}
        max_order_raw = risk_params.get("max_order_amount")
        strategy_max_order_amount = (
            _dec(max_order_raw) if max_order_raw is not None else None
        )

        rows = self._prices.get_between(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=start_date or date(1990, 1, 1),
            end_date=end_date or date(2999, 12, 31),
        )
        prices = [
            BacktestPrice(
                trade_date=row.trade_date,
                open_price=_dec(row.open_price),
                high_price=_dec(row.high_price),
                low_price=_dec(row.low_price),
                close_price=_dec(row.close_price),
                volume=_dec(row.volume),
            )
            for row in rows
        ]
        if len(prices) < 2:
            raise PaperHistoricalReplayError(
                "PRICE_REQUIRED", "historical daily bars 부족"
            )
        period_start = prices[0].trade_date
        period_end = prices[-1].trade_date

        paper_account = self._ensure_owner_paper_account(
            owner_id, market_exchange=exchange_code.upper()
        )
        adapter = RuleBasedBacktestAdapter(specification, prices)
        fee_ratio, sell_tax_ratio = _cost_ratios(exchange_code)

        # 전략 payload에 max_order_amount가 없으면 cash*ratio(예: 10M*0.20=2M)가
        # 시스템 ResolvedRisk(max_order_amount/max_position_amount)를 초과한다.
        # PAPER는 UBA 오버레이를 쓰지 않고 시스템+사용자 한도만으로 cap 한다.
        max_order_amount = _paper_replay_buy_budget_cap(
            self._session,
            owner_user_id=owner_id,
            strategy_max_order_amount=strategy_max_order_amount,
        )

        identity_payload = {
            "kind": "PAPER_HISTORICAL_REPLAY",
            "strategy_definition_id": int(strategy_definition_id),
            "executable_hash": specification.get("executable_hash"),
            "symbol": symbol.upper(),
            "exchange_code": exchange_code.upper(),
            "period_start": str(period_start),
            "period_end": str(period_end),
            "paper_account_id": int(paper_account.account_id),
            "fee_ratio": str(fee_ratio),
            "sell_tax_ratio": str(sell_tax_ratio),
            "slippage_ratio": str(SLIPPAGE_RATIO),
            "holdout_policy": PAPER_REPLAY_HOLDOUT_POLICY,
            "fill_convention": FILL_CONVENTION,
            "order_exchange_code": "PAPER",
            "buy_budget_cap": "resolved_risk_without_uba",
            "buy_budget_cap_amount": (
                str(max_order_amount) if max_order_amount is not None else None
            ),
        }
        strategy_code = f"DEFINITION_{int(strategy_definition_id)}"
        existing = self._performance_repo.find_latest_matching(
            strategy_code=strategy_code,
            run_type=RUN_TYPE,
            market_code=exchange_code.upper(),
            symbol=symbol.upper(),
            period_start_date=period_start,
            period_end_date=period_end,
            parameter_payload=identity_payload,
        )
        if existing is not None and existing.status_code == (
            PerformanceRunStatus.COMPLETED.value
        ):
            metric = self._performance_repo.get_detail(
                run_id=int(existing.strategy_performance_run_id)
            )[1]
            return self._to_dict(
                existing,
                metric=metric,
                idempotent_replay=True,
            )

        if existing is not None:
            run = existing
            run.status_code = PerformanceRunStatus.RUNNING.value
            run.error_message = None
            self._session.commit()
        else:
            run = self._performance.create_run(
                strategy_code=strategy_code,
                run_type=RUN_TYPE,
                market_code=exchange_code.upper(),
                symbol=symbol.upper(),
                period_start_date=period_start,
                period_end_date=period_end,
                parameter_payload=identity_payload,
                strategy_id=int(strategy_definition_id),
                requested_by_user_id=int(actor_user_id),
            )

        run_id = int(run.strategy_performance_run_id)
        try:
            evidence = self._execute_bars(
                run_id=run_id,
                owner_id=owner_id,
                paper_account_id=int(paper_account.account_id),
                strategy_definition_id=int(strategy_definition_id),
                symbol=symbol.upper(),
                exchange_code=exchange_code.upper(),
                order_exchange_code="PAPER",
                adapter=adapter,
                prices=prices,
                warmup_bars=warmup_bars,
                cooldown_bars=cooldown_bars,
                max_order_amount=max_order_amount,
                position_ratio=adapter.config.position_ratio,
                market_exchange_code=exchange_code.upper(),
            )
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            self._performance_repo.fail_run(
                run_id=run_id,
                error_message=str(exc)[:2000],
            )
            raise

        metrics = evidence["metrics"]
        completed = self._performance.complete_run(
            run_id=int(run.strategy_performance_run_id),
            metrics=metrics,
            result_payload=evidence["result_payload"],
        )
        return self._to_dict(completed, metric=None, idempotent_replay=False)

    def _ensure_owner_paper_account(
        self, owner_id: int, *, market_exchange: str = "KRX"
    ):
        repo = PaperAccountRepository(self._session)
        market = str(market_exchange or "KRX").upper()
        if market in CRYPTO_EXCHANGES:
            existing = self._session.scalar(
                select(PaperAccount)
                .where(
                    PaperAccount.user_id == int(owner_id),
                    func.upper(PaperAccount.exchange_code) == "UPBIT",
                    PaperAccount.is_active.is_(True),
                    PaperAccount.deleted_at.is_(None),
                )
                .order_by(PaperAccount.account_id.asc())
                .limit(1)
            )
            if existing is not None:
                return existing
            return self._accounts.create_account(
                account_name=f"user-{owner_id}-upbit-crypto-paper-replay",
                initial_cash=Decimal("10000000"),
                currency_code="KRW",
                user_id=int(owner_id),
                is_default=False,
                exchange_code="UPBIT",
                broker_code="PAPER",
            )
        existing = repo.get_primary_for_user(owner_id)
        if existing is not None and existing.is_active:
            if str(existing.exchange_code or "").upper() in CRYPTO_EXCHANGES:
                existing = None
            else:
                return existing
        view = self._user_accounts.create_account(
            owner_id,
            account_type="PAPER",
            account_name=f"user-{owner_id}-stock-paper-replay",
            is_default=True,
        )
        account = repo.get_account(int(view.account_id))
        if account is None:
            raise PaperHistoricalReplayError(
                "PAPER_ACCOUNT_CREATE_FAILED", "Paper account 생성 실패"
            )
        return account

    def _execute_bars(
        self,
        *,
        run_id: int,
        owner_id: int,
        paper_account_id: int,
        strategy_definition_id: int,
        symbol: str,
        exchange_code: str,
        order_exchange_code: str,
        adapter: RuleBasedBacktestAdapter,
        prices: list[BacktestPrice],
        warmup_bars: int,
        cooldown_bars: int,
        max_order_amount: Decimal | None,
        position_ratio: Decimal,
        market_exchange_code: str,
    ) -> dict[str, Any]:
        in_position = False
        entry_price = ZERO
        entry_date: date | None = None
        entry_qty = ZERO
        cooldown_remaining = 0
        signals = {
            "BUY": 0,
            "SELL": 0,
            "STOP_LOSS": 0,
            "TAKE_PROFIT": 0,
            "MA_DEAD_CROSS": 0,
        }
        buy_orders = 0
        sell_orders = 0
        fills = 0
        closed: list[ReplayClosedTrade] = []
        equity_curve: list[tuple[date, Decimal]] = []
        fee_total = ZERO
        tax_total = ZERO
        slippage_total = ZERO
        blocked: list[dict[str, Any]] = []
        order_ids: list[int] = []

        initial_account = self._accounts._repository.get_account(paper_account_id)
        if initial_account is None:
            raise PaperHistoricalReplayError("PAPER_ACCOUNT_MISSING", "paper account 없음")
        initial_cash = _dec(initial_account.available_cash)

        for index, price in enumerate(prices):
            decision = evaluate_bar(
                adapter,
                prices,
                index,
                in_position=in_position,
                entry_price=entry_price,
                cooldown_remaining=cooldown_remaining,
                warmup_bars=warmup_bars,
            )
            if decision.skipped_cooldown and cooldown_remaining > 0:
                cooldown_remaining -= 1

            if decision.side == "BUY":
                signals["BUY"] += 1
                account = self._accounts._repository.get_account(paper_account_id)
                assert account is not None
                qty, _gross = _size_buy_quantity(
                    available_cash=_dec(account.available_cash),
                    price=decision.fill_price or ZERO,
                    position_ratio=position_ratio,
                    max_order_amount=max_order_amount,
                    exchange_code=market_exchange_code,
                )
                if qty <= ZERO:
                    blocked.append(
                        {
                            "date": str(decision.trade_date),
                            "reason": "ZERO_QUANTITY",
                        }
                    )
                else:
                    submitted = self._submit_and_fill(
                        run_id=run_id,
                        owner_id=owner_id,
                        paper_account_id=paper_account_id,
                        strategy_definition_id=strategy_definition_id,
                        symbol=symbol,
                        exchange_code=order_exchange_code,
                        market_exchange_code=market_exchange_code,
                        side=OrderSide.BUY,
                        quantity=qty,
                        price=decision.fill_price or ZERO,
                        reason=decision.reason,
                        trade_date=decision.trade_date,
                        index=index,
                    )
                    if submitted.get("filled"):
                        buy_orders += 1
                        fills += 1
                        order_ids.append(int(submitted["order_id"]))
                        in_position = True
                        entry_price = _dec(submitted["fill_price"])
                        entry_date = decision.trade_date
                        entry_qty = _dec(submitted["quantity"])
                        fee = _dec(submitted["fee"])
                        fee_total += fee
                        slippage_total += _dec(submitted["slippage"])
                        cooldown_remaining = cooldown_bars
                    else:
                        blocked.append(
                            {
                                "date": str(decision.trade_date),
                                "reason": submitted.get("reason_code"),
                            }
                        )
            elif decision.side == "SELL":
                if decision.reason == "MA_DEAD_CROSS":
                    signals["SELL"] += 1
                if decision.reason in signals:
                    signals[decision.reason] += 1
                submitted = self._submit_and_fill(
                    run_id=run_id,
                    owner_id=owner_id,
                    paper_account_id=paper_account_id,
                    strategy_definition_id=strategy_definition_id,
                    symbol=symbol,
                    exchange_code=order_exchange_code,
                    market_exchange_code=market_exchange_code,
                    side=OrderSide.SELL,
                    quantity=entry_qty,
                    price=decision.fill_price or ZERO,
                    reason=decision.reason,
                    trade_date=decision.trade_date,
                    index=index,
                    is_risk_reducing=True,
                )
                if submitted.get("filled"):
                    sell_orders += 1
                    fills += 1
                    order_ids.append(int(submitted["order_id"]))
                    exit_price = _dec(submitted["fill_price"])
                    fee = _dec(submitted["fee"])
                    tax = _dec(submitted["tax"])
                    fee_total += fee
                    tax_total += tax
                    slippage_total += _dec(submitted["slippage"])
                    entry_amount = entry_qty * entry_price
                    net = (
                        entry_qty * exit_price - fee - tax - entry_amount
                    ).quantize(Decimal("0.01"))
                    closed.append(
                        ReplayClosedTrade(
                            entry_date=entry_date or decision.trade_date,
                            exit_date=decision.trade_date,
                            quantity=entry_qty,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            fee_amount=fee,
                            tax_amount=tax,
                            slippage_amount=_dec(submitted["slippage"]),
                            net_profit_loss=net,
                            exit_reason=decision.reason,
                        )
                    )
                    in_position = False
                    entry_price = ZERO
                    entry_date = None
                    entry_qty = ZERO
                    cooldown_remaining = cooldown_bars
                else:
                    blocked.append(
                        {
                            "date": str(decision.trade_date),
                            "reason": submitted.get("reason_code"),
                            "message": submitted.get("message"),
                        }
                    )

            account = self._accounts._repository.get_account(paper_account_id)
            position = self._accounts._repository.get_position(
                account_id=paper_account_id,
                exchange_code=order_exchange_code,
                symbol=symbol,
            )
            qty_now = _dec(position.quantity) if position is not None else ZERO
            cash_now = _dec(account.available_cash) if account is not None else ZERO
            equity = cash_now + qty_now * price.close_price
            equity_curve.append((price.trade_date, equity.quantize(Decimal("0.01"))))

        account = self._accounts._repository.get_account(paper_account_id)
        position = self._accounts._repository.get_position(
            account_id=paper_account_id,
            exchange_code=order_exchange_code,
            symbol=symbol,
        )
        final_cash = _dec(account.available_cash) if account is not None else ZERO
        open_qty = _dec(position.quantity) if position is not None else ZERO
        avg_px = (
            _dec(position.average_entry_price) if position is not None else ZERO
        )
        last_close = prices[-1].close_price
        final_equity = (final_cash + open_qty * last_close).quantize(Decimal("0.01"))
        realized = _dec(account.realized_profit_loss) if account is not None else ZERO

        wins = [t for t in closed if t.net_profit_loss > ZERO]
        losses = [t for t in closed if t.net_profit_loss <= ZERO]
        trade_count = len(closed)
        win_rate = (
            Decimal(len(wins)) / Decimal(trade_count) * HUNDRED
            if trade_count
            else ZERO
        )
        gross_profit = sum((t.net_profit_loss for t in wins), ZERO)
        gross_loss = sum((t.net_profit_loss for t in losses), ZERO)
        profit_factor = (
            gross_profit / abs(gross_loss) if gross_loss != ZERO else None
        )
        total_return = (
            (final_equity - initial_cash) / initial_cash * HUNDRED
            if initial_cash > ZERO
            else ZERO
        )
        peak = initial_cash
        mdd = ZERO
        daily_returns: list[Decimal] = []
        prev = initial_cash
        for _d, eq in equity_curve:
            peak = max(peak, eq)
            if peak > ZERO:
                mdd = max(mdd, (peak - eq) / peak * HUNDRED)
            if prev > ZERO:
                daily_returns.append((eq - prev) / prev)
            prev = eq
        sharpe = _sharpe(daily_returns)

        cash_ok = final_cash >= ZERO
        oversell = open_qty < ZERO
        integrity_ok = (
            fills == buy_orders + sell_orders
            and not oversell
            and cash_ok
            and self._kiwoom_adapter_calls == 0
            and self._upbit_adapter_calls == 0
        )
        result_label = (
            "PAPER_VALIDATION_EXECUTED_NO_CANONICAL_ACCEPTANCE_POLICY"
            if integrity_ok
            else "INSUFFICIENT_EVIDENCE"
        )

        metrics = StrategyPerformanceMetrics(
            initial_capital=initial_cash,
            final_capital=final_equity,
            total_return_rate=total_return.quantize(Decimal("0.00000001")),
            annualized_return_rate=None,
            maximum_drawdown_rate=mdd.quantize(Decimal("0.00000001")),
            volatility_rate=None,
            sharpe_ratio=sharpe,
            sortino_ratio=None,
            win_rate=win_rate.quantize(Decimal("0.00000001")),
            profit_factor=profit_factor,
            total_trade_count=trade_count,
            winning_trade_count=len(wins),
            losing_trade_count=len(losses),
            average_profit_amount=(
                (sum((t.net_profit_loss for t in wins), ZERO) / Decimal(len(wins)))
                if wins
                else ZERO
            ),
            average_loss_amount=(
                (sum((t.net_profit_loss for t in losses), ZERO) / Decimal(len(losses)))
                if losses
                else ZERO
            ),
            gross_profit_amount=gross_profit,
            gross_loss_amount=gross_loss,
            net_profit_amount=(final_equity - initial_cash).quantize(Decimal("0.01")),
        )
        result_payload = {
            "paper_validation_id": run_id,
            "paper_account_id": paper_account_id,
            "bars": len(prices),
            "signals": signals,
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "fills": fills,
            "closed_trades": [
                {
                    "entry_date": str(t.entry_date),
                    "exit_date": str(t.exit_date),
                    "quantity": str(t.quantity),
                    "entry_price": str(t.entry_price),
                    "exit_price": str(t.exit_price),
                    "fee": str(t.fee_amount),
                    "tax": str(t.tax_amount),
                    "slippage": str(t.slippage_amount),
                    "net_pnl": str(t.net_profit_loss),
                    "exit_reason": t.exit_reason,
                }
                for t in closed
            ],
            "open_position": {
                "quantity": str(open_qty),
                "average_entry_price": str(avg_px),
            },
            "final_cash": str(final_cash),
            "realized_pnl": str(realized),
            "fee_total": str(fee_total),
            "tax_total": str(tax_total),
            "fee_ratio": str(_cost_ratios(market_exchange_code)[0]),
            "sell_tax_ratio": str(_cost_ratios(market_exchange_code)[1]),
            "cost_model": (
                "UPBIT_TAKER"
                if str(market_exchange_code).upper() in CRYPTO_EXCHANGES
                else "KRX_COMMISSION_SELL_TAX"
            ),
            "slippage_total": str(slippage_total),
            "order_ids": order_ids,
            "blocked": blocked,
            "integrity_ok": integrity_ok,
            "acceptance_policy": ACCEPTANCE_POLICY,
            "holdout_policy": PAPER_REPLAY_HOLDOUT_POLICY,
            "fill_convention": FILL_CONVENTION,
            "kiwoom_adapter_calls": self._kiwoom_adapter_calls,
            "upbit_adapter_calls": self._upbit_adapter_calls,
            "result": result_label,
        }
        return {"metrics": metrics, "result_payload": result_payload}

    def _submit_and_fill(
        self,
        *,
        run_id: int,
        owner_id: int,
        paper_account_id: int,
        strategy_definition_id: int,
        symbol: str,
        exchange_code: str,
        market_exchange_code: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        reason: str,
        trade_date: date,
        index: int,
        is_risk_reducing: bool = False,
    ) -> dict[str, Any]:
        if quantity <= ZERO:
            return {"filled": False, "reason_code": "ZERO_QUANTITY"}
        idempotency_key = (
            f"PAPER_REPLAY:{run_id}:{trade_date.isoformat()}:{side.value}:{index}"
        )
        account = self._accounts._repository.get_account(paper_account_id)
        cash = _dec(account.available_cash) if account is not None else ZERO
        result = OrderExecutionService(self._session).submit(
            OrderExecutionCommand(
                account_id=paper_account_id,
                broker_code="PAPER",
                exchange_code=exchange_code,
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price,
                strategy_code=f"DEFINITION_{strategy_definition_id}",
                account_number=f"PAPER-{paper_account_id}",
                skip_risk_checks=False,
                available_cash=cash,
                portfolio_value=cash,
                metadata_payload={
                    "environment": "PAPER",
                    "source": "PAPER_HISTORICAL_REPLAY",
                    "paper_validation_id": run_id,
                    "signal_reason": reason,
                    "replay_index": index,
                },
                actor="PAPER_HISTORICAL_REPLAY",
                order_source="AUTO",
                environment="PAPER",
                user_id=owner_id,
                owner_user_id=owner_id,
                idempotency_key=idempotency_key,
                is_risk_reducing=is_risk_reducing,
            )
        )
        if not result.allowed or result.order_id is None:
            return {
                "filled": False,
                "reason_code": result.reason_code,
                "message": result.sanitized_message,
            }
        if result.outbox_id is None:
            return {
                "filled": False,
                "reason_code": "OUTBOX_MISSING",
                "order_id": int(result.order_id),
            }
        worker = OrderOutboxWorker(
            session_factory=get_session_factory(),
            dispatcher=OrderOutboxDispatcher(adapter=PaperBrokerAdapter()),
            worker_id="PAPER_HISTORICAL_REPLAY",
            paper_only=True,
        )
        worker.dispatch_one(int(result.outbox_id))
        self._session.expire_all()
        fill = PaperOutboxFillService(self._session).fill_accepted_order(
            int(result.order_id),
            actor="PAPER_HISTORICAL_REPLAY",
        )
        if not fill.filled:
            return {
                "filled": False,
                "reason_code": fill.reason_code,
                "order_id": int(result.order_id),
            }
        gross = (quantity * price).quantize(Decimal("0.01"))
        fee_ratio, sell_tax_ratio = _cost_ratios(market_exchange_code)
        fee = (gross * fee_ratio).quantize(Decimal("0.01"))
        tax = (
            (gross * sell_tax_ratio).quantize(Decimal("0.01"))
            if side == OrderSide.SELL
            else ZERO
        )
        cost = fee + tax
        if cost > ZERO:
            try:
                self._accounts.apply_cash_delta(
                    account_id=paper_account_id,
                    delta=-cost,
                )
            except PaperAccountError:
                return {
                    "filled": False,
                    "reason_code": "COST_CASH_INSUFFICIENT",
                    "order_id": int(result.order_id),
                }
        self._session.commit()
        return {
            "filled": True,
            "order_id": int(result.order_id),
            "quantity": quantity,
            "fill_price": price,
            "fee": fee,
            "tax": tax,
            "slippage": ZERO,
        }

    def _to_dict(self, run, *, metric, idempotent_replay: bool) -> dict[str, Any]:
        payload = dict(run.result_payload or {})
        return {
            "paper_validation_id": int(run.strategy_performance_run_id),
            "backtest_id_reused": False,
            "status_code": run.status_code,
            "idempotent_replay": idempotent_replay,
            "strategy_id": run.strategy_id,
            "paper_account_id": payload.get("paper_account_id"),
            "symbol": run.symbol,
            "period_start": str(run.period_start_date),
            "period_end": str(run.period_end_date),
            "result_payload": payload,
            "metric_present": metric is not None,
        }
