"""STEP 8-5-17 — Snapshot Hash / Freshness 유틸."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus


def compute_snapshot_hash(
    *,
    broker_code: str,
    account_number: str,
    deposit_amount: Decimal | Any,
    available_order_amount: Decimal | Any,
    total_evaluation_amount: Decimal | Any,
    synchronized_at: datetime | None,
) -> str:
    payload = "|".join(
        [
            str(broker_code or "").upper(),
            str(account_number or ""),
            str(deposit_amount or "0"),
            str(available_order_amount or "0"),
            str(total_evaluation_amount or "0"),
            synchronized_at.isoformat() if synchronized_at else "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotFreshnessResult:
    ok: bool
    reason: str | None
    age_seconds: float | None
    max_age_seconds: int
    snapshot_status: str | None
    snapshot_generation: int | None
    snapshot_hash: str | None


def evaluate_snapshot_freshness(
    *,
    snapshot: Any | None,
    expected_uba_id: int,
    expected_broker_code: str,
    max_age_seconds: int,
    now: datetime | None = None,
) -> SnapshotFreshnessResult:
    """Settlement/Recovery용 Fail-Closed Freshness 검사."""

    max_age = max(1, int(max_age_seconds))
    if snapshot is None:
        return SnapshotFreshnessResult(
            ok=False,
            reason="BROKER_SNAPSHOT_MISSING",
            age_seconds=None,
            max_age_seconds=max_age,
            snapshot_status=None,
            snapshot_generation=None,
            snapshot_hash=None,
        )

    status = str(getattr(snapshot, "snapshot_status", "") or "")
    generation = getattr(snapshot, "snapshot_generation", None)
    snap_hash = getattr(snapshot, "snapshot_hash", None)
    uba_id = getattr(snapshot, "user_broker_account_id", None)
    broker = str(getattr(snapshot, "broker_code", "") or "").upper()

    if uba_id is None or int(uba_id) != int(expected_uba_id):
        return SnapshotFreshnessResult(
            ok=False,
            reason="SNAPSHOT_UBA_MISMATCH",
            age_seconds=None,
            max_age_seconds=max_age,
            snapshot_status=status or None,
            snapshot_generation=int(generation) if generation else None,
            snapshot_hash=str(snap_hash) if snap_hash else None,
        )
    if broker != expected_broker_code.upper():
        return SnapshotFreshnessResult(
            ok=False,
            reason="SNAPSHOT_BROKER_MISMATCH",
            age_seconds=None,
            max_age_seconds=max_age,
            snapshot_status=status or None,
            snapshot_generation=int(generation) if generation else None,
            snapshot_hash=str(snap_hash) if snap_hash else None,
        )
    if status != BrokerSnapshotStatus.ACTIVE.value:
        return SnapshotFreshnessResult(
            ok=False,
            reason=f"SNAPSHOT_STATUS_{status or 'UNKNOWN'}",
            age_seconds=None,
            max_age_seconds=max_age,
            snapshot_status=status or None,
            snapshot_generation=int(generation) if generation else None,
            snapshot_hash=str(snap_hash) if snap_hash else None,
        )

    moment = now or datetime.now(timezone.utc)
    snap_time = (
        getattr(snapshot, "snapshot_time", None)
        or getattr(snapshot, "synchronized_at", None)
    )
    if snap_time is None:
        return SnapshotFreshnessResult(
            ok=False,
            reason="STALE_BROKER_SNAPSHOT",
            age_seconds=None,
            max_age_seconds=max_age,
            snapshot_status=status,
            snapshot_generation=int(generation) if generation else None,
            snapshot_hash=str(snap_hash) if snap_hash else None,
        )
    if snap_time.tzinfo is None:
        snap_time = snap_time.replace(tzinfo=timezone.utc)
    age = (moment - snap_time).total_seconds()
    if age > max_age:
        return SnapshotFreshnessResult(
            ok=False,
            reason="STALE_BROKER_SNAPSHOT",
            age_seconds=age,
            max_age_seconds=max_age,
            snapshot_status=status,
            snapshot_generation=int(generation) if generation else None,
            snapshot_hash=str(snap_hash) if snap_hash else None,
        )
    return SnapshotFreshnessResult(
        ok=True,
        reason=None,
        age_seconds=age,
        max_age_seconds=max_age,
        snapshot_status=status,
        snapshot_generation=int(generation) if generation else None,
        snapshot_hash=str(snap_hash) if snap_hash else None,
    )
