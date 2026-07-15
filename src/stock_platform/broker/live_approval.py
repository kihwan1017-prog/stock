from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class LiveTradingApproval:
    approval_id: str
    token_hash: str
    expires_at: datetime
    used: bool = False


class LiveTradingApprovalService:
    """
    실거래 주문 직전 1회용 승인 토큰을 발급하고 검증한다.

    원문 토큰은 저장하지 않고 SHA-256 해시만 메모리에 저장한다.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                "ttl_seconds must be greater than zero"
            )

        self._ttl_seconds = ttl_seconds
        self._approvals: dict[
            str,
            LiveTradingApproval,
        ] = {}

    def issue(self) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(32)
        approval_id = secrets.token_hex(12)

        approval = LiveTradingApproval(
            approval_id=approval_id,
            token_hash=self._hash(token),
            expires_at=now
            + timedelta(seconds=self._ttl_seconds),
        )
        self._approvals[approval_id] = approval

        return {
            "approval_id": approval_id,
            "approval_token": token,
            "expires_at": approval.expires_at.isoformat(),
        }

    def consume(
        self,
        *,
        approval_id: str,
        approval_token: str,
    ) -> bool:
        approval = self._approvals.get(approval_id)

        if approval is None:
            return False

        if approval.used:
            return False

        if approval.expires_at < datetime.now(timezone.utc):
            return False

        if not secrets.compare_digest(
            approval.token_hash,
            self._hash(approval_token),
        ):
            return False

        self._approvals[approval_id] = LiveTradingApproval(
            approval_id=approval.approval_id,
            token_hash=approval.token_hash,
            expires_at=approval.expires_at,
            used=True,
        )
        return True

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()
