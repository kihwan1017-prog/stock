from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from stock_platform.performance.dashboard_service import StrategyPerformanceDashboardService

def test_selection_to_dict():
    selection = SimpleNamespace(
        strategy_selection_run_id=1, market_code="KRX", symbol="005930",
        run_type="WALK_FORWARD", model_name="qwen3.5:4b",
        status_code="SELECTED", selected_strategy_code="MA_CROSS_V1",
        selected_performance_run_id=10, confidence_score=Decimal("0.8"),
        reason="stable", risk_notes=["mdd"], alternatives=["RSI_V1"],
        created_at=datetime.now(timezone.utc),
    )
    result = StrategyPerformanceDashboardService._selection_to_dict(selection)
    assert result["selected_strategy_code"] == "MA_CROSS_V1"
    assert result["confidence_score"] == "0.8"
