from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_DOWN
from math import sqrt

from sqlalchemy.orm import Session

from stock_platform.backtest.rebalancing_models import (
    RebalancingAsset,
    RebalancingBacktestResult,
    RebalancingFrequency,
    RebalancingSnapshot,
    RebalancingSummary,
    RebalancingTrade,
)
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import PriceDailyService


ZERO = Decimal("0")
ONE = Decimal("1")


class PortfolioRebalancingBacktestService:
    """고정 목표비중 기반 정기 리밸런싱 백테스트."""

    def __init__(self, session: Session) -> None:
        self._price_service = PriceDailyService(
            PriceDailyRepository(session)
        )

    def run(
        self,
        *,
        assets: list[RebalancingAsset],
        start_date: date,
        end_date: date,
        initial_capital: Decimal,
        frequency: RebalancingFrequency,
        fee_ratio: Decimal,
        sell_tax_ratio: Decimal,
        slippage_ratio: Decimal,
        rebalance_threshold: Decimal = Decimal("0"),
    ) -> RebalancingBacktestResult:
        self._validate(
            assets=assets,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            fee_ratio=fee_ratio,
            sell_tax_ratio=sell_tax_ratio,
            slippage_ratio=slippage_ratio,
            rebalance_threshold=rebalance_threshold,
        )

        prices = self._load_prices(
            assets=assets,
            start_date=start_date,
            end_date=end_date,
        )
        trade_dates = sorted(
            set.intersection(
                *[
                    set(rows.keys())
                    for rows in prices.values()
                ]
            )
        )

        if not trade_dates:
            raise ValueError("No common trade dates found")

        cash = initial_capital
        quantities: dict[str, Decimal] = defaultdict(lambda: ZERO)
        trades: list[RebalancingTrade] = []
        snapshots: list[RebalancingSnapshot] = []
        rebalance_count = 0
        previous_rebalance_date: date | None = None

        for current_date in trade_dates:
            rebalance_now = (
                previous_rebalance_date is None
                or self._is_rebalance_date(
                    previous=previous_rebalance_date,
                    current=current_date,
                    frequency=frequency,
                )
            )

            if rebalance_now:
                current_equity = self._total_equity(
                    cash=cash,
                    quantities=quantities,
                    prices=prices,
                    current_date=current_date,
                )

                sell_trades = []
                buy_trades = []

                for asset in assets:
                    key = self._key(asset.exchange_code, asset.symbol)
                    price = prices[key][current_date]
                    current_value = quantities[key] * price
                    target_value = current_equity * asset.target_weight
                    difference = target_value - current_value

                    if current_equity > ZERO:
                        drift = abs(difference) / current_equity
                        if drift < rebalance_threshold:
                            continue

                    if difference < ZERO:
                        sell_trades.append(
                            (asset, price, -difference)
                        )
                    elif difference > ZERO:
                        buy_trades.append(
                            (asset, price, difference)
                        )

                for asset, price, amount in sell_trades:
                    key = self._key(asset.exchange_code, asset.symbol)
                    quantity = min(
                        quantities[key],
                        (amount / price).quantize(
                            Decimal("0.00000001"),
                            rounding=ROUND_DOWN,
                        ),
                    )
                    if quantity <= ZERO:
                        continue

                    gross = quantity * price
                    slippage = gross * slippage_ratio
                    fee = gross * fee_ratio
                    tax_ratio = (
                        ZERO
                        if asset.exchange_code.upper() == "UPBIT"
                        else sell_tax_ratio
                    )
                    tax = gross * tax_ratio
                    net = gross - slippage - fee - tax

                    quantities[key] -= quantity
                    cash += net

                    trades.append(
                        RebalancingTrade(
                            trade_date=current_date,
                            exchange_code=asset.exchange_code.upper(),
                            symbol=asset.symbol.upper(),
                            side="SELL",
                            quantity=quantity,
                            price=price,
                            gross_amount=gross.quantize(Decimal("0.01")),
                            fee_amount=fee.quantize(Decimal("0.01")),
                            tax_amount=tax.quantize(Decimal("0.01")),
                            slippage_amount=slippage.quantize(Decimal("0.01")),
                        )
                    )

                for asset, price, requested_amount in buy_trades:
                    key = self._key(asset.exchange_code, asset.symbol)
                    max_gross = cash / (
                        ONE + fee_ratio + slippage_ratio
                    )
                    gross = min(requested_amount, max_gross)

                    quantity = (
                        gross / price
                    ).quantize(
                        Decimal("0.00000001"),
                        rounding=ROUND_DOWN,
                    )
                    if quantity <= ZERO:
                        continue

                    gross = quantity * price
                    slippage = gross * slippage_ratio
                    fee = gross * fee_ratio
                    total_cost = gross + slippage + fee

                    if total_cost > cash:
                        continue

                    quantities[key] += quantity
                    cash -= total_cost

                    trades.append(
                        RebalancingTrade(
                            trade_date=current_date,
                            exchange_code=asset.exchange_code.upper(),
                            symbol=asset.symbol.upper(),
                            side="BUY",
                            quantity=quantity,
                            price=price,
                            gross_amount=gross.quantize(Decimal("0.01")),
                            fee_amount=fee.quantize(Decimal("0.01")),
                            tax_amount=ZERO,
                            slippage_amount=slippage.quantize(Decimal("0.01")),
                        )
                    )

                previous_rebalance_date = current_date
                rebalance_count += 1

            position_value = self._position_value(
                quantities=quantities,
                prices=prices,
                current_date=current_date,
            )
            snapshots.append(
                RebalancingSnapshot(
                    trade_date=current_date,
                    cash=cash.quantize(Decimal("0.01")),
                    position_value=position_value.quantize(Decimal("0.01")),
                    total_equity=(cash + position_value).quantize(
                        Decimal("0.01")
                    ),
                    rebalance_executed=rebalance_now,
                )
            )

        summary = self._build_summary(
            initial_capital=initial_capital,
            snapshots=snapshots,
            trade_count=len(trades),
            rebalance_count=rebalance_count,
        )

        final_weights = self._final_weights(
            assets=assets,
            quantities=quantities,
            prices=prices,
            final_date=trade_dates[-1],
            final_equity=summary.final_equity,
        )

        return RebalancingBacktestResult(
            start_date=trade_dates[0],
            end_date=trade_dates[-1],
            frequency=frequency,
            summary=summary,
            trades=trades,
            snapshots=snapshots,
            final_weights=final_weights,
        )

    def _load_prices(
        self,
        *,
        assets: list[RebalancingAsset],
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[date, Decimal]]:
        result: dict[str, dict[date, Decimal]] = {}

        for asset in assets:
            rows = self._price_service.get_between(
                exchange_code=asset.exchange_code.upper(),
                symbol=asset.symbol.upper(),
                start_date=start_date,
                end_date=end_date,
            )
            if not rows:
                raise ValueError(
                    f"Price data not found: "
                    f"{asset.exchange_code}/{asset.symbol}"
                )

            result[self._key(
                asset.exchange_code,
                asset.symbol,
            )] = {
                row.trade_date: Decimal(row.close_price)
                for row in rows
            }

        return result

    @staticmethod
    def _is_rebalance_date(
        *,
        previous: date,
        current: date,
        frequency: RebalancingFrequency,
    ) -> bool:
        if frequency == RebalancingFrequency.WEEKLY:
            return current.isocalendar()[:2] != previous.isocalendar()[:2]

        if frequency == RebalancingFrequency.MONTHLY:
            return (current.year, current.month) != (
                previous.year,
                previous.month,
            )

        if frequency == RebalancingFrequency.QUARTERLY:
            return (
                current.year,
                (current.month - 1) // 3,
            ) != (
                previous.year,
                (previous.month - 1) // 3,
            )

        if frequency == RebalancingFrequency.SEMIANNUAL:
            return (
                current.year,
                (current.month - 1) // 6,
            ) != (
                previous.year,
                (previous.month - 1) // 6,
            )

        return current.year != previous.year

    @staticmethod
    def _position_value(
        *,
        quantities: dict[str, Decimal],
        prices: dict[str, dict[date, Decimal]],
        current_date: date,
    ) -> Decimal:
        return sum(
            (
                quantities[key] * rows[current_date]
                for key, rows in prices.items()
            ),
            ZERO,
        )

    @classmethod
    def _total_equity(
        cls,
        *,
        cash: Decimal,
        quantities: dict[str, Decimal],
        prices: dict[str, dict[date, Decimal]],
        current_date: date,
    ) -> Decimal:
        return cash + cls._position_value(
            quantities=quantities,
            prices=prices,
            current_date=current_date,
        )

    @staticmethod
    def _build_summary(
        *,
        initial_capital: Decimal,
        snapshots: list[RebalancingSnapshot],
        trade_count: int,
        rebalance_count: int,
    ) -> RebalancingSummary:
        equities = [row.total_equity for row in snapshots]
        final_equity = equities[-1]
        total_profit_loss = final_equity - initial_capital
        total_return_rate = (
            total_profit_loss / initial_capital * Decimal("100")
        )

        years = max(
            Decimal(
                str(
                    (snapshots[-1].trade_date - snapshots[0].trade_date).days
                    / 365.25
                )
            ),
            Decimal("0.0027379"),
        )
        cagr = (
            Decimal(
                str(
                    float(final_equity / initial_capital)
                    ** (1 / float(years))
                )
            )
            - ONE
        ) * Decimal("100")

        peak = equities[0]
        maximum_drawdown = ZERO
        daily_returns: list[Decimal] = []

        for index, equity in enumerate(equities):
            peak = max(peak, equity)
            if peak > ZERO:
                maximum_drawdown = max(
                    maximum_drawdown,
                    (peak - equity) / peak * Decimal("100"),
                )

            if index > 0 and equities[index - 1] > ZERO:
                daily_returns.append(
                    equity / equities[index - 1] - ONE
                )

        volatility = PortfolioRebalancingBacktestService._stddev(
            daily_returns
        ) * Decimal(str(sqrt(252))) * Decimal("100")

        average_return = (
            sum(daily_returns, ZERO) / Decimal(len(daily_returns))
            if daily_returns
            else ZERO
        )
        return_std = (
            PortfolioRebalancingBacktestService._stddev(daily_returns)
        )
        downside = [value for value in daily_returns if value < ZERO]
        downside_std = (
            PortfolioRebalancingBacktestService._stddev(downside)
        )

        sharpe = (
            average_return / return_std * Decimal(str(sqrt(252)))
            if return_std > ZERO
            else ZERO
        )
        sortino = (
            average_return / downside_std * Decimal(str(sqrt(252)))
            if downside_std > ZERO
            else ZERO
        )
        calmar = (
            cagr / maximum_drawdown
            if maximum_drawdown > ZERO
            else ZERO
        )

        return RebalancingSummary(
            initial_capital=initial_capital,
            final_equity=final_equity.quantize(Decimal("0.01")),
            total_profit_loss=total_profit_loss.quantize(Decimal("0.01")),
            total_return_rate=total_return_rate.quantize(Decimal("0.0001")),
            cagr=cagr.quantize(Decimal("0.0001")),
            maximum_drawdown_rate=maximum_drawdown.quantize(
                Decimal("0.0001")
            ),
            annualized_volatility=volatility.quantize(
                Decimal("0.0001")
            ),
            sharpe_ratio=sharpe.quantize(Decimal("0.0001")),
            sortino_ratio=sortino.quantize(Decimal("0.0001")),
            calmar_ratio=calmar.quantize(Decimal("0.0001")),
            trade_count=trade_count,
            rebalance_count=rebalance_count,
        )

    @staticmethod
    def _stddev(values: list[Decimal]) -> Decimal:
        if len(values) < 2:
            return ZERO

        mean = sum(values, ZERO) / Decimal(len(values))
        variance = sum(
            ((value - mean) ** 2 for value in values),
            ZERO,
        ) / Decimal(len(values) - 1)

        return Decimal(str(float(variance) ** 0.5))

    @staticmethod
    def _final_weights(
        *,
        assets: list[RebalancingAsset],
        quantities: dict[str, Decimal],
        prices: dict[str, dict[date, Decimal]],
        final_date: date,
        final_equity: Decimal,
    ) -> dict[str, Decimal]:
        if final_equity <= ZERO:
            return {}

        return {
            PortfolioRebalancingBacktestService._key(
                asset.exchange_code,
                asset.symbol,
            ): (
                quantities[
                    PortfolioRebalancingBacktestService._key(
                        asset.exchange_code,
                        asset.symbol,
                    )
                ]
                * prices[
                    PortfolioRebalancingBacktestService._key(
                        asset.exchange_code,
                        asset.symbol,
                    )
                ][final_date]
                / final_equity
            ).quantize(Decimal("0.000001"))
            for asset in assets
        }

    @staticmethod
    def _key(exchange_code: str, symbol: str) -> str:
        return f"{exchange_code.upper()}:{symbol.upper()}"

    @staticmethod
    def _validate(
        *,
        assets: list[RebalancingAsset],
        start_date: date,
        end_date: date,
        initial_capital: Decimal,
        fee_ratio: Decimal,
        sell_tax_ratio: Decimal,
        slippage_ratio: Decimal,
        rebalance_threshold: Decimal,
    ) -> None:
        if not assets:
            raise ValueError("assets must not be empty")
        if len(assets) > 50:
            raise ValueError("asset count must not exceed 50")
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        if initial_capital <= ZERO:
            raise ValueError("initial_capital must be greater than zero")

        total_weight = sum(
            (item.target_weight for item in assets),
            ZERO,
        )
        if total_weight > ONE:
            raise ValueError("total target weight must not exceed 1")

        seen: set[tuple[str, str]] = set()
        for item in assets:
            if item.target_weight <= ZERO:
                raise ValueError(
                    "target_weight must be greater than zero"
                )
            key = (
                item.exchange_code.upper(),
                item.symbol.upper(),
            )
            if key in seen:
                raise ValueError(
                    f"duplicate asset: {key[0]}/{key[1]}"
                )
            seen.add(key)

        for name, value in {
            "fee_ratio": fee_ratio,
            "sell_tax_ratio": sell_tax_ratio,
            "slippage_ratio": slippage_ratio,
            "rebalance_threshold": rebalance_threshold,
        }.items():
            if value < ZERO or value > Decimal("0.20"):
                raise ValueError(
                    f"{name} must be between 0 and 0.20"
                )
