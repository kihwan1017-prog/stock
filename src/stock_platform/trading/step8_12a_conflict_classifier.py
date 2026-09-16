"""STEP 8-12A — Recovery Conflict 조회 전용 분류 (상태 변경 금지)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


CLASS_CURRENT_ACTIVE = "CURRENT_ACTIVE_CONFLICT"
CLASS_STATE_MISMATCH = "CURRENT_STATE_MISMATCH"
CLASS_HISTORICAL = "HISTORICAL_STALE_CONFLICT"
CLASS_TEST = "TEST_OR_NON_LIVE_ARTIFACT"
CLASS_DUP = "DUPLICATE_OR_ORPHAN"
CLASS_UNKNOWN = "UNCLASSIFIED"

TERMINAL_REMOTE = frozenset(
    {
        "DONE",
        "CANCEL",
        "CANCELLED",
        "CANCELED",
        "FAILED",
        "EXPIRED",
    }
)
OPENISH_REMOTE = frozenset(
    {
        "WAIT",
        "WATCH",
        "OPEN",
        "NEW",
        "PENDING",
        "PARTIAL",
        "PARTIALLY_FILLED",
    }
)


@dataclass(slots=True)
class ConflictClassification:
    conflict_id: int
    classification: str
    conflict_type: str
    review_status: str
    broker_code: str
    market: str | None
    side: str | None
    external_status: str | None
    masked_uuid: str | None
    linked_internal_order_id: int | None
    remaining_quantity: str | None
    executed_quantity: str | None
    detected_at: str | None
    last_refreshed_at: str | None
    age_hours: float | None
    broker_open_match: bool
    db_open_match: bool
    remote_lookup_status: str | None
    affects_live_trading: bool
    release_blocker: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _age_hours(detected_at: datetime | None, now: datetime) -> float | None:
    if detected_at is None:
        return None
    dt = detected_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def classify_conflict(
    *,
    conflict_id: int,
    conflict_type: str,
    review_status: str,
    broker_code: str,
    market_code: str | None,
    side_code: str | None,
    external_status: str | None,
    external_order_id_masked: str | None,
    linked_internal_order_id: int | None,
    remaining_quantity: Any,
    executed_quantity: Any,
    detected_at: datetime | None,
    last_remote_checked_at: datetime | None,
    paper_account_id: int | None,
    now: datetime | None = None,
    broker_open_uuids: set[str] | None = None,
    db_open_order_ids: set[int] | None = None,
    external_order_id: str | None = None,
    remote_lookup_status: str | None = None,
    duplicate_of_ids: list[int] | None = None,
) -> ConflictClassification:
    """단건 Conflict를 A~E 분류로 매핑. DB/Broker 상태를 변경하지 않는다."""

    now = now or datetime.now(timezone.utc)
    remote = _upper(external_status)
    rem_qty = Decimal(str(remaining_quantity or 0))
    broker_open = broker_open_uuids or set()
    db_open = db_open_order_ids or set()
    uuid_raw = (external_order_id or "").strip()
    broker_match = bool(uuid_raw and uuid_raw in broker_open)
    db_match = bool(
        linked_internal_order_id is not None
        and int(linked_internal_order_id) in db_open
    )

    notes: list[str] = []
    classification = CLASS_UNKNOWN
    affects = False
    blocker = False

    if paper_account_id is not None:
        classification = CLASS_TEST
        notes.append("paper_account_id set")
    elif duplicate_of_ids:
        classification = CLASS_DUP
        notes.append(f"duplicate_of={duplicate_of_ids}")
    elif broker_match or (
        remote in OPENISH_REMOTE
        and rem_qty > 0
        and remote_lookup_status in {"wait", "watch", "open"}
    ):
        classification = CLASS_CURRENT_ACTIVE
        affects = True
        blocker = True
        notes.append("remote still open or broker open match")
    elif remote in OPENISH_REMOTE and rem_qty > 0:
        # 스냅샷은 wait이나 현재 broker open 목록에는 없음
        if remote_lookup_status in TERMINAL_REMOTE or remote_lookup_status in {
            "done",
            "cancel",
            "cancelled",
            "canceled",
        }:
            classification = CLASS_STATE_MISMATCH
            notes.append(
                f"snapshot={remote} remote_now={remote_lookup_status}"
            )
            # 종료 확정이면 실거래 직접 충돌은 낮음
            affects = False
            blocker = False
        elif remote_lookup_status in {"not_found", "404"}:
            classification = CLASS_HISTORICAL
            notes.append("wait snapshot but order not found remotely")
            affects = False
            blocker = False
        elif remote_lookup_status is None and not broker_match:
            # list_orders(wait)=0 이고 단건 조회 미실행 → mismatch 경고
            classification = CLASS_STATE_MISMATCH
            notes.append(
                "snapshot wait/open but not in current broker open list"
            )
            affects = False
            blocker = False
        else:
            classification = CLASS_UNKNOWN
            affects = True
            blocker = True
            notes.append("openish remote unresolved")
    elif remote in TERMINAL_REMOTE:
        classification = CLASS_HISTORICAL
        notes.append("terminal remote status")
        affects = False
        blocker = False
    elif linked_internal_order_id is not None and db_match:
        classification = CLASS_CURRENT_ACTIVE
        affects = True
        blocker = True
        notes.append("linked internal order still open")
    else:
        classification = CLASS_UNKNOWN
        affects = True
        blocker = True
        notes.append("unable to classify safely")

    return ConflictClassification(
        conflict_id=int(conflict_id),
        classification=classification,
        conflict_type=str(conflict_type),
        review_status=str(review_status),
        broker_code=str(broker_code).upper(),
        market=market_code,
        side=side_code,
        external_status=external_status,
        masked_uuid=external_order_id_masked,
        linked_internal_order_id=linked_internal_order_id,
        remaining_quantity=(
            str(remaining_quantity) if remaining_quantity is not None else None
        ),
        executed_quantity=(
            str(executed_quantity) if executed_quantity is not None else None
        ),
        detected_at=detected_at.isoformat() if detected_at else None,
        last_refreshed_at=(
            last_remote_checked_at.isoformat()
            if last_remote_checked_at
            else None
        ),
        age_hours=_age_hours(detected_at, now),
        broker_open_match=broker_match,
        db_open_match=db_match,
        remote_lookup_status=remote_lookup_status,
        affects_live_trading=affects,
        release_blocker=blocker,
        notes="; ".join(notes),
    )


def summarize_classifications(
    rows: list[ConflictClassification],
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    blockers = [r for r in rows if r.release_blocker]
    for row in rows:
        counts[row.classification] = counts.get(row.classification, 0) + 1
    return {
        "total": len(rows),
        "counts": counts,
        "release_blocker_count": len(blockers),
        "release_blocker_ids": [r.conflict_id for r in blockers],
        "affects_live_trading_count": sum(
            1 for r in rows if r.affects_live_trading
        ),
    }
