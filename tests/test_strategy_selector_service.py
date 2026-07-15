from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.performance.selector_models import (
    StrategySelectionCandidate,
    StrategySelectionStatus,
)
from stock_platform.performance.selector_service import (
    LlmStrategySelectionService,
)


def _candidate():
    return StrategySelectionCandidate(
        rank=1,
        strategy_code="MA_CROSS_V1",
        strategy_performance_run_id=10,
        market_code="KRX",
        symbol="005930",
        run_type="WALK_FORWARD",
        score=Decimal("0.85"),
        total_return_rate=Decimal("0.15"),
        maximum_drawdown_rate=Decimal("0.08"),
        sharpe_ratio=Decimal("1.4"),
        sortino_ratio=Decimal("1.8"),
        win_rate=Decimal("0.60"),
        profit_factor=Decimal("1.7"),
        total_trade_count=40,
    )


def test_parse_valid_llm_decision() -> None:
    decision = (
        LlmStrategySelectionService
        ._parse_decision(
            response={
                "selected_strategy_code": (
                    "MA_CROSS_V1"
                ),
                "selected_performance_run_id": 10,
                "confidence_score": 0.8,
                "reason": "stable",
                "risk_notes": ["mdd"],
                "alternatives": [],
            },
            candidates=[_candidate()],
            model_name="qwen3.5:4b",
        )
    )

    assert decision.status == (
        StrategySelectionStatus.SELECTED
    )
    assert decision.confidence_score == Decimal(
        "0.8"
    )


def test_fallback_selects_top_candidate() -> None:
    decision = (
        LlmStrategySelectionService
        ._fallback(
            candidates=[_candidate()],
            model_name="qwen3.5:4b",
            error="timeout",
        )
    )

    assert decision.status == (
        StrategySelectionStatus.FALLBACK
    )
    assert decision.selected_strategy_code == (
        "MA_CROSS_V1"
    )
