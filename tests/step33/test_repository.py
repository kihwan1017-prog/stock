"""Legacy STEP33 in-memory market package removed in STEP56.

본선 시세는 `stock_platform.markets` 를 사용한다.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="STEP56: stock_platform.market package removed; use markets/"
)
