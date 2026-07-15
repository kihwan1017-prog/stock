from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class KillSwitchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    status: KillSwitchStatus
    reason: str | None
    activated_by: str | None
    activated_at: datetime | None
    deactivated_by: str | None
    deactivated_at: datetime | None
