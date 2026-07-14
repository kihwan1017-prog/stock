from __future__ import annotations

from stock_platform.backtest.grid_models import (
    BacktestGridResult,
)


class BacktestGridReportBuilder:
    """파라미터 최적화 후보 결과를 텍스트로 요약한다."""

    @staticmethod
    def build(result: BacktestGridResult) -> str:
        lines = [
            (
                f"{result.exchange_code} "
                f"{result.symbol} 파라미터 조합 결과"
            ),
            (
                f"전체={result.combination_count}, "
                f"성공={result.success_count}, "
                f"실패={result.failed_count}"
            ),
            "",
        ]

        for item in result.top_results:
            lines.append(
                (
                    f"{item.rank_no}위 "
                    f"run_id={item.backtest_run_id}, "
                    f"MA={item.short_window}/"
                    f"{item.long_window}, "
                    f"손절={item.stop_loss_ratio}, "
                    f"익절={item.take_profit_ratio}, "
                    f"비중={item.position_ratio}, "
                    f"수익률={item.total_return_rate}%, "
                    f"MDD={item.maximum_drawdown_rate}%, "
                    f"승률={item.win_rate}%, "
                    f"점수={item.score}"
                )
            )

        return "\n".join(lines)
