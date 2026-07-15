from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class LoadedStrategyRuntime:
    deployment_id: int
    strategy_code: str
    market_code: str
    symbol: str | None
    parameter_payload: dict[str, Any]
    loaded_at: datetime


@dataclass(frozen=True, slots=True)
class StrategyRuntimeReloadResult:
    changed: bool
    previous_deployment_id: int | None
    current_deployment_id: int | None
    strategy_code: str | None
    message: str
    reloaded_at: datetime
