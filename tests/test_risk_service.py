"""Legacy RiskService persistence API tests.

현재 `stock_platform.risk.service.RiskService`는 주문 한도 평가용
dataclass 서비스로 단순화되어 있어, 이전 persistence API 테스트는
보류한다. STEP38에서 risk_engine/risk 통합 시 재작성한다.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "RiskService persistence API removed; "
        "rewrite in STEP38 risk package consolidation"
    )
)


def test_create_policy() -> None:
    assert False


def test_create_and_save_position_plan() -> None:
    assert False
