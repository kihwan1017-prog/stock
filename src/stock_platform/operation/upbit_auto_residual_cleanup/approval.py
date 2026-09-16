# -*- coding: utf-8 -*-
"""One-time explicit operator approval — 재사용 금지."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    REASON_APPROVAL_REQUIRED,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    EligibilityResult,
    truth_version_hash,
)


class ApprovalError(ValueError):
    """승인 검증 실패."""


@dataclass
class CleanupApproval:
    approval_id: str
    secret: str
    uba_id: int
    binding_id: int
    symbol: str
    preview_hash: str
    provenance_hash: str
    eligible_qty: str
    broker_qty: str
    mark_price: str
    notional: str
    idempotency_key: str
    operator_intent: str
    created_at: str
    expires_at: str
    consumed: bool = False
    consumed_at: str | None = None

    def as_public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("secret", None)
        return d


def preview_result_hash(elig: EligibilityResult) -> str:
    raw = "|".join(
        [
            elig.kind,
            str(elig.eligible_qty),
            str(elig.broker_qty),
            str(elig.provenance_qty),
            str(elig.mark_price),
            str(elig.estimated_notional),
            elig.idempotency_key,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_cleanup_approval(
    *,
    uba_id: int,
    binding_id: int,
    symbol: str,
    truth: dict[str, Any],
    elig: EligibilityResult,
    operator_intent: str,
    ttl_seconds: int = 600,
) -> CleanupApproval:
    """1회성 approval 발급. secret은 제출 시에만 사용."""

    if not elig.eligible:
        raise ApprovalError("cannot approve ineligible preview")
    if not operator_intent or not str(operator_intent).strip():
        raise ApprovalError(REASON_APPROVAL_REQUIRED)

    now = datetime.now(timezone.utc)
    approval_id = f"CRA-{secrets.token_hex(8)}"
    secret = secrets.token_urlsafe(24)
    return CleanupApproval(
        approval_id=approval_id,
        secret=secret,
        uba_id=int(uba_id),
        binding_id=int(binding_id),
        symbol=str(symbol).upper(),
        preview_hash=preview_result_hash(elig),
        provenance_hash=truth_version_hash(truth),
        eligible_qty=str(elig.eligible_qty),
        broker_qty=str(elig.broker_qty),
        mark_price=str(elig.mark_price or ""),
        notional=str(elig.estimated_notional or ""),
        idempotency_key=elig.idempotency_key,
        operator_intent=str(operator_intent).strip()[:200],
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=int(ttl_seconds))).isoformat(),
        consumed=False,
    )


def validate_approval(
    approval: CleanupApproval,
    *,
    secret: str,
    uba_id: int,
    binding_id: int,
    symbol: str,
    truth: dict[str, Any],
    elig: EligibilityResult,
    now: datetime | None = None,
) -> None:
    """승인 1회성·만료·preview/provenance hash·대상 일치 검증."""

    if approval.consumed:
        raise ApprovalError("APPROVAL_ALREADY_CONSUMED")
    if str(secret or "") != str(approval.secret):
        raise ApprovalError("APPROVAL_SECRET_MISMATCH")
    if int(uba_id) != int(approval.uba_id):
        raise ApprovalError("APPROVAL_UBA_MISMATCH")
    if int(binding_id) != int(approval.binding_id):
        raise ApprovalError("APPROVAL_BINDING_MISMATCH")
    if str(symbol).upper() != str(approval.symbol).upper():
        raise ApprovalError("APPROVAL_SYMBOL_MISMATCH")

    ts = now or datetime.now(timezone.utc)
    exp = datetime.fromisoformat(approval.expires_at)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if ts > exp:
        raise ApprovalError("APPROVAL_EXPIRED")

    if truth_version_hash(truth) != approval.provenance_hash:
        raise ApprovalError("PROVENANCE_HASH_CHANGED")
    if preview_result_hash(elig) != approval.preview_hash:
        raise ApprovalError("PREVIEW_HASH_CHANGED")

    # qty drift guard — eligible must still match approved qty
    if Decimal(str(elig.eligible_qty)) != Decimal(str(approval.eligible_qty)):
        raise ApprovalError("ELIGIBLE_QTY_CHANGED")
