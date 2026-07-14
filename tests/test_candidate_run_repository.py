from datetime import date
from decimal import Decimal

from stock_platform.screener.models import CandidateScore, RuleResult, ScoreBreakdown


def test_candidate_score_payload_shape() -> None:
    rules = RuleResult(
        volume_surge=True,
        trend_alignment=True,
        rsi_range=True,
        macd_positive=True,
        breakout=True,
        atr_acceptable=True,
    )
    breakdown = ScoreBreakdown(
        volume=Decimal("20"),
        trend=Decimal("20"),
        rsi=Decimal("15"),
        macd=Decimal("20"),
        breakout=Decimal("15"),
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
