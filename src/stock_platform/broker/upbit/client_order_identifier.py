"""STEP 8-5-12 — Upbit Client Order Identifier Factory.

형식: spu-{sha256_hex[:32]}  (총 36자 — Upbit identifier 최대)
입력: broker_code + user_broker_account_id + local_order_id + generation
"""

from __future__ import annotations

import hashlib
import re

# Upbit identifier: 계정 내 Unique, 재사용 불가, 최대 36자
UPBIT_IDENTIFIER_MAX_LEN = 36
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


class UpbitClientOrderIdentifierFactory:
    """안정적·비민감 Upbit identifier 생성기."""

    PREFIX = "spu-"

    @classmethod
    def build(
        cls,
        *,
        broker_code: str,
        user_broker_account_id: int,
        local_order_id: int,
        submission_generation: int,
    ) -> str:
        if int(submission_generation) < 1:
            raise ValueError("submission_generation must be >= 1")
        if int(local_order_id) < 1:
            raise ValueError("local_order_id must be >= 1")
        if int(user_broker_account_id) < 1:
            raise ValueError("user_broker_account_id must be >= 1")

        material = "|".join(
            [
                str(broker_code or "").strip().upper(),
                str(int(user_broker_account_id)),
                str(int(local_order_id)),
                str(int(submission_generation)),
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        # PREFIX(4) + 32 hex = 36
        identifier = f"{cls.PREFIX}{digest[:32]}"
        cls.validate(identifier)
        return identifier

    @classmethod
    def validate(cls, identifier: str) -> str:
        value = (identifier or "").strip()
        if not value:
            raise ValueError("identifier must not be empty")
        if len(value) > UPBIT_IDENTIFIER_MAX_LEN:
            raise ValueError(
                f"identifier exceeds {UPBIT_IDENTIFIER_MAX_LEN} chars"
            )
        if not _IDENTIFIER_RE.match(value):
            raise ValueError("identifier has invalid characters")
        return value

    @classmethod
    def order_fingerprint(
        cls,
        *,
        user_broker_account_id: int,
        strategy_id: str | None,
        signal_id: str | None,
        market: str,
        side: str,
        order_type: str,
        price: str | None,
        volume: str,
        generation: int,
    ) -> str:
        """논리 주문 Fingerprint (Identifier 대체 아님)."""

        parts = [
            f"uba={int(user_broker_account_id)}",
            f"strategy={strategy_id or ''}",
            f"signal={signal_id or ''}",
            f"market={(market or '').upper()}",
            f"side={(side or '').upper()}",
            f"type={(order_type or '').upper()}",
            f"price={price or ''}",
            f"volume={volume}",
            f"gen={int(generation)}",
        ]
        raw = "\n".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
