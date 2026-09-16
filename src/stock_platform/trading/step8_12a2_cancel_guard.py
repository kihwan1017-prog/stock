"""STEP 8-12A-2 — CANCEL Conflict Ignore 가드 (allowlist + zero-fill)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

# 8-12A-1 기준 UBA 58 Historical CANCEL_CONFIRMED 22건
# (#3/#4 CURRENT_STATE_MISMATCH는 별도 Refresh 후 Ignore)
STEP8_12A2_CANCEL_ALLOWLIST: frozenset[int] = frozenset(
    {
        1,
        2,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
    }
)

STEP8_12A2_MISMATCH_IDS: frozenset[int] = frozenset({3, 4})

STEP8_12A2_DONE_ALLOWLIST: frozenset[int] = frozenset(range(5, 25))

IGNORE_NOTE = "REMOTE_CANCEL_CONFIRMED_ZERO_FILL_REVIEWED_2026_07_27"

# Broker 조회가 이보다 오래되면 stale로 간주
STALE_AFTER = timedelta(hours=24)


@dataclass(slots=True)
class CancelIgnoreVerdict:
    conflict_id: int
    ok: bool
    bucket: str  # SAFE_CANCEL_TO_IGNORE | NEEDS_REVIEW | BLOCKED_NOT_ALLOWLISTED | ALREADY_RESOLVED
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "ok": self.ok,
            "bucket": self.bucket,
            "reasons": list(self.reasons),
        }


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _is_zero(value: Any) -> bool:
    try:
        return _dec(value) == 0
    except Exception:  # noqa: BLE001
        return False


def _remote_cancel(status: Any) -> bool:
    return str(status or "").strip().lower() in {
        "cancel",
        "cancelled",
        "canceled",
    }


def _is_stale(last_checked: datetime | None, *, now: datetime | None = None) -> bool:
    if last_checked is None:
        return True
    current = now or datetime.now(timezone.utc)
    checked = last_checked
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return (current - checked) > STALE_AFTER


def evaluate_safe_cancel_ignore(
    *,
    conflict_id: int,
    allowlist: frozenset[int],
    remote_status: Any,
    executed_volume: Any,
    remaining_volume: Any,
    paid_fee: Any,
    trades_count: Any,
    broker_open: bool,
    has_internal_execution: bool,
    has_position_impact: bool,
    last_remote_checked_at: datetime | None,
    review_status: str | None = None,
    linked_internal_order_id: int | None = None,
    now: datetime | None = None,
) -> CancelIgnoreVerdict:
    """SAFE_CANCEL_TO_IGNORE 조건 전수 검사. allowlist 외는 즉시 차단."""

    reasons: list[str] = []
    resolved = str(review_status or "").upper() in {
        "IGNORED",
        "APPROVED_IMPORT",
        "REMOTE_DISAPPEARED",
        "RESOLVED",
        "HISTORICAL_PRESERVED",
    }
    if resolved:
        return CancelIgnoreVerdict(
            conflict_id=conflict_id,
            ok=False,
            bucket="ALREADY_RESOLVED",
            reasons=["already_resolved"],
        )

    if int(conflict_id) not in allowlist:
        return CancelIgnoreVerdict(
            conflict_id=conflict_id,
            ok=False,
            bucket="BLOCKED_NOT_ALLOWLISTED",
            reasons=["conflict_id_not_in_allowlist"],
        )

    if not _remote_cancel(remote_status):
        reasons.append(f"remote_status_not_cancel:{remote_status}")
    if not _is_zero(executed_volume):
        reasons.append(f"executed_volume_nonzero:{executed_volume}")
    if not _is_zero(paid_fee):
        reasons.append(f"paid_fee_nonzero:{paid_fee}")
    try:
        trades = int(trades_count or 0)
    except (TypeError, ValueError):
        trades = -1
        reasons.append(f"trades_count_invalid:{trades_count}")
    if trades != 0:
        reasons.append(f"trades_count_nonzero:{trades_count}")
    if broker_open:
        reasons.append("currently_broker_open")
    if has_internal_execution:
        reasons.append("internal_execution_exists")
    if has_position_impact:
        reasons.append("position_or_balance_impact")
    if linked_internal_order_id is not None:
        # 내부 주문만 있고 execution 없으면 별도 검토 — CANCEL zero-fill에서는 보수 차단
        reasons.append(f"linked_internal_order:{linked_internal_order_id}")
    if _is_stale(last_remote_checked_at, now=now):
        reasons.append("broker_state_stale")

    # remaining_volume: cancel+zero-fill이면 0 또는 요청량과 일치 가능
    # 보수적으로 remaining이 음수만 아니면 통과 (executed=0 이미 검사)
    try:
        rem = _dec(remaining_volume)
        if rem < 0:
            reasons.append(f"remaining_volume_negative:{remaining_volume}")
    except Exception:  # noqa: BLE001
        reasons.append(f"remaining_volume_invalid:{remaining_volume}")

    if reasons:
        return CancelIgnoreVerdict(
            conflict_id=conflict_id,
            ok=False,
            bucket="NEEDS_REVIEW",
            reasons=reasons,
        )
    return CancelIgnoreVerdict(
        conflict_id=conflict_id,
        ok=True,
        bucket="SAFE_CANCEL_TO_IGNORE",
        reasons=[],
    )


def assert_only_allowlisted_mutation(
    conflict_id: int,
    *,
    allowlist: frozenset[int],
) -> None:
    if int(conflict_id) not in allowlist:
        raise ValueError(
            f"BLOCKED: conflict_id={conflict_id} not in allowlist"
        )
