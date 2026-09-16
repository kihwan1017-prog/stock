"""STEP 8-5-6 — Instance Identity for Distributed Lock Owner."""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class RecoveryInstanceIdentity:
    instance_id: str
    hostname: str
    process_id: int
    startup_uuid: str
    started_at: datetime

    def masked(self) -> str:
        # ADMIN 표시용 — hostname 일부만
        host = self.hostname[:12] if self.hostname else "host"
        return f"{host}:…:{self.startup_uuid[:8]}"


_IDENTITY: RecoveryInstanceIdentity | None = None


def get_recovery_instance_identity(
    *,
    override: str | None = None,
) -> RecoveryInstanceIdentity:
    """프로세스 수명 동안 유지되는 Owner ID."""

    global _IDENTITY
    if override:
        now = datetime.now(timezone.utc)
        return RecoveryInstanceIdentity(
            instance_id=override,
            hostname="override",
            process_id=os.getpid(),
            startup_uuid=override[-12:],
            started_at=now,
        )
    if _IDENTITY is not None:
        return _IDENTITY

    hostname = socket.gethostname() or "unknown"
    pid = os.getpid()
    startup = uuid.uuid4().hex
    started = datetime.now(timezone.utc)
    instance_id = f"stock-platform:{hostname}:{pid}:{startup}"
    _IDENTITY = RecoveryInstanceIdentity(
        instance_id=instance_id,
        hostname=hostname,
        process_id=pid,
        startup_uuid=startup,
        started_at=started,
    )
    return _IDENTITY


def reset_recovery_instance_identity_for_tests() -> None:
    """테스트 격리용."""

    global _IDENTITY
    _IDENTITY = None
