"""Legacy STEP33 sync tests — market package removed in STEP56."""

import pytest

pytestmark = pytest.mark.skip(
    reason="STEP56: stock_platform.market package removed; use markets/"
)
