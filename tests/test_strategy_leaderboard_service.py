from datetime import date
from types import SimpleNamespace


class FakeRankingService:
    def rank(self, **kwargs):
        return [
            SimpleNamespace(
                rank=1,
                strategy_code="A",
                market_code="KRX",
                symbol="005930",
                run_type="BACKTEST",
                score=1,
                total_return_rate=0.1,
                maximum_drawdown_rate=0.05,
                sharpe_ratio=1.2,
                sortino_ratio=1.5,
                win_rate=0.6,
                profit_factor=1.8,
                total_trade_count=20,
                strategy_performance_run_id=1,
            )
        ]


class FakeRepository:
    def create_snapshot(self, **kwargs):
        return kwargs


def test_generates_snapshot() -> None:
    from stock_platform.performance.leaderboard_service import (
        StrategyLeaderboardService,
    )

    service = StrategyLeaderboardService.__new__(
        StrategyLeaderboardService
    )
    service._ranking = FakeRankingService()
    service._repository = FakeRepository()

    result = service.generate_snapshot(
        snapshot_date=date(2026, 7, 16),
        run_type="backtest",
        market_code="krx",
        symbol="005930",
        minimum_trade_count=10,
        limit=20,
    )

    assert result["run_type"] == "BACKTEST"
    assert result["market_code"] == "KRX"
    assert len(result["ranking"]) == 1
