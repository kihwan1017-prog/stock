"""Legacy STEP33 session contract — market package removed in STEP56."""

import pytest

pytestmark = pytest.mark.skip(
    reason="STEP56: stock_platform.market package removed; use markets/"
)
