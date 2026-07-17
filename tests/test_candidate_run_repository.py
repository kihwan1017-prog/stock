from datetime import date
from decimal import Decimal

from stock_platform.screener.models import (
    CandidateScore,
    RuleResult,
    ScoreBreakdown,
)


def test_candidate_score_payload_shape() -> None:
    rules = RuleResult(
        liquidity=True,
        trade_value=True,
        volume_surge=True,
        trend_alignment=True,
        rsi_range=True,
        week52_position=True,
        atr_acceptable=True,
        tradable=True,
        macd_positive=True,
        breakout=True,
        rejection_reasons=(),
    )
    breakdown = ScoreBreakdown(
        liquidity=Decimal("10"),
        trade_value=Decimal("10"),
        volume=Decimal("15"),
        trend=Decimal("15"),
        rsi=Decimal("10"),
        macd=Decimal("10"),
        week52=Decimal("15"),
        breakout=Decimal("5"),
        volatility=Decimal("10"),
    )
    score = CandidateScore(
        exchange_code="KRX",
        symbol="005930",
        trade_date=date(2026, 7, 13),
        total_score=Decimal("100"),
        rules=rules,
        breakdown=breakdown,
    )
    assert score.rules.passed is True
    assert score.breakdown.total == Decimal("100")
    assert score.rules.to_dict()["rejection_reasons"] == []
