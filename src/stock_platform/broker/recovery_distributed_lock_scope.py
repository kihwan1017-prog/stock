"""STEP 8-5-6 — Distributed Recovery Lock Scope / Key.

Python builtin hash()는 프로세스마다 달라지므로 사용 금지.
SHA-256 기반 안정적 scope key를 사용한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RecoveryAccountKind(StrEnum):
    PAPER = "PAPER"
    USER_BROKER = "USER_BROKER"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class RecoveryLockScope:
    account_kind: RecoveryAccountKind
    account_id: int  # paper/uba id; SYSTEM은 0
    broker_code: str
    market_type: str  # STOCK | CRYPTO | ALL

    def __post_init__(self) -> None:
        if self.account_kind != RecoveryAccountKind.SYSTEM:
            if self.account_id <= 0:
                raise ValueError("account_id must be > 0")
        if not (self.broker_code or "").strip():
            raise ValueError("broker_code required")
        if not (self.market_type or "").strip():
            raise ValueError("market_type required")

    @property
    def lock_scope_key(self) -> str:
        """계좌번호·Secret 없이 안정적인 문자열 키."""

        kind = self.account_kind.value
        if self.account_kind == RecoveryAccountKind.PAPER:
            acct = f"paper:{self.account_id}"
        elif self.account_kind == RecoveryAccountKind.USER_BROKER:
            acct = f"uba:{self.account_id}"
        else:
            acct = "system:0"
        raw = "|".join(
            [
                f"kind:{kind}",
                acct,
                f"broker:{self.broker_code.upper()}",
                f"mkt:{self.market_type.upper()}",
            ]
        )
        # 고정 Namespace + SHA-256 hex (프로세스 독립)
        digest = hashlib.sha256(
            f"stock-platform-recovery|{raw}".encode("utf-8")
        ).hexdigest()
        return f"rlk:{digest[:40]}"

    def masked_for_log(self) -> dict[str, Any]:
        return {
            "lock_scope_key": self.lock_scope_key,
            "account_kind": self.account_kind.value,
            "account_id": self.account_id,
            "broker_code": self.broker_code.upper(),
            "market_type": self.market_type.upper(),
        }


def scope_from_context(context) -> RecoveryLockScope:
    """AccountRecoveryContext → RecoveryLockScope."""

    broker = str(context.broker_code).upper()
    market = str(context.market_type or "ALL").upper()
    if context.user_broker_account_id is not None:
        return RecoveryLockScope(
            account_kind=RecoveryAccountKind.USER_BROKER,
            account_id=int(context.user_broker_account_id),
            broker_code=broker,
            market_type=market,
        )
    if context.paper_account_id is not None:
        return RecoveryLockScope(
            account_kind=RecoveryAccountKind.PAPER,
            account_id=int(context.paper_account_id),
            broker_code=broker,
            market_type=market,
        )
    return RecoveryLockScope(
        account_kind=RecoveryAccountKind.SYSTEM,
        account_id=0,
        broker_code=broker,
        market_type=market,
    )
