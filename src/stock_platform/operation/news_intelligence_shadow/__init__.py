"""News Intelligence Shadow package."""

from __future__ import annotations

from stock_platform.operation.news_intelligence_shadow.entities import (
    NewsIntelligenceShadowDecisionEntity,
)
from stock_platform.operation.news_intelligence_shadow.policy import (
    PIPELINE_VERSION,
)

__all__ = [
    "NewsIntelligenceShadowDecisionEntity",
    "PIPELINE_VERSION",
]
