from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from stock_platform.performance.backtest_models import (
    BacktestPerformanceInput,
)


class BacktestResultPayloadAdapter:
    """
    기존 백테스트 서비스의 dict 결과를 성과 저장 입력으로 변환한다.

    프로젝트의 실제 키가 다르면 KEY_ALIASES만 조정한다.
    """

    KEY_ALIASES = {
        "initial_capital": (
            "initial_capital",
            "starting_capital",
            "start_balance",
        ),
        "final_capital": (
            "final_capital",
            "ending_capital",
            "end_balance",
        ),
        "total_trade_count": (
            "total_trade_count",
            "trade_count",
            "total_trades",
        ),
        "winning_trade_count": (
            "winning_trade_count",
            "win_count",
            "winning_trades",
        ),
        "losing_trade_count": (
            "losing_trade_count",
            "loss_count",
            "losing_trades",
        ),
        "gross_profit_amount": (
            "gross_profit_amount",
            "gross_profit",
            "total_profit",
        ),
        "gross_loss_amount": (
            "gross_loss_amount",
            "gross_loss",
            "total_loss",
        ),
        "maximum_drawdown_rate": (
            "maximum_drawdown_rate",
            "max_drawdown_rate",
            "mdd",
        ),
        "annualized_return_rate": (
            "annualized_return_rate",
            "annual_return_rate",
            "cagr",
        ),
        "volatility_rate": (
            "volatility_rate",
            "volatility",
        ),
        "sharpe_ratio": (
            "sharpe_ratio",
            "sharpe",
        ),
        "sortino_ratio": (
            "sortino_ratio",
            "sortino",
        ),
        "profit_factor": (
            "profit_factor",
        ),
    }

    @classmethod
    def from_payload(
        cls,
        *,
        strategy_code: str,
        market_code: str,
        symbol: str | None,
        period_start_date: date,
        period_end_date: date,
        parameter_payload: dict[str, Any],
        result_payload: dict[str, Any],
    ) -> BacktestPerformanceInput:
        return BacktestPerformanceInput(
            strategy_code=strategy_code,
            market_code=market_code,
            symbol=symbol,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            parameter_payload=parameter_payload,
            initial_capital=cls._required_decimal(
                result_payload,
                "initial_capital",
            ),
            final_capital=cls._required_decimal(
                result_payload,
                "final_capital",
            ),
            total_trade_count=cls._required_int(
                result_payload,
                "total_trade_count",
            ),
            winning_trade_count=cls._required_int(
                result_payload,
                "winning_trade_count",
            ),
            losing_trade_count=cls._required_int(
                result_payload,
                "losing_trade_count",
            ),
            gross_profit_amount=cls._required_decimal(
                result_payload,
                "gross_profit_amount",
            ),
            gross_loss_amount=cls._required_decimal(
                result_payload,
                "gross_loss_amount",
            ),
            maximum_drawdown_rate=(
                cls._required_decimal(
                    result_payload,
                    "maximum_drawdown_rate",
                )
            ),
            annualized_return_rate=(
                cls._optional_decimal(
                    result_payload,
                    "annualized_return_rate",
                )
            ),
            volatility_rate=cls._optional_decimal(
                result_payload,
                "volatility_rate",
            ),
            sharpe_ratio=cls._optional_decimal(
                result_payload,
                "sharpe_ratio",
            ),
            sortino_ratio=cls._optional_decimal(
                result_payload,
                "sortino_ratio",
            ),
            profit_factor=cls._optional_decimal(
                result_payload,
                "profit_factor",
            ),
            result_payload=result_payload,
        )

    @classmethod
    def _find(
        cls,
        payload: dict[str, Any],
        canonical_key: str,
    ):
        for key in cls.KEY_ALIASES[canonical_key]:
            value = payload.get(key)
            if value is not None:
                return value
        return None

    @classmethod
    def _required_decimal(
        cls,
        payload: dict[str, Any],
        canonical_key: str,
    ) -> Decimal:
        value = cls._find(
            payload,
            canonical_key,
        )
        if value is None:
            raise ValueError(
                f"Missing backtest result field: "
                f"{canonical_key}"
            )
        return Decimal(str(value))

    @classmethod
    def _optional_decimal(
        cls,
        payload: dict[str, Any],
        canonical_key: str,
    ) -> Decimal | None:
        value = cls._find(
            payload,
            canonical_key,
        )
        if value is None:
            return None
        return Decimal(str(value))

    @classmethod
    def _required_int(
        cls,
        payload: dict[str, Any],
        canonical_key: str,
    ) -> int:
        value = cls._find(
            payload,
            canonical_key,
        )
        if value is None:
            raise ValueError(
                f"Missing backtest result field: "
                f"{canonical_key}"
            )
        return int(value)
