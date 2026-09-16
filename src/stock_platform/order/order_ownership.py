"""공통 Open-Order Ownership — MANUAL / AUTO / UNKNOWN (KIWOOM+UPBIT).

SymbolOwnership / TradingOrder strategy provenance 를 재사용한다.
새 중복 SoT 를 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
)


ORDER_OWNERSHIP_UNKNOWN = "ORDER_OWNERSHIP_UNKNOWN"


@dataclass(frozen=True, slots=True)
class OrderOwnershipDecision:
    owner: str  # MANUAL | AUTO | UNKNOWN
    broker: str
    uba_id: int
    symbol: str | None
    broker_order_id: str | None
    local_order_id: int | None
    strategy_id: int | None
    deployment_id: int | None
    binding_id: int | None = None
    slot_id: int | None = None
    provenance: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_local_auto_provenance(
    *,
    strategy_id: int | None,
    strategy_deployment_id: int | None = None,
    metadata_payload: dict[str, Any] | None = None,
    order_source: str | None = None,
) -> bool:
    """DB 근거로 AUTO 주문인지 판정."""

    if strategy_id is not None:
        return True
    if strategy_deployment_id is not None:
        return True
    src = str(order_source or "").strip().upper()
    if src == "AUTO":
        return True
    meta = metadata_payload if isinstance(metadata_payload, dict) else {}
    meta_src = str(meta.get("order_source") or "").strip().upper()
    if meta_src == "AUTO":
        return True
    if meta.get("strategy_id") is not None:
        try:
            int(meta["strategy_id"])
            return True
        except (TypeError, ValueError):
            pass
    return False


def classify_local_open_order(
    *,
    broker: str,
    uba_id: int,
    symbol: str | None,
    local_order_id: int | None,
    broker_order_id: str | None,
    strategy_id: int | None,
    strategy_deployment_id: int | None = None,
    metadata_payload: dict[str, Any] | None = None,
    order_source: str | None = None,
) -> OrderOwnershipDecision:
    broker_u = str(broker or "").upper()
    if is_local_auto_provenance(
        strategy_id=strategy_id,
        strategy_deployment_id=strategy_deployment_id,
        metadata_payload=metadata_payload,
        order_source=order_source,
    ):
        return OrderOwnershipDecision(
            owner=OWNER_AUTO,
            broker=broker_u,
            uba_id=int(uba_id),
            symbol=(str(symbol).upper() if symbol else None),
            broker_order_id=broker_order_id,
            local_order_id=local_order_id,
            strategy_id=int(strategy_id) if strategy_id is not None else None,
            deployment_id=(
                int(strategy_deployment_id)
                if strategy_deployment_id is not None
                else None
            ),
            provenance=["LOCAL_TRADING_ORDER_AUTO"],
            reasons=["STRATEGY_OR_AUTO_SOURCE"],
        )
    return OrderOwnershipDecision(
        owner=OWNER_MANUAL,
        broker=broker_u,
        uba_id=int(uba_id),
        symbol=(str(symbol).upper() if symbol else None),
        broker_order_id=broker_order_id,
        local_order_id=local_order_id,
        strategy_id=None,
        deployment_id=None,
        provenance=["LOCAL_TRADING_ORDER_MANUAL"],
        reasons=["NO_AUTO_PROVENANCE"],
    )


def classify_unmapped_remote_open_order(
    *,
    broker: str,
    uba_id: int,
    symbol: str | None,
    broker_order_id: str | None,
    has_matching_local_auto: bool = False,
) -> OrderOwnershipDecision:
    """local AUTO TradingOrder 매칭이 없는 broker open → MANUAL.

    플랫폼 AUTO 주문이라면 local TradingOrder + strategy provenance 가 있어야 한다.
    """

    broker_u = str(broker or "").upper()
    if has_matching_local_auto:
        return OrderOwnershipDecision(
            owner=OWNER_AUTO,
            broker=broker_u,
            uba_id=int(uba_id),
            symbol=(str(symbol).upper() if symbol else None),
            broker_order_id=broker_order_id,
            local_order_id=None,
            strategy_id=None,
            deployment_id=None,
            provenance=["REMOTE_MAPPED_SHOULD_NOT_CALL"],
            reasons=["UNEXPECTED"],
        )
    # 미매칭 remote = 사용자 HTS/MTS/앱 직접 주문 (MANUAL)
    return OrderOwnershipDecision(
        owner=OWNER_MANUAL,
        broker=broker_u,
        uba_id=int(uba_id),
        symbol=(str(symbol).upper() if symbol else None),
        broker_order_id=broker_order_id,
        local_order_id=None,
        strategy_id=None,
        deployment_id=None,
        provenance=["REMOTE_UNMAPPED_NO_LOCAL_AUTO"],
        reasons=["REMOTE_MANUAL_ACTIVITY"],
    )
