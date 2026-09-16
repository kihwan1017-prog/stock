"""LIVE ENTRY open-order exposure — MANUAL/AUTO/UNKNOWN 분리 (KIWOOM+UPBIT).

AUTO max_open_orders 는 auto_open_count 만 비교한다.
unmapped remote (local AUTO 없음) = MANUAL → AUTO risk 제외.
UNKNOWN open > 0 또는 remote state 불명 → fail-closed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.order_ownership import (
    ORDER_OWNERSHIP_UNKNOWN,
    classify_local_open_order,
    classify_unmapped_remote_open_order,
)
from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
)


LOCAL_OPEN_STATUSES = (
    "CREATED",
    "PENDING",
    "SENT",
    "ACCEPTED",
    "PARTIALLY_FILLED",
    "CANCEL_REQUESTED",
    "REPLACE_REQUESTED",
)

STATE_FRESH = "FRESH"
STATE_STALE = "STALE"
STATE_UNKNOWN = "UNKNOWN"
STATE_UNAVAILABLE = "UNAVAILABLE"
STATE_NOT_APPLICABLE = "NOT_APPLICABLE"
STATE_LOCAL_ONLY = "LOCAL_ONLY"

REMOTE_OPEN_CHECK_FAILED = "REMOTE_OPEN_CHECK_FAILED"
OPEN_ORDER_LIMIT_EXCEEDED = "OPEN_ORDER_LIMIT_EXCEEDED"

# 주문마다 REST 재호출 방지. 대시보드 TTL(20s)보다 짧게.
_REMOTE_VIEW_TTL_SECONDS = 15.0
_REMOTE_VIEW_CACHE: dict[int, tuple[float, "RemoteOpenOrderView"]] = {}


@dataclass(frozen=True, slots=True)
class LocalOpenOrder:
    order_id: int
    broker_order_id: str | None
    client_order_id: str | None
    client_order_identifier: str | None
    symbol: str | None = None
    strategy_id: int | None = None
    strategy_deployment_id: int | None = None
    metadata_payload: dict[str, Any] | None = None
    owner: str = OWNER_MANUAL


@dataclass(frozen=True, slots=True)
class RemoteOpenOrderRef:
    uuid: str
    identifier: str | None = None
    market: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteOpenOrderView:
    """Broker wait/watch 스냅샷. REST 원문/시크릿 없음."""

    status: str
    orders: tuple[RemoteOpenOrderRef, ...] = ()
    source: str = "NONE"
    fetched_at_monotonic: float | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATE_FRESH

    @property
    def uuids(self) -> frozenset[str]:
        return frozenset(item.uuid for item in self.orders if item.uuid)

    @property
    def identifiers(self) -> frozenset[str]:
        return frozenset(
            item.identifier for item in self.orders if item.identifier
        )


@dataclass(frozen=True, slots=True)
class OpenOrderExposure:
    """open-order 집계.

    canonical_count = auto_open_count (AUTO max_open_orders 게이트용, 하위호환).
    """

    auto_open_count: int
    manual_open_count: int
    unknown_open_count: int
    total_open_count: int
    local_open_count: int
    local_auto_count: int
    local_manual_count: int
    remote_open_count: int
    remote_unmapped_count: int
    remote_unmapped_manual_count: int
    mapped_remote_count: int
    remote_state: str
    remote_state_ok: bool
    source: str
    reason_code: str | None = None

    @property
    def canonical_count(self) -> int:
        """하위호환: AUTO risk 비교에 쓰는 값."""

        return int(self.auto_open_count)

    def as_detail(self) -> dict[str, Any]:
        return {
            # 하위호환 (AUTO count)
            "open_order_count": self.auto_open_count,
            "auto_open_orders": self.auto_open_count,
            "manual_open_orders": self.manual_open_count,
            "unknown_open_orders": self.unknown_open_count,
            "total_open_orders": self.total_open_count,
            "local_open_order_count": self.local_open_count,
            "local_auto_open_order_count": self.local_auto_count,
            "local_manual_open_order_count": self.local_manual_count,
            "remote_open_order_count": self.remote_open_count,
            "remote_unmapped_open_order_count": self.remote_unmapped_count,
            "remote_unmapped_manual_open_order_count": (
                self.remote_unmapped_manual_count
            ),
            "mapped_remote_open_order_count": self.mapped_remote_count,
            "remote_open_state": self.remote_state,
            "open_order_source": self.source,
            "ownership_reason_code": self.reason_code,
        }


def _norm_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.lower()


def load_local_open_orders(
    session: Session,
    *,
    uba_id: int,
    broker_code: str | None = None,
) -> list[LocalOpenOrder]:
    stmt = select(TradingOrderEntity).where(
        TradingOrderEntity.user_broker_account_id == int(uba_id),
        TradingOrderEntity.status_code.in_(LOCAL_OPEN_STATUSES),
    )
    if broker_code:
        stmt = stmt.where(
            TradingOrderEntity.broker_code == str(broker_code).upper()
        )
    rows: list[LocalOpenOrder] = []
    broker_u = str(broker_code or "").upper()
    for entity in session.scalars(stmt):
        decision = classify_local_open_order(
            broker=broker_u or str(getattr(entity, "broker_code", "") or ""),
            uba_id=int(uba_id),
            symbol=getattr(entity, "symbol", None),
            local_order_id=int(entity.order_id),
            broker_order_id=getattr(entity, "broker_order_id", None),
            strategy_id=getattr(entity, "strategy_id", None),
            strategy_deployment_id=getattr(
                entity, "strategy_deployment_id", None
            ),
            metadata_payload=getattr(entity, "metadata_payload", None),
        )
        rows.append(
            LocalOpenOrder(
                order_id=int(entity.order_id),
                broker_order_id=getattr(entity, "broker_order_id", None),
                client_order_id=getattr(entity, "client_order_id", None),
                client_order_identifier=getattr(
                    entity, "client_order_identifier", None
                ),
                symbol=(
                    str(entity.symbol).upper()
                    if getattr(entity, "symbol", None)
                    else None
                ),
                strategy_id=(
                    int(entity.strategy_id)
                    if getattr(entity, "strategy_id", None) is not None
                    else None
                ),
                strategy_deployment_id=(
                    int(entity.strategy_deployment_id)
                    if getattr(entity, "strategy_deployment_id", None)
                    is not None
                    else None
                ),
                metadata_payload=(
                    dict(entity.metadata_payload)
                    if isinstance(
                        getattr(entity, "metadata_payload", None), dict
                    )
                    else None
                ),
                owner=decision.owner,
            )
        )
    return rows


def _local_identity_set(rows: Iterable[LocalOpenOrder]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        for raw in (
            row.broker_order_id,
            row.client_order_id,
            row.client_order_identifier,
        ):
            key = _norm_id(raw)
            if key:
                keys.add(key)
    return keys


def _local_auto_identity_set(rows: Iterable[LocalOpenOrder]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        if row.owner != OWNER_AUTO:
            continue
        for raw in (
            row.broker_order_id,
            row.client_order_id,
            row.client_order_identifier,
        ):
            key = _norm_id(raw)
            if key:
                keys.add(key)
    return keys


def combine_open_order_exposure(
    *,
    local_orders: list[LocalOpenOrder],
    remote_view: RemoteOpenOrderView,
    source: str,
    broker: str = "UPBIT",
    uba_id: int = 0,
) -> OpenOrderExposure:
    """local AUTO + mapped remote AUTO 만 auto_open_count.

    unmapped remote → MANUAL (계좌 전체 AUTO pause 금지).
    """

    local_count = len(local_orders)
    local_auto = sum(1 for r in local_orders if r.owner == OWNER_AUTO)
    local_manual = sum(1 for r in local_orders if r.owner == OWNER_MANUAL)
    local_unknown = sum(1 for r in local_orders if r.owner == OWNER_UNKNOWN)

    local_ids = _local_identity_set(local_orders)
    local_auto_ids = _local_auto_identity_set(local_orders)

    mapped = 0
    unmapped_manual = 0
    unmapped_unknown = 0
    for item in remote_view.orders:
        uid = _norm_id(item.uuid)
        ident = _norm_id(item.identifier)
        matched = (uid and uid in local_ids) or (
            ident and ident in local_ids
        )
        if matched:
            mapped += 1
            continue
        # unmapped: local AUTO 없음 → MANUAL
        matched_auto = (uid and uid in local_auto_ids) or (
            ident and ident in local_auto_ids
        )
        decision = classify_unmapped_remote_open_order(
            broker=broker,
            uba_id=int(uba_id),
            symbol=item.market,
            broker_order_id=item.uuid,
            has_matching_local_auto=matched_auto,
        )
        if decision.owner == OWNER_AUTO:
            # 이론상 unmapped+auto 는 없어야 함 — UNKNOWN 보수
            unmapped_unknown += 1
        elif decision.owner == OWNER_UNKNOWN:
            unmapped_unknown += 1
        else:
            unmapped_manual += 1

    unmapped = unmapped_manual + unmapped_unknown
    auto_count = local_auto  # mapped remote 는 이미 local 에 포함
    manual_count = local_manual + unmapped_manual
    unknown_count = local_unknown + unmapped_unknown
    total = auto_count + manual_count + unknown_count

    reason = None
    if unknown_count > 0:
        reason = ORDER_OWNERSHIP_UNKNOWN
    if not remote_view.ok and remote_view.status not in {
        STATE_NOT_APPLICABLE,
        STATE_LOCAL_ONLY,
    }:
        reason = REMOTE_OPEN_CHECK_FAILED

    return OpenOrderExposure(
        auto_open_count=auto_count,
        manual_open_count=manual_count,
        unknown_open_count=unknown_count,
        total_open_count=total,
        local_open_count=local_count,
        local_auto_count=local_auto,
        local_manual_count=local_manual,
        remote_open_count=len(remote_view.orders),
        remote_unmapped_count=unmapped,
        remote_unmapped_manual_count=unmapped_manual,
        mapped_remote_count=mapped,
        remote_state=remote_view.status,
        remote_state_ok=remote_view.ok
        or remote_view.status
        in {STATE_NOT_APPLICABLE, STATE_LOCAL_ONLY},
        source=source,
        reason_code=reason,
    )


def clear_remote_open_view_cache(uba_id: int | None = None) -> None:
    if uba_id is None:
        _REMOTE_VIEW_CACHE.clear()
        return
    _REMOTE_VIEW_CACHE.pop(int(uba_id), None)


def fetch_upbit_remote_open_view(
    session: Session,
    *,
    uba_id: int,
    now_monotonic: float | None = None,
    ttl_seconds: float = _REMOTE_VIEW_TTL_SECONDS,
    rest_loader: Callable[[], tuple[list[dict[str, Any]], list[dict[str, Any]]]]
    | None = None,
) -> RemoteOpenOrderView:
    """wait+watch UUID 스냅샷. 프로세스 TTL 캐시로 주문마다 REST 금지."""

    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    cached = _REMOTE_VIEW_CACHE.get(int(uba_id))
    if cached is not None:
        cached_at, view = cached
        if now - cached_at <= ttl_seconds and view.status == STATE_FRESH:
            return view
        if now - cached_at > ttl_seconds and view.status == STATE_FRESH:
            stale = RemoteOpenOrderView(
                status=STATE_STALE,
                orders=view.orders,
                source=view.source,
                fetched_at_monotonic=cached_at,
                error="TTL_EXPIRED",
            )
        else:
            stale = None
    else:
        stale = None

    try:
        if rest_loader is None:
            wait_rows, watch_rows = _rest_list_upbit_open_orders(
                session, uba_id=int(uba_id)
            )
        else:
            wait_rows, watch_rows = rest_loader()
    except Exception as exc:  # noqa: BLE001
        if stale is not None:
            return stale
        view = RemoteOpenOrderView(
            status=STATE_UNKNOWN,
            source="UPBIT_REST",
            error=exc.__class__.__name__,
        )
        return view

    refs: list[RemoteOpenOrderRef] = []
    seen: set[str] = set()
    for row in list(wait_rows) + list(watch_rows):
        uid = _norm_id(row.get("uuid"))
        if not uid or uid in seen:
            continue
        seen.add(uid)
        ident = _norm_id(row.get("identifier"))
        market = str(row.get("market") or "").strip().upper() or None
        refs.append(
            RemoteOpenOrderRef(uuid=uid, identifier=ident, market=market)
        )
    view = RemoteOpenOrderView(
        status=STATE_FRESH,
        orders=tuple(refs),
        source="UPBIT_REST_WAIT_WATCH",
        fetched_at_monotonic=now,
    )
    _REMOTE_VIEW_CACHE[int(uba_id)] = (now, view)
    return view


def _rest_list_upbit_open_orders(
    session: Session, *, uba_id: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from stock_platform.broker.credential_adapter_factory import (
        build_upbit_settings_from_vault,
    )
    from stock_platform.broker.credential_vault_service import (
        BrokerCredentialVaultService,
    )
    from stock_platform.broker.upbit.order_client import UpbitOrderRestClient

    resolved = BrokerCredentialVaultService(session).resolve_for_runtime(
        int(uba_id),
        expected_broker="UPBIT",
        require_verified=True,
        touch_last_used=False,
    )
    client = UpbitOrderRestClient(
        settings=build_upbit_settings_from_vault(resolved),
        user_broker_account_id=int(uba_id),
    )
    wait = client.list_orders(state="wait", limit=100)
    watch = client.list_orders(state="watch", limit=100)
    return wait, watch


def _load_kiwoom_unmapped_pending_as_manual(
    session: Session, *, uba_id: int
) -> list[LocalOpenOrder]:
    """키움 BrokerPending 중 local TradingOrder 미매칭 = MANUAL open."""

    try:
        from stock_platform.broker.pending_entities import (
            BrokerPendingOrderEntity,
        )
    except Exception:  # noqa: BLE001
        return []

    pendings = list(
        session.scalars(
            select(BrokerPendingOrderEntity).where(
                BrokerPendingOrderEntity.user_broker_account_id == int(uba_id),
                BrokerPendingOrderEntity.broker_code == "KIWOOM",
            )
        )
    )
    if not pendings:
        return []
    extras: list[LocalOpenOrder] = []
    for p in pendings:
        broker_oid = getattr(p, "broker_order_id", None) or getattr(
            p, "order_no", None
        )
        if broker_oid:
            local = session.scalar(
                select(TradingOrderEntity.order_id).where(
                    TradingOrderEntity.user_broker_account_id == int(uba_id),
                    TradingOrderEntity.broker_code == "KIWOOM",
                    TradingOrderEntity.broker_order_id == str(broker_oid),
                )
            )
            if local is not None:
                continue
        extras.append(
            LocalOpenOrder(
                order_id=0,
                broker_order_id=str(broker_oid) if broker_oid else None,
                client_order_id=None,
                client_order_identifier=None,
                symbol=(
                    str(p.symbol).upper()
                    if getattr(p, "symbol", None)
                    else None
                ),
                owner=OWNER_MANUAL,
            )
        )
    return extras


def evaluate_live_open_order_exposure(
    session: Session,
    *,
    uba_id: int,
    broker_code: str,
    environment: str = "LIVE",
    remote_view: RemoteOpenOrderView | None = None,
    rest_loader: Callable[[], tuple[list[dict[str, Any]], list[dict[str, Any]]]]
    | None = None,
) -> OpenOrderExposure:
    """AUTO risk count = auto_open_count only."""

    broker = str(broker_code or "").upper()
    env = str(environment or "LIVE").upper()
    local_orders = load_local_open_orders(
        session,
        uba_id=int(uba_id),
        broker_code=broker if broker else None,
    )

    if env != "LIVE":
        empty = RemoteOpenOrderView(
            status=STATE_NOT_APPLICABLE, source=STATE_LOCAL_ONLY
        )
        return combine_open_order_exposure(
            local_orders=local_orders,
            remote_view=empty,
            source=STATE_LOCAL_ONLY,
            broker=broker or "UNKNOWN",
            uba_id=int(uba_id),
        )

    if broker == "KIWOOM":
        # remote REST 없음 — pending 미매칭을 MANUAL 로 합산
        local_orders = list(local_orders) + _load_kiwoom_unmapped_pending_as_manual(
            session, uba_id=int(uba_id)
        )
        empty = RemoteOpenOrderView(
            status=STATE_NOT_APPLICABLE, source=STATE_LOCAL_ONLY
        )
        return combine_open_order_exposure(
            local_orders=local_orders,
            remote_view=empty,
            source="KIWOOM_LOCAL_PLUS_PENDING",
            broker="KIWOOM",
            uba_id=int(uba_id),
        )

    if broker != "UPBIT":
        empty = RemoteOpenOrderView(
            status=STATE_NOT_APPLICABLE, source=STATE_LOCAL_ONLY
        )
        return combine_open_order_exposure(
            local_orders=local_orders,
            remote_view=empty,
            source=STATE_LOCAL_ONLY,
            broker=broker or "UNKNOWN",
            uba_id=int(uba_id),
        )

    view = remote_view or fetch_upbit_remote_open_view(
        session, uba_id=int(uba_id), rest_loader=rest_loader
    )
    source = view.source or "UPBIT_REMOTE"
    combined = combine_open_order_exposure(
        local_orders=local_orders,
        remote_view=view,
        source=source,
        broker="UPBIT",
        uba_id=int(uba_id),
    )
    if not combined.remote_state_ok:
        return OpenOrderExposure(
            auto_open_count=combined.auto_open_count,
            manual_open_count=combined.manual_open_count,
            unknown_open_count=combined.unknown_open_count,
            total_open_count=combined.total_open_count,
            local_open_count=combined.local_open_count,
            local_auto_count=combined.local_auto_count,
            local_manual_count=combined.local_manual_count,
            remote_open_count=combined.remote_open_count,
            remote_unmapped_count=combined.remote_unmapped_count,
            remote_unmapped_manual_count=combined.remote_unmapped_manual_count,
            mapped_remote_count=combined.mapped_remote_count,
            remote_state=combined.remote_state,
            remote_state_ok=False,
            source=combined.source,
            reason_code=REMOTE_OPEN_CHECK_FAILED,
        )
    return combined
