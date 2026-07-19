from decimal import Decimal

from stock_platform.risk.legacy_gate import InMemoryRiskGate
from stock_platform.risk.models import RiskLimits, RiskRequest


def test_large_order_rejected() -> None:
    gate = InMemoryRiskGate(
        RiskLimits(
            Decimal("100"),
            Decimal("500"),
            Decimal("50"),
            3,
        )
    )
    decision = gate.evaluate(
        RiskRequest(
            Decimal("101"),
            Decimal("0"),
            Decimal("0"),
            0,
            True,
        )
    )
    assert not decision.allowed
    assert "MAX_ORDER_AMOUNT_EXCEEDED" in decision.reasons
