"""주문·체결 전략 Provenance 헬퍼.

기존 행은 채우지 않는다. NULL = UNATTRIBUTED.
strategy_code 문자열을 새로 만들지 않고 strategy_id FK 를 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


UNATTRIBUTED = "UNATTRIBUTED"


@dataclass(frozen=True, slots=True)
class OrderStrategyProvenance:
    strategy_id: int | None = None
    strategy_version: int | None = None
    runtime_scope_hash: str | None = None
    account_strategy_link_id: int | None = None
    user_id: int | None = None
    execution_mode: str | None = None  # PAPER | MOCK | LIVE | SHADOW | MANUAL

    def attribution_label(self) -> str:
        if self.strategy_id is None:
            return UNATTRIBUTED
        return f"strategy:{self.strategy_id}"

    def as_column_kwargs(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "runtime_scope_hash": (
                (self.runtime_scope_hash or "").strip() or None
            ),
            "account_strategy_link_id": self.account_strategy_link_id,
            "user_id": self.user_id,
            "execution_mode": (
                (self.execution_mode or "").strip().upper() or None
            ),
        }


def provenance_from_mapping(data: dict[str, Any] | None) -> OrderStrategyProvenance:
    if not data:
        return OrderStrategyProvenance()
    sid = data.get("strategy_id")
    ver = data.get("strategy_version")
    link = data.get("account_strategy_link_id")
    uid = data.get("user_id")
    return OrderStrategyProvenance(
        strategy_id=int(sid) if sid is not None else None,
        strategy_version=int(ver) if ver is not None else None,
        runtime_scope_hash=(
            str(data.get("runtime_scope_hash") or "").strip() or None
        ),
        account_strategy_link_id=int(link) if link is not None else None,
        user_id=int(uid) if uid is not None else None,
        execution_mode=(
            str(data.get("execution_mode") or "").strip().upper() or None
        ),
    )


def provenance_from_order_entity(order: Any) -> OrderStrategyProvenance:
    return OrderStrategyProvenance(
        strategy_id=getattr(order, "strategy_id", None),
        strategy_version=getattr(order, "strategy_version", None),
        runtime_scope_hash=getattr(order, "runtime_scope_hash", None),
        account_strategy_link_id=getattr(
            order, "account_strategy_link_id", None
        ),
        user_id=getattr(order, "user_id", None),
        execution_mode=getattr(order, "execution_mode", None),
    )
