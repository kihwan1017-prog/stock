from decimal import Decimal
from types import SimpleNamespace

from stock_platform.risk.allocation_service import (
    CandidatePositionPlanService,
)


class FakeAnalysisRepository:
    def get_latest_run(self, *, exchange_code: str):
        return SimpleNamespace(
            analysis_run_id=11,
        )

    def get_results(self, analysis_run_id: int):
        return [
            SimpleNamespace(
                rank_no=1,
                symbol="005930",
                ai_score=Decimal("90"),
                action_code="REVIEW",
                confidence=Decimal("0.80"),
            ),
            SimpleNamespace(
                rank_no=2,
                symbol="000660",
                ai_score=Decimal("85"),
                action_code="WATCH",
                confidence=Decimal("0.70"),
            ),
        ]


class FakeRiskRepository:
    def get_policy(self, policy_id: int):
        return SimpleNamespace(
            policy_id=policy_id,
            is_active=True,
        )


class FakePriceService:
    def get_latest(
        self,
        *,
        exchange_code: str,
        symbol: str,
    ):
        return SimpleNamespace(
            close_price=Decimal("100000")
        )


class FakeRiskService:
    def __init__(self) -> None:
        self.calls = 0

    def create_and_save_position_plan(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            position_plan_id=self.calls,
            approved=True,
            reason_code="APPROVED",
            quantity=Decimal("10"),
            order_amount=Decimal("1000000"),
            entry_price=Decimal("100000"),
            stop_loss_price=Decimal("95000"),
            take_profit_price=Decimal("110000"),
            trailing_stop_ratio=Decimal("0.03"),
            maximum_loss_amount=Decimal("50000"),
        )


def test_creates_top_five_position_plans() -> None:
    service = CandidatePositionPlanService.__new__(
        CandidatePositionPlanService
    )
    service._analysis_repository = (
        FakeAnalysisRepository()
    )
    service._risk_repository = (
        FakeRiskRepository()
    )
    service._price_service = FakePriceService()
    service._risk_service = FakeRiskService()

    result = service.create_plans(
        exchange_code="KRX",
        policy_id=1,
        portfolio_value=Decimal("10000000"),
        available_cash=Decimal("5000000"),
        current_position_count=0,
        limit=5,
        minimum_ai_score=Decimal("80"),
        minimum_confidence=Decimal("0.5"),
    )

    assert result.analysis_run_id == 11
    assert result.planned_count == 2
    assert result.approved_count == 2
    assert result.remaining_cash == Decimal(
        "3000000"
    )
    assert [
        item.symbol
        for item in result.candidates
    ] == [
        "005930",
        "000660",
    ]


def test_filters_by_action_and_score() -> None:
    service = CandidatePositionPlanService.__new__(
        CandidatePositionPlanService
    )
    service._analysis_repository = (
        FakeAnalysisRepository()
    )
    service._risk_repository = (
        FakeRiskRepository()
    )
    service._price_service = FakePriceService()
    service._risk_service = FakeRiskService()

    result = service.create_plans(
        exchange_code="KRX",
        policy_id=1,
        portfolio_value=Decimal("10000000"),
        available_cash=Decimal("5000000"),
        current_position_count=0,
        limit=5,
        minimum_ai_score=Decimal("88"),
        minimum_confidence=Decimal("0.5"),
        allowed_actions={"REVIEW"},
    )

    assert result.planned_count == 1
    assert result.candidates[0].symbol == "005930"
