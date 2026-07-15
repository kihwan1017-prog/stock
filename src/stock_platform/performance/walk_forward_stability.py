from __future__ import annotations

from decimal import Decimal

from stock_platform.performance.walk_forward_entities import (
    WalkForwardWindowMetricEntity,
)


ZERO = Decimal("0")


class WalkForwardStabilityAnalyzer:
    @staticmethod
    def analyze(
        windows: list[WalkForwardWindowMetricEntity],
    ) -> dict:
        if not windows:
            return {
                "window_count": 0,
                "positive_window_count": 0,
                "negative_window_count": 0,
                "positive_window_rate": "0",
                "average_return_rate": "0",
                "return_rate_stddev": "0",
                "worst_window_return_rate": "0",
                "best_window_return_rate": "0",
                "maximum_drawdown_rate": "0",
                "stability_score": "0",
            }

        returns = [
            Decimal(item.total_return_rate)
            for item in windows
        ]
        positive_count = sum(
            1 for value in returns if value > ZERO
        )
        negative_count = sum(
            1 for value in returns if value < ZERO
        )
        average_return = (
            sum(returns, ZERO)
            / Decimal(len(returns))
        )

        variance = (
            sum(
                (
                    value - average_return
                ) ** 2
                for value in returns
            )
            / Decimal(len(returns))
        )
        stddev = variance.sqrt()

        positive_rate = (
            Decimal(positive_count)
            / Decimal(len(returns))
        )
        worst_return = min(returns)
        best_return = max(returns)
        maximum_drawdown = max(
            Decimal(item.maximum_drawdown_rate)
            for item in windows
        )

        stability_score = max(
            ZERO,
            (
                positive_rate
                - stddev
                - maximum_drawdown
            ),
        ).quantize(Decimal("0.00000001"))

        return {
            "window_count": len(windows),
            "positive_window_count": positive_count,
            "negative_window_count": negative_count,
            "positive_window_rate": str(positive_rate),
            "average_return_rate": str(average_return),
            "return_rate_stddev": str(stddev),
            "worst_window_return_rate": str(
                worst_return
            ),
            "best_window_return_rate": str(
                best_return
            ),
            "maximum_drawdown_rate": str(
                maximum_drawdown
            ),
            "stability_score": str(stability_score),
        }
