"""STEP 8-15 — DONE Conflict History Preserve 가드 (allowlist + 사전 조건)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# 운영자 승인 DONE 20건 (#5–#24)
STEP8_15_PRESERVE_ALLOWLIST: frozenset[int] = frozenset(range(5, 25))

PRESERVE_REASON = (
    "HISTORICAL_REMOTE_DONE_POSITION_RECONCILED_NO_IMPORT_REQUIRED"
)

ALLOWED_CLASSIFICATIONS = frozenset({"POSITION_RECONCILABLE"})
BLOCKED_CLASSIFICATIONS = frozenset(
    {"IMPORT_REQUIRED", "UNSAFE", "MISSING_EXECUTION", "MISSING_ORDER_ONLY"}
)


@dataclass(slots=True)
class PreserveHistoryVerdict:
    conflict_id: int
    ok: bool
    bucket: str
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


def evaluate_preserve_history(
    *,
    conflict_id: int,
    allowlist: frozenset[int],
    review_status: str | None,
    remote_status: Any,
    classification: str | None,
    broker_open: bool,
    db_open: bool,
    position_impact: bool,
    balance_impact: bool,
) -> PreserveHistoryVerdict:
    """preserve-history 사전 조건. allowlist 외·조건 미충족은 차단."""

    reasons: list[str] = []
    status = str(review_status or "").upper()

    if status == "HISTORICAL_PRESERVED":
        return PreserveHistoryVerdict(
            conflict_id=conflict_id,
            ok=False,
            bucket="ALREADY_PRESERVED",
            reasons=["already_historical_preserved"],
        )

    if int(conflict_id) not in allowlist:
        return PreserveHistoryVerdict(
            conflict_id=conflict_id,
            ok=False,
            bucket="BLOCKED_NOT_ALLOWLISTED",
            reasons=["conflict_id_not_in_allowlist"],
        )

    if status != "PENDING_REVIEW":
        reasons.append(f"review_status_not_pending:{status}")

    remote = str(remote_status or "").strip().lower()
    if remote != "done":
        reasons.append(f"remote_status_not_done:{remote_status}")

    cls = str(classification or "").upper()
    if cls in {c.upper() for c in BLOCKED_CLASSIFICATIONS}:
        reasons.append(f"classification_blocked:{classification}")
    elif cls not in {c.upper() for c in ALLOWED_CLASSIFICATIONS}:
        reasons.append(f"classification_not_position_reconcilable:{classification}")

    if broker_open:
        reasons.append("broker_open_order")
    if db_open:
        reasons.append("db_open_order")
    if position_impact:
        reasons.append("position_impact")
    if balance_impact:
        reasons.append("balance_impact")

    if reasons:
        return PreserveHistoryVerdict(
            conflict_id=conflict_id,
            ok=False,
            bucket="NEEDS_REVIEW",
            reasons=reasons,
        )
    return PreserveHistoryVerdict(
        conflict_id=conflict_id,
        ok=True,
        bucket="SAFE_TO_PRESERVE",
        reasons=[],
    )


def assert_only_allowlisted_preserve(
    conflict_id: int,
    *,
    allowlist: frozenset[int],
) -> None:
    if int(conflict_id) not in allowlist:
        raise ValueError(
            f"BLOCKED: conflict_id={conflict_id} not in preserve allowlist"
        )
