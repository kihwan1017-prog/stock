"""Open-order semantic classification for ARM renew / restore safety gates.

Trading policy unchanged — operational gate semantics only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.order_ownership import (
    OWNER_AUTO,
    OWNER_MANUAL,
    ORDER_OWNERSHIP_UNKNOWN,
    classify_local_open_order,
)
from stock_platform.trading.account_models import UserBrokerAccount

GateMode = Literal["initial_arm", "arm_renew", "restore"]

OPEN_CLASS_AUTO_ENTRY_BUY = "AUTO_ENTRY_BUY_OPEN"
OPEN_CLASS_AUTO_EXIT_SELL = "AUTO_EXIT_SELL_OPEN"
OPEN_CLASS_MANUAL = "MANUAL_OPEN"
OPEN_CLASS_UNKNOWN = "UNKNOWN_OPEN"
OPEN_CLASS_AMBIGUOUS = "AMBIGUOUS_OPEN"

_LOCAL_OPEN_STATUSES = frozenset(
    {
        OrderStatus.CREATED.value,
        OrderStatus.PENDING.value,
        OrderStatus.SUBMITTING.value,
        OrderStatus.SENT.value,
        OrderStatus.ACCEPTED.value,
        OrderStatus.PARTIALLY_FILLED.value,
        OrderStatus.REMOTE_LOOKUP_PENDING.value,
    }
)
_LOCAL_AMBIGUOUS_STATUSES = frozenset(
    {
        OrderStatus.AMBIGUOUS_SUBMISSION.value,
        OrderStatus.MANUAL_REVIEW_REQUIRED.value,
    }
)
_UPBIT_BROKER_CONFIRMED = frozenset({"wait", "watch"})


@dataclass(slots=True)
class ClassifiedOpenOrder:
    order_id: int
    symbol: str
    side: str
    semantic_class: str
    owner: str
    broker_order_id: str | None
    broker_remote_state: str | None = None
    blocks_initial_arm: bool = True
    blocks_arm_renew: bool = True
    blocks_restore: bool = True
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OpenOrderGateSummary:
    user_broker_account_id: int
    broker_code: str
    gate_mode: GateMode
    class_counts: dict[str, int]
    orders: list[ClassifiedOpenOrder]
    db_open_blocking: int
    submission_unknown: int
    cancel_pending: int
    replace_pending: int
    auto_protective_excluded: int
    auto_entry_buy_excluded: int
    arm_renew_block_reason: str | None = None

    def blocking_dict(self) -> dict[str, int]:
        return {
            "db_open": self.db_open_blocking,
            "submission_unknown": self.submission_unknown,
            "cancel_pending": self.cancel_pending,
            "replace_pending": self.replace_pending,
            "auto_protective_open_excluded": self.auto_protective_excluded,
            "auto_entry_buy_excluded": self.auto_entry_buy_excluded,
        }


def _classify_local_order(
    order: TradingOrderEntity,
    *,
    uba_id: int,
    broker_code: str,
    broker_remote_state: str | None,
) -> ClassifiedOpenOrder:
    meta = order.metadata_payload if isinstance(order.metadata_payload, dict) else {}
    side = str(order.side_code or "").upper()
    decision = classify_local_open_order(
        broker=broker_code,
        uba_id=uba_id,
        symbol=order.symbol,
        local_order_id=int(order.order_id),
        broker_order_id=order.broker_order_id,
        strategy_id=getattr(order, "strategy_id", None),
        strategy_deployment_id=getattr(order, "strategy_deployment_id", None),
        metadata_payload=meta,
        order_source=str(meta.get("order_source") or ""),
    )
    owner = str(decision.owner or OWNER_MANUAL).upper()
    broker_uuid = str(order.broker_order_id or "").strip() or None
    local_status = str(order.status_code or "")

    if local_status in _LOCAL_AMBIGUOUS_STATUSES or not broker_uuid:
        if owner == OWNER_AUTO:
            semantic = OPEN_CLASS_AMBIGUOUS
        else:
            semantic = OPEN_CLASS_AMBIGUOUS
    elif owner == OWNER_AUTO:
        order_src = str(meta.get("order_source") or "").strip().upper()
        if side == "SELL" or order_src == "EXIT":
            semantic = OPEN_CLASS_AUTO_EXIT_SELL
        elif side == "BUY":
            semantic = OPEN_CLASS_AUTO_ENTRY_BUY
        else:
            semantic = OPEN_CLASS_UNKNOWN
    elif owner == OWNER_MANUAL:
        semantic = OPEN_CLASS_MANUAL
    else:
        semantic = OPEN_CLASS_UNKNOWN

    blocks_arm_renew = True
    blocks_initial = True
    blocks_restore = True
    known_safe_entry = False

    if semantic == OPEN_CLASS_AUTO_EXIT_SELL:
        blocks_arm_renew = False
    elif semantic == OPEN_CLASS_AUTO_ENTRY_BUY:
        if broker_code == "UPBIT" and broker_remote_state is not None:
            if broker_remote_state in _UPBIT_BROKER_CONFIRMED:
                known_safe_entry = True
        elif broker_code != "UPBIT" and broker_uuid:
            # KIWOOM 등 — local AUTO BUY + UUID 있으면 renew 허용 (broker sync 별도)
            known_safe_entry = True
        if known_safe_entry:
            blocks_arm_renew = False

    return ClassifiedOpenOrder(
        order_id=int(order.order_id),
        symbol=str(order.symbol or ""),
        side=side,
        semantic_class=semantic,
        owner=owner,
        broker_order_id=broker_uuid,
        broker_remote_state=broker_remote_state,
        blocks_initial_arm=blocks_initial,
        blocks_arm_renew=blocks_arm_renew,
        blocks_restore=blocks_restore,
        detail={
            "local_status": local_status,
            "known_safe_auto_entry": known_safe_entry,
        },
    )


def evaluate_open_order_gate_for_uba(
    session: Session,
    uba_id: int,
    *,
    gate_mode: GateMode = "initial_arm",
    verify_upbit_broker_state: bool = False,
) -> OpenOrderGateSummary:
    """Semantic open-order gate — renew vs initial ARM semantics 분리."""

    uba = session.get(UserBrokerAccount, int(uba_id))
    broker_code = str(getattr(uba, "broker_code", "") or "UPBIT").upper()

    open_rows = list(
        session.scalars(
            select(TradingOrderEntity).where(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.status_code.in_(list(_LOCAL_OPEN_STATUSES)),
            )
        )
    )

    client: Any | None = None
    classified: list[ClassifiedOpenOrder] = []
    for order in open_rows:
        remote_state: str | None = None
        if verify_upbit_broker_state and broker_code == "UPBIT":
            uuid = str(order.broker_order_id or "").strip()
            if uuid:
                try:
                    if client is None:
                        from stock_platform.broker.credential_adapter_factory import (
                            build_upbit_adapter_for_uba,
                        )

                        client = build_upbit_adapter_for_uba(
                            session, int(uba_id)
                        )._client  # noqa: SLF001
                    remote = client.get_order(uuid=uuid)
                    remote_state = str(remote.get("state") or "").lower()
                except Exception as exc:  # noqa: BLE001
                    remote_state = f"error:{type(exc).__name__}"
        classified.append(
            _classify_local_order(
                order,
                uba_id=int(uba_id),
                broker_code=broker_code,
                broker_remote_state=remote_state,
            )
        )

    class_counts: dict[str, int] = {
        OPEN_CLASS_AUTO_ENTRY_BUY: 0,
        OPEN_CLASS_AUTO_EXIT_SELL: 0,
        OPEN_CLASS_MANUAL: 0,
        OPEN_CLASS_UNKNOWN: 0,
        OPEN_CLASS_AMBIGUOUS: 0,
    }
    auto_protective_excluded = 0
    auto_entry_excluded = 0
    db_open_blocking = 0

    for row in classified:
        class_counts[row.semantic_class] = (
            int(class_counts.get(row.semantic_class, 0)) + 1
        )
        if gate_mode == "arm_renew":
            if row.semantic_class == OPEN_CLASS_AUTO_EXIT_SELL:
                auto_protective_excluded += 1
                continue
            if (
                row.semantic_class == OPEN_CLASS_AUTO_ENTRY_BUY
                and not row.blocks_arm_renew
            ):
                auto_entry_excluded += 1
                continue
            if row.blocks_arm_renew:
                db_open_blocking += 1
        else:
            db_open_blocking += 1

    submission_unknown = int(
        session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.status_code.in_(
                    list(_LOCAL_AMBIGUOUS_STATUSES)
                ),
            )
        )
        or 0
    )
    cancel_pending = _count_status(session, uba_id, {OrderStatus.CANCEL_REQUESTED.value})
    replace_pending = _count_status(
        session, uba_id, {OrderStatus.REPLACE_REQUESTED.value}
    )

    block_reason: str | None = None
    if gate_mode == "arm_renew" and db_open_blocking > 0:
        blockers = [
            f"{o.semantic_class}:{o.order_id}"
            for o in classified
            if o.blocks_arm_renew
        ]
        block_reason = "db_open_orders:" + ",".join(blockers[:5])
    elif submission_unknown > 0:
        block_reason = f"submission_unknown:{submission_unknown}"

    return OpenOrderGateSummary(
        user_broker_account_id=int(uba_id),
        broker_code=broker_code,
        gate_mode=gate_mode,
        class_counts=class_counts,
        orders=classified,
        db_open_blocking=db_open_blocking,
        submission_unknown=submission_unknown,
        cancel_pending=cancel_pending,
        replace_pending=replace_pending,
        auto_protective_excluded=auto_protective_excluded,
        auto_entry_buy_excluded=auto_entry_excluded,
        arm_renew_block_reason=block_reason,
    )


def _count_status(session: Session, uba_id: int, statuses: set[str]) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.status_code.in_(list(statuses)),
            )
        )
        or 0
    )


def open_order_class_counts_for_ops(session: Session, uba_id: int) -> dict[str, int]:
    """ops-status용 — broker remote 검증 없이 local semantic count."""

    summary = evaluate_open_order_gate_for_uba(
        session,
        int(uba_id),
        gate_mode="initial_arm",
        verify_upbit_broker_state=False,
    )
    return dict(summary.class_counts)
