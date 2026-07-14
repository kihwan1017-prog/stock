from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from stock_platform.backtest.models import (
    BacktestPrice,
    BacktestResult,
    BacktestSummary,
    BacktestTrade,
)
from stock_platform.backtest.strategy import (
    MovingAverageCrossStrategy,
)


ZERO = Decimal("0")
ONE = Decimal("1")


class BacktestValidationError(ValueError):
    pass


class BacktestEngine:
    """단일 종목 일봉 백테스트 엔진."""

    def __init__(
        self,
        strategy: MovingAverageCrossStrategy,
    ) -> None:
        self._strategy = strategy

    def run(
        self,
        *,
        exchange_code: str,
        symbol: str,
        prices: list[BacktestPrice],
        initial_capital: Decimal,
        fee_ratio: Decimal = Decimal("0.00015"),
        sell_tax_ratio: Decimal = Decimal("0.0018"),
        slippage_ratio: Decimal = Decimal("0"),
    ) -> BacktestResult:
        self._validate(
            prices=prices,
            initial_capital=initial_capital,
            fee_ratio=fee_ratio,
            sell_tax_ratio=sell_tax_ratio,
            slippage_ratio=slippage_ratio,
        )

        cash = initial_capital
        quantity = ZERO
        entry_price = ZERO
        entry_date = None
        entry_reason = ""
        trades: list[BacktestTrade] = []
        equity_curve: list[tuple] = []
        peak_equity = initial_capital
        maximum_drawdown = ZERO

        for index, price in enumerate(prices):
            if quantity == ZERO:
                should_enter, reason = (
                    self._strategy.should_enter(
                        prices=prices,
                        index=index,
                    )
                )

                if should_enter:
                    fill_price = (
                        price.close_price
                        * (ONE + slippage_ratio)
                    )
                    budget = (
                        cash
                        * self._strategy.config.position_ratio
                    )
                    quantity = (
                        budget / fill_price
                    ).quantize(
                        Decimal("0.00000001"),
                        rounding=ROUND_DOWN,
                    )

                    if quantity > ZERO:
                        gross_amount = quantity * fill_price
                        fee = gross_amount * fee_ratio
                        total_cost = gross_amount + fee

                        if total_cost <= cash:
                            cash -= total_cost
                            entry_price = fill_price
                            entry_date = price.trade_date
                            entry_reason = reason
                        else:
                            quantity = ZERO

            else:
                should_exit, reason = (
                    self._strategy.should_exit(
                        prices=prices,
                        index=index,
                        entry_price=entry_price,
                    )
                )

                if should_exit:
                    if reason == "STOP_LOSS":
                        raw_exit_price = (
                            entry_price
                            * (
                                ONE
                                - self._strategy.config.stop_loss_ratio
                            )
                        )
                    elif reason == "TAKE_PROFIT":
                        raw_exit_price = (
                            entry_price
                            * (
                                ONE
                                + self._strategy.config.take_profit_ratio
                            )
                        )
                    else:
                        raw_exit_price = price.close_price

                    exit_price = (
                        raw_exit_price
                        * (ONE - slippage_ratio)
                    )
                    gross_proceeds = quantity * exit_price
                    fee = gross_proceeds * fee_ratio
                    tax = gross_proceeds * sell_tax_ratio
                    net_proceeds = gross_proceeds - fee - tax

                    entry_amount = quantity * entry_price
                    gross_profit_loss = (
                        gross_proceeds - entry_amount
                    )
                    net_profit_loss = (
                        net_proceeds - entry_amount
                    )
                    return_rate = (
                        net_profit_loss
                        / entry_amount
                        * Decimal("100")
                    )

                    cash += net_proceeds

                    trades.append(
                        BacktestTrade(
                            entry_date=entry_date,
                            exit_date=price.trade_date,
                            quantity=quantity,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            gross_profit_loss=(
                                gross_profit_loss.quantize(
                                    Decimal("0.01")
                                )
                            ),
                            fee_amount=fee.quantize(
                                Decimal("0.01")
                            ),
                            tax_amount=tax.quantize(
                                Decimal("0.01")
                            ),
                            net_profit_loss=(
                                net_profit_loss.quantize(
                                    Decimal("0.01")
                                )
                            ),
                            return_rate=return_rate.quantize(
                                Decimal("0.0001")
                            ),
                            entry_reason=entry_reason,
                            exit_reason=reason,
                        )
                    )

                    quantity = ZERO
                    entry_price = ZERO
                    entry_date = None
                    entry_reason = ""

            equity = cash + quantity * price.close_price
            equity_curve.append(
                (
                    price.trade_date,
                    equity.quantize(Decimal("0.01")),
                )
            )

            peak_equity = max(peak_equity, equity)
            drawdown = (
                (peak_equity - equity)
                / peak_equity
                * Decimal("100")
            )
            maximum_drawdown = max(
                maximum_drawdown,
                drawdown,
            )

        if quantity > ZERO:
            last = prices[-1]
            exit_price = (
                last.close_price * (ONE - slippage_ratio)
            )
            gross_proceeds = quantity * exit_price
            fee = gross_proceeds * fee_ratio
            tax = gross_proceeds * sell_tax_ratio
            net_proceeds = gross_proceeds - fee - tax
            entry_amount = quantity * entry_price
            net_profit_loss = net_proceeds - entry_amount

            cash += net_proceeds

            trades.append(
                BacktestTrade(
                    entry_date=entry_date,
                    exit_date=last.trade_date,
                    quantity=quantity,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    gross_profit_loss=(
                        gross_proceeds - entry_amount
                    ).quantize(Decimal("0.01")),
                    fee_amount=fee.quantize(
                        Decimal("0.01")
                    ),
                    tax_amount=tax.quantize(
                        Decimal("0.01")
                    ),
                    net_profit_loss=net_profit_loss.quantize(
                        Decimal("0.01")
                    ),
                    return_rate=(
                        net_profit_loss
                        / entry_amount
                        * Decimal("100")
                    ).quantize(Decimal("0.0001")),
                    entry_reason=entry_reason,
                    exit_reason="END_OF_PERIOD",
                )
            )

            equity_curve[-1] = (
                last.trade_date,
                cash.quantize(Decimal("0.01")),
            )

        final_equity = cash.quantize(Decimal("0.01"))
        total_profit_loss = (
            final_equity - initial_capital
        ).quantize(Decimal("0.01"))
        total_return_rate = (
            total_profit_loss
            / initial_capital
            * Decimal("100")
        ).quantize(Decimal("0.0001"))

        win_count = sum(
            1
            for trade in trades
            if trade.net_profit_loss > ZERO
        )
        loss_count = sum(
            1
            for trade in trades
            if trade.net_profit_loss <= ZERO
        )
        trade_count = len(trades)

        win_rate = (
            Decimal(win_count)
            / Decimal(trade_count)
            * Decimal("100")
            if trade_count
            else ZERO
        ).quantize(Decimal("0.0001"))

        average_trade_return_rate = (
            sum(
                (
                    trade.return_rate
                    for trade in trades
                ),
                ZERO,
            )
            / Decimal(trade_count)
            if trade_count
            else ZERO
        ).quantize(Decimal("0.0001"))

        summary = BacktestSummary(
            initial_capital=initial_capital,
            final_equity=final_equity,
            total_return_rate=total_return_rate,
            maximum_drawdown_rate=(
                maximum_drawdown.quantize(
                    Decimal("0.0001")
                )
            ),
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            total_profit_loss=total_profit_loss,
            average_trade_return_rate=(
                average_trade_return_rate
            ),
        )

        return BacktestResult(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=prices[0].trade_date,
            end_date=prices[-1].trade_date,
            summary=summary,
            trades=trades,
            equity_curve=equity_curve,
        )

    @staticmethod
    def _validate(
        *,
        prices: list[BacktestPrice],
        initial_capital: Decimal,
        fee_ratio: Decimal,
        sell_tax_ratio: Decimal,
        slippage_ratio: Decimal,
    ) -> None:
        if not prices:
            raise BacktestValidationError(
                "prices must not be empty"
            )

        if initial_capital <= ZERO:
            raise BacktestValidationError(
                "initial_capital must be greater than zero"
            )

        for name, value in {
            "fee_ratio": fee_ratio,
            "sell_tax_ratio": sell_tax_ratio,
            "slippage_ratio": slippage_ratio,
        }.items():
            if value < ZERO or value > Decimal("0.20"):
                raise BacktestValidationError(
                    f"{name} must be between 0 and 0.20"
                )
