from __future__ import annotations

from stock_platform.backtest.rebalancing_models import (
    RebalancingBacktestResult,
)


class RebalancingBacktestReportBuilder:
    @staticmethod
    def build(result: RebalancingBacktestResult) -> str:
        summary = result.summary

        lines = [
            (
                f"정기 리밸런싱 백테스트 "
                f"{result.start_date}~{result.end_date}"
            ),
            f"주기={result.frequency.value}",
            (
                f"초기자본={summary.initial_capital}, "
                f"최종자산={summary.final_equity}, "
                f"총수익률={summary.total_return_rate}%, "
                f"CAGR={summary.cagr}%"
            ),
            (
                f"MDD={summary.maximum_drawdown_rate}%, "
                f"변동성={summary.annualized_volatility}%, "
                f"Sharpe={summary.sharpe_ratio}, "
                f"Sortino={summary.sortino_ratio}, "
                f"Calmar={summary.calmar_ratio}"
            ),
            (
                f"거래수={summary.trade_count}, "
                f"리밸런싱수={summary.rebalance_count}"
            ),
            "",
            "최종 비중",
        ]

        for key, weight in sorted(
            result.final_weights.items()
        ):
            lines.append(f"{key}: {weight}")

        return "\n".join(lines)
