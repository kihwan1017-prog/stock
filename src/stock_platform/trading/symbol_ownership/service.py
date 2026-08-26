"""공통 Symbol Ownership Resolver — derived SoT (복제 최소화)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import BrokerPositionSnapshotEntity
from stock_platform.broker.pending_entities import BrokerPendingOrderEntity
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_OPEN,
    StrategyPositionBindingEntity,
)
from stock_platform.trading.symbol_ownership.constants import (
    ACTIVE_SLOT_STATUSES,
    CONFLICT_REMOTE_AUTO_MISMATCH,
    CONFLICT_REMOTE_MANUAL_ACTIVITY,
    CONFLICT_SAME_SYMBOL_MANUAL_AUTO,
    OPEN_ORDER_STATUSES,
    OWNER_AUTO,
    OWNER_AUTO_EXCLUDED,
    OWNER_FREE,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
    REASON_AUTO_BINDING,
    REASON_AUTO_OPEN_ORDER,
    REASON_AUTO_SLOT,
    REASON_MANUAL_OPEN_ORDER,
    REASON_MANUAL_POSITION,
    REASON_SAME_SYMBOL_MIX,
    REASON_UNKNOWN_PROVENANCE,
    REASON_USER_EXCLUDED,
    SKIP_AUTO_ALREADY_MANAGED,
    SKIP_AUTO_EXCLUDED,
    SKIP_MANUAL_SYMBOL_EXCLUDED,
    SKIP_OWNERSHIP_UNKNOWN,
    SKIP_SYMBOL_HOLD,
)
from stock_platform.trading.symbol_ownership.entities import (
    SymbolAutoExclusionEntity,
    SymbolOwnershipHoldEntity,
)

ZERO = Decimal("0")


@dataclass(slots=True)
class SymbolOwnershipResult:
    owner: str
    symbol: str = ""
    reasons: list[str] = field(default_factory=list)
    manual_position_qty: Decimal = ZERO
    manual_open_orders: int = 0
    auto_position_qty: Decimal = ZERO
    auto_open_orders: int = 0
    auto_entry_price: Decimal | None = None
    strategy_id: int | None = None
    deployment_id: int | None = None
    slot_id: int | None = None
    slot_no: int | None = None
    user_excluded: bool = False
    symbol_hold_active: bool = False
    entry_allowed: bool = False
    entry_skip_reason: str | None = None
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["manual_position_qty"] = str(self.manual_position_qty)
        d["auto_position_qty"] = str(self.auto_position_qty)
        d["auto_entry_price"] = (
            str(self.auto_entry_price)
            if self.auto_entry_price is not None
            else None
        )
        return d


@dataclass(slots=True)
class RemoteConflictClassification:
    """REMOTE_ONLY 주문에 대한 ownership-aware 분류."""

    pause_account: bool
    conflict_kind: str
    risk_level: str
    symbol: str
    owner: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SymbolOwnershipService:
    """KIWOOM/UPBIT 공통 ownership 판정."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
        symbol: str,
    ) -> SymbolOwnershipResult:
        broker = str(broker_code or "").upper()
        uba = int(user_broker_account_id)
        sym = str(symbol or "").strip().upper()
        now = datetime.now(timezone.utc).isoformat()
        if not sym:
            return SymbolOwnershipResult(
                owner=OWNER_UNKNOWN,
                symbol=sym,
                reasons=[REASON_UNKNOWN_PROVENANCE],
                entry_allowed=False,
                entry_skip_reason=SKIP_OWNERSHIP_UNKNOWN,
                resolved_at=now,
            )

        user_excluded = self.is_user_excluded(uba, broker, sym)
        hold = self.get_active_hold(uba, broker, sym)

        auto_qty, strategy_id, deployment_id, auto_entry = self._auto_binding_qty(
            uba, broker, sym, broker_qty_hint=None
        )
        broker_qty = self._broker_position_qty(uba, broker, sym)
        if auto_qty <= ZERO:
            auto_qty, strategy_id, deployment_id, auto_entry = self._auto_binding_qty(
                uba, broker, sym, broker_qty_hint=broker_qty
            )
        slot_id, slot_no, slot_active = self._auto_slot(uba, broker, sym)
        auto_orders = self._auto_open_order_count(uba, broker, sym)
        pending_manualish = self._broker_pending_without_local(
            uba, broker, sym
        )
        local_manual_orders = self._manual_open_order_count(uba, broker, sym)

        from stock_platform.trading.symbol_ownership.decision import (
            OwnershipFacts,
            decide_ownership,
        )

        manual_orders = pending_manualish + local_manual_orders
        decision = decide_ownership(
            OwnershipFacts(
                broker_position_qty=broker_qty,
                auto_binding_qty=auto_qty,
                auto_open_orders=auto_orders,
                auto_slot_active=slot_active,
                manual_open_orders=manual_orders,
                user_excluded=user_excluded,
                symbol_hold_active=hold is not None,
            )
        )

        return SymbolOwnershipResult(
            owner=decision.owner,
            symbol=sym,
            reasons=list(decision.reasons),
            manual_position_qty=decision.manual_position_qty,
            manual_open_orders=int(manual_orders),
            auto_position_qty=decision.auto_position_qty,
            auto_open_orders=int(auto_orders),
            auto_entry_price=auto_entry,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            slot_id=slot_id,
            slot_no=slot_no,
            user_excluded=user_excluded,
            symbol_hold_active=hold is not None,
            entry_allowed=decision.entry_allowed,
            entry_skip_reason=decision.entry_skip_reason,
            resolved_at=now,
        )

    def resolve_many(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
        symbols: list[str],
    ) -> dict[str, SymbolOwnershipResult]:
        return {
            str(s).upper(): self.resolve(
                broker_code=broker_code,
                user_broker_account_id=user_broker_account_id,
                symbol=s,
            )
            for s in symbols
            if str(s or "").strip()
        }

    def list_account_symbols(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
    ) -> list[SymbolOwnershipResult]:
        """스냅샷+binding+pending+slot 심볼 합집합을 판정."""

        broker = str(broker_code).upper()
        uba = int(user_broker_account_id)
        symbols: set[str] = set()
        for row in self._session.scalars(
            select(BrokerPositionSnapshotEntity).where(
                BrokerPositionSnapshotEntity.user_broker_account_id == uba,
                BrokerPositionSnapshotEntity.broker_code == broker,
                BrokerPositionSnapshotEntity.snapshot_status == "ACTIVE",
            )
        ):
            if Decimal(str(row.quantity or 0)) > ZERO:
                symbols.add(str(row.symbol).upper())
        for row in self._session.scalars(
            select(StrategyPositionBindingEntity).where(
                StrategyPositionBindingEntity.user_broker_account_id == uba,
                StrategyPositionBindingEntity.broker_code == broker,
                StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
            )
        ):
            symbols.add(str(row.symbol).upper())
        for row in self._session.scalars(
            select(BrokerPendingOrderEntity).where(
                BrokerPendingOrderEntity.user_broker_account_id == uba,
                BrokerPendingOrderEntity.broker_code == broker,
            )
        ):
            symbols.add(str(row.symbol).upper())
        if broker == "UPBIT":
            try:
                from stock_platform.operation.upbit_full_market.entities import (
                    UpbitPositionSlotEntity,
                    UpbitStrategyPositionBindingEntity,
                )

                for row in self._session.scalars(
                    select(UpbitStrategyPositionBindingEntity).where(
                        UpbitStrategyPositionBindingEntity.user_broker_account_id
                        == uba,
                        UpbitStrategyPositionBindingEntity.status
                        == BINDING_STATUS_OPEN,
                    )
                ):
                    symbols.add(str(row.symbol).upper())
                for row in self._session.scalars(
                    select(UpbitPositionSlotEntity).where(
                        UpbitPositionSlotEntity.user_broker_account_id == uba,
                        UpbitPositionSlotEntity.status.in_(
                            list(ACTIVE_SLOT_STATUSES)
                        ),
                    )
                ):
                    if row.symbol:
                        symbols.add(str(row.symbol).upper())
            except Exception:  # noqa: BLE001
                pass
        for row in self._session.scalars(
            select(SymbolAutoExclusionEntity).where(
                SymbolAutoExclusionEntity.user_broker_account_id == uba,
                SymbolAutoExclusionEntity.broker_code == broker,
                SymbolAutoExclusionEntity.enabled.is_(True),
            )
        ):
            symbols.add(str(row.symbol).upper())

        out = [
            self.resolve(
                broker_code=broker,
                user_broker_account_id=uba,
                symbol=sym,
            )
            for sym in sorted(symbols)
        ]
        return out

    def entry_gate(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
        symbol: str,
    ) -> tuple[bool, str | None, SymbolOwnershipResult]:
        result = self.resolve(
            broker_code=broker_code,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
        )
        return result.entry_allowed, result.entry_skip_reason, result

    def classify_remote_order(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
        symbol: str,
    ) -> RemoteConflictClassification:
        """REMOTE_ONLY → account pause 여부 판정."""

        resolved = self.resolve(
            broker_code=broker_code,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
        )
        sym = str(symbol or "").upper()
        if resolved.owner == OWNER_AUTO or (
            resolved.auto_position_qty > ZERO or resolved.auto_open_orders > 0
        ):
            # AUTO 심볼에 출처 없는 remote → same-symbol fail-closed
            return RemoteConflictClassification(
                pause_account=False,
                conflict_kind=CONFLICT_SAME_SYMBOL_MANUAL_AUTO,
                risk_level="HIGH",
                symbol=sym,
                owner=resolved.owner,
                reasons=resolved.reasons
                + [CONFLICT_SAME_SYMBOL_MANUAL_AUTO],
            )
        if resolved.owner in {OWNER_MANUAL, OWNER_FREE, OWNER_AUTO_EXCLUDED}:
            return RemoteConflictClassification(
                pause_account=False,
                conflict_kind=CONFLICT_REMOTE_MANUAL_ACTIVITY,
                risk_level="INFO",
                symbol=sym,
                owner=resolved.owner,
                reasons=resolved.reasons + [CONFLICT_REMOTE_MANUAL_ACTIVITY],
            )
        # UNKNOWN — AUTO 추정 금지, account pause는 보수적으로만
        # (AUTO 흔적이 없을 때 UNKNOWN이면 MANUAL activity로 취급)
        if resolved.auto_position_qty <= ZERO and resolved.auto_open_orders <= 0:
            return RemoteConflictClassification(
                pause_account=False,
                conflict_kind=CONFLICT_REMOTE_MANUAL_ACTIVITY,
                risk_level="INFO",
                symbol=sym,
                owner=resolved.owner,
                reasons=resolved.reasons + [CONFLICT_REMOTE_MANUAL_ACTIVITY],
            )
        return RemoteConflictClassification(
            pause_account=True,
            conflict_kind=CONFLICT_REMOTE_AUTO_MISMATCH,
            risk_level="HIGH",
            symbol=sym,
            owner=resolved.owner,
            reasons=resolved.reasons + [CONFLICT_REMOTE_AUTO_MISMATCH],
        )

    def activate_same_symbol_hold(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
        symbol: str,
        reason_code: str = CONFLICT_SAME_SYMBOL_MANUAL_AUTO,
        detail: dict[str, Any] | None = None,
    ) -> SymbolOwnershipHoldEntity:
        broker = str(broker_code).upper()
        uba = int(user_broker_account_id)
        sym = str(symbol).upper()
        row = self.get_active_hold(uba, broker, sym)
        now = datetime.now(timezone.utc)
        if row is None:
            row = SymbolOwnershipHoldEntity(
                user_broker_account_id=uba,
                broker_code=broker,
                symbol=sym,
                status="ACTIVE",
                reason_code=reason_code,
                detail_json=detail or {},
            )
            self._session.add(row)
        else:
            row.reason_code = reason_code
            row.detail_json = detail or row.detail_json or {}
            row.updated_at = now
        self._session.flush()
        return row

    def is_user_excluded(
        self, uba: int, broker: str, symbol: str
    ) -> bool:
        row = self._session.scalar(
            select(SymbolAutoExclusionEntity).where(
                SymbolAutoExclusionEntity.user_broker_account_id == int(uba),
                SymbolAutoExclusionEntity.broker_code == str(broker).upper(),
                SymbolAutoExclusionEntity.symbol == str(symbol).upper(),
                SymbolAutoExclusionEntity.enabled.is_(True),
            )
        )
        return row is not None

    def get_active_hold(
        self, uba: int, broker: str, symbol: str
    ) -> SymbolOwnershipHoldEntity | None:
        return self._session.scalar(
            select(SymbolOwnershipHoldEntity).where(
                SymbolOwnershipHoldEntity.user_broker_account_id == int(uba),
                SymbolOwnershipHoldEntity.broker_code == str(broker).upper(),
                SymbolOwnershipHoldEntity.symbol == str(symbol).upper(),
                SymbolOwnershipHoldEntity.status == "ACTIVE",
            )
        )

    def set_user_exclusion(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        symbol: str,
        enabled: bool,
        reason: str | None = None,
        created_by: str | None = None,
    ) -> SymbolAutoExclusionEntity:
        uba = int(user_broker_account_id)
        broker = str(broker_code).upper()
        sym = str(symbol).upper()
        row = self._session.scalar(
            select(SymbolAutoExclusionEntity).where(
                SymbolAutoExclusionEntity.user_broker_account_id == uba,
                SymbolAutoExclusionEntity.broker_code == broker,
                SymbolAutoExclusionEntity.symbol == sym,
            )
        )
        if row is None:
            row = SymbolAutoExclusionEntity(
                user_broker_account_id=uba,
                broker_code=broker,
                symbol=sym,
                enabled=bool(enabled),
                reason=reason,
                created_by=created_by,
            )
            self._session.add(row)
        else:
            row.enabled = bool(enabled)
            if reason is not None:
                row.reason = reason
            row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return row

    # --- internal collectors ---

    def _auto_binding_qty(
        self,
        uba: int,
        broker: str,
        sym: str,
        *,
        broker_qty_hint: Decimal | None = None,
    ) -> tuple[Decimal, int | None, int | None, Decimal | None]:
        qty = ZERO
        strategy_id: int | None = None
        deployment_id: int | None = None
        entry_price: Decimal | None = None
        cost = ZERO
        broker_fallback = (
            broker_qty_hint
            if broker_qty_hint is not None
            else ZERO
        )
        rows = list(
            self._session.scalars(
                select(StrategyPositionBindingEntity).where(
                    StrategyPositionBindingEntity.user_broker_account_id
                    == uba,
                    StrategyPositionBindingEntity.broker_code == broker,
                    StrategyPositionBindingEntity.symbol == sym,
                    StrategyPositionBindingEntity.status
                    == BINDING_STATUS_OPEN,
                )
            )
        )
        for row in rows:
            q = Decimal(str(row.owned_quantity or 0))
            qty += q
            strategy_id = int(row.strategy_id)
            if row.deployment_id is not None:
                deployment_id = int(row.deployment_id)
            ep = getattr(row, "entry_price", None)
            if ep is not None and q > ZERO:
                try:
                    ep_d = Decimal(str(ep))
                    if ep_d > ZERO:
                        cost += q * ep_d
                        if entry_price is None:
                            entry_price = ep_d
                except Exception:  # noqa: BLE001
                    pass
        if qty > ZERO and cost > ZERO:
            entry_price = cost / qty
        if broker == "UPBIT":
            try:
                from stock_platform.operation.upbit_full_market.entities import (
                    UpbitStrategyPositionBindingEntity,
                )

                upbit_rows = list(
                    self._session.scalars(
                        select(UpbitStrategyPositionBindingEntity).where(
                            UpbitStrategyPositionBindingEntity.user_broker_account_id
                            == uba,
                            UpbitStrategyPositionBindingEntity.symbol == sym,
                            UpbitStrategyPositionBindingEntity.status
                            == BINDING_STATUS_OPEN,
                        )
                    )
                )
                if upbit_rows and qty <= ZERO:
                    qty = (
                        broker_fallback
                        if broker_fallback > ZERO
                        else Decimal("1")
                    )
                for row in upbit_rows:
                    if getattr(row, "strategy_id", None) is not None:
                        strategy_id = int(row.strategy_id)
                    if getattr(row, "deployment_id", None) is not None:
                        deployment_id = int(row.deployment_id)
            except Exception:  # noqa: BLE001
                pass
        return qty, strategy_id, deployment_id, entry_price

    def _auto_slot(
        self, uba: int, broker: str, sym: str
    ) -> tuple[int | None, int | None, bool]:
        if broker != "UPBIT":
            return None, None, False
        try:
            from stock_platform.operation.upbit_full_market.entities import (
                UpbitPositionSlotEntity,
            )

            row = self._session.scalar(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba,
                    UpbitPositionSlotEntity.symbol == sym,
                    UpbitPositionSlotEntity.status.in_(
                        list(ACTIVE_SLOT_STATUSES)
                    ),
                )
            )
            if row is None:
                return None, None, False
            return (
                int(row.slot_id)
                if getattr(row, "slot_id", None) is not None
                else None,
                int(row.slot_no) if row.slot_no is not None else None,
                True,
            )
        except Exception:  # noqa: BLE001
            return None, None, False

    def _broker_position_qty(
        self, uba: int, broker: str, sym: str
    ) -> Decimal:
        row = self._session.scalar(
            select(BrokerPositionSnapshotEntity).where(
                BrokerPositionSnapshotEntity.user_broker_account_id == uba,
                BrokerPositionSnapshotEntity.broker_code == broker,
                BrokerPositionSnapshotEntity.symbol == sym,
                BrokerPositionSnapshotEntity.snapshot_status == "ACTIVE",
            )
        )
        if row is None:
            return ZERO
        return Decimal(str(row.quantity or 0))

    def _auto_open_order_count(
        self, uba: int, broker: str, sym: str
    ) -> int:
        rows = list(
            self._session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.broker_code == broker,
                    TradingOrderEntity.symbol == sym,
                    TradingOrderEntity.status_code.in_(
                        list(OPEN_ORDER_STATUSES)
                    ),
                    TradingOrderEntity.strategy_id.is_not(None),
                )
            )
        )
        return len(rows)

    def _manual_open_order_count(
        self, uba: int, broker: str, sym: str
    ) -> int:
        rows = list(
            self._session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.broker_code == broker,
                    TradingOrderEntity.symbol == sym,
                    TradingOrderEntity.status_code.in_(
                        list(OPEN_ORDER_STATUSES)
                    ),
                    TradingOrderEntity.strategy_id.is_(None),
                )
            )
        )
        return len(rows)

    def _broker_pending_without_local(
        self, uba: int, broker: str, sym: str
    ) -> int:
        pendings = list(
            self._session.scalars(
                select(BrokerPendingOrderEntity).where(
                    BrokerPendingOrderEntity.user_broker_account_id == uba,
                    BrokerPendingOrderEntity.broker_code == broker,
                    BrokerPendingOrderEntity.symbol == sym,
                )
            )
        )
        if not pendings:
            return 0
        count = 0
        for p in pendings:
            local = self._session.scalar(
                select(TradingOrderEntity.order_id).where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.broker_code == broker,
                    TradingOrderEntity.broker_order_id
                    == str(p.broker_order_id),
                )
            )
            if local is None:
                count += 1
        return count
