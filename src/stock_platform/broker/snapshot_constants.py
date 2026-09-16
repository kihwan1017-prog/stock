"""STEP 8-5-17/18 — Broker Snapshot Binding / Freshness 상수."""

from __future__ import annotations

from enum import StrEnum


class BrokerSnapshotStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ORPHAN = "ORPHAN"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    INVALID = "INVALID"
    # STEP 8-5-18 — ORPHAN 관리 수명주기
    REBIND_PENDING = "REBIND_PENDING"
    REBOUND = "REBOUND"
    RETIRED = "RETIRED"
    PURGED = "PURGED"


# 운영 조회·Settlement·Risk 에서 사용 금지
NON_OPERATIONAL_SNAPSHOT_STATUSES = frozenset(
    {
        BrokerSnapshotStatus.ORPHAN.value,
        BrokerSnapshotStatus.STALE.value,
        BrokerSnapshotStatus.SUPERSEDED.value,
        BrokerSnapshotStatus.INVALID.value,
        BrokerSnapshotStatus.REBIND_PENDING.value,
        BrokerSnapshotStatus.REBOUND.value,
        BrokerSnapshotStatus.RETIRED.value,
        BrokerSnapshotStatus.PURGED.value,
    }
)

# 관리자 ORPHAN 큐에 노출
ORPHAN_MANAGEABLE_STATUSES = frozenset(
    {
        BrokerSnapshotStatus.ORPHAN.value,
        BrokerSnapshotStatus.REBIND_PENDING.value,
    }
)
