from __future__ import annotations

from stock_platform.backtest.walk_forward_models import (
    WalkForwardResult,
)


class WalkForwardReportBuilder:
    @staticmethod
    def build(result: WalkForwardResult) -> str:
        summary = result.summary

        lines = [
            (
                f"{result.exchange_code} {result.symbol} "
                f"워크포워드 검증"
            ),
            (
                f"기간={result.start_date}~{result.end_date}, "
                f"학습={result.train_months}개월, "
                f"검증={result.test_months}개월"
            ),
            (
                f"전체 창={summary.window_count}, "
                f"성공={summary.completed_window_count}, "
                f"실패={summary.failed_window_count}"
            ),
            (
                f"평균 검증 수익률="
                f"{summary.average_test_return_rate}%, "
                f"복리 검증 수익률="
                f"{summary.compounded_test_return_rate}%, "
                f"평균 검증 MDD="
                f"{summary.average_test_maximum_drawdown_rate}%"
            ),
            (
                f"수익 창 비율="
                f"{summary.profitable_window_rate}%, "
                f"파라미터 변경 횟수="
                f"{summary.parameter_change_count}"
            ),
            "",
        ]

        for item in result.windows:
            parameters = item.selected_parameters
            lines.append(
                (
                    f"[{item.window_no}] "
                    f"학습 {item.train_start_date}~"
                    f"{item.train_end_date}, "
                    f"검증 {item.test_start_date}~"
                    f"{item.test_end_date}, "
                    f"MA={parameters.short_window}/"
                    f"{parameters.long_window}, "
                    f"손절={parameters.stop_loss_ratio}, "
                    f"익절={parameters.take_profit_ratio}, "
                    f"비중={parameters.position_ratio}, "
                    f"학습점수={item.train_score}, "
                    f"검증수익률={item.test_return_rate}%, "
                    f"검증MDD="
                    f"{item.test_maximum_drawdown_rate}%"
                )
            )

        return "\n".join(lines)
