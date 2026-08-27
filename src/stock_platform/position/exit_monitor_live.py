"""UPBIT LIVE Position Exit Monitor — 포지션/시세/중복 SELL 가드.

Broker adapter 직접 호출 금지. 주문은 OES만 사용한다.
high-water는 BrokerPositionSnapshot.raw_data에 저장 (신규 테이블 없음).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from stock_platform.broker.account_models import BrokerPositionSnapshotEntity
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.exit_risk import (
    PENDING_SELL_STATUSES,
    is_order_outstanding_for_sell,
    load_pending_sell_quantity,
)
from stock_platform.trading.account_models import UserBrokerAccount


ZERO = Decimal("0")
HIGH_WATER_KEY = "exit_monitor_high_water"
SOURCE_EXIT_MONITOR = "POSITION_EXIT_MONITOR"
EXIT_RULE_VERSION = "exit_reliability_v1"

# Exit lifecycle (snapshot raw_data — parallel SoT 금지)
STATE_OPEN_MONITORING = "OPEN_MONITORING"
STATE_TRAILING_ARMED = "TRAILING_ARMED"
STATE_TRAILING_TRIGGERED = "TRAILING_TRIGGERED"
STATE_EXIT_ORDER_PENDING = "EXIT_ORDER_PENDING"
STATE_EXIT_SUBMITTED = "EXIT_SUBMITTED"
STATE_EXIT_FILLED = "EXIT_FILLED"
STATE_CLOSED = "CLOSED"

# 제출 실패 후 재시도는 허용하되, Telegram/event는 억제
_TRIGGERED_OR_PENDING = frozenset(
    {
        STATE_TRAILING_TRIGGERED,
        STATE_EXIT_ORDER_PENDING,
        STATE_EXIT_SUBMITTED,
        STATE_EXIT_FILLED,
        STATE_CLOSED,
    }
)

# FILLED 직후 스냅샷 미반영 race — 이 상태면 새 EXIT 금지
_INFLIGHT_OR_DONE_EXIT_STATUSES = PENDING_SELL_STATUSES + (
    "FILLED",
    "SUBMITTED",
)


def _as_decimal(value: object) -> Decimal:
    try:
        qty = Decimal(str(value if value is not None else 0))
    except Exception:  # noqa: BLE001
        return ZERO
    return qty


def read_persisted_high_water(raw_data: object) -> Decimal | None:
    """스냅샷 raw_data의 persisted high-water. 없으면 None (fail-closed)."""

    if not isinstance(raw_data, dict):
        return None
    raw = raw_data.get(HIGH_WATER_KEY)
    if raw is None:
        nested = raw_data.get("exit_monitor")
        if isinstance(nested, dict):
            raw = nested.get("high_water")
    if raw is None:
        return None
    value = _as_decimal(raw)
    return value if value > ZERO else None


def persist_high_water(
    row: BrokerPositionSnapshotEntity,
    *,
    high_water: Decimal,
) -> None:
    """trailing high-water를 기존 snapshot raw_data에 기록한다."""

    payload: dict[str, Any] = {}
    current = getattr(row, "raw_data", None)
    if isinstance(current, dict):
        payload = dict(current)
    payload[HIGH_WATER_KEY] = str(high_water)
    nested = dict(payload.get("exit_monitor") or {})
    nested["high_water"] = str(high_water)
    nested["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["exit_monitor"] = nested
    row.raw_data = payload
    try:
        flag_modified(row, "raw_data")
    except Exception:  # noqa: BLE001
        # 단위 테스트 SimpleNamespace 등 mapped instance가 아닌 경우
        pass


def resolve_trailing_high_water(
    row: BrokerPositionSnapshotEntity,
    *,
    entry: Decimal,
    current_price: Decimal,
) -> tuple[Decimal, bool]:
    """(평가용 high-water, trailing 허용 여부).

    persisted 값이 없으면 이번 tick은 trailing 금지 후 저장만 한다.
    restart 후 current를 peak로 오인하는 잘못된 SELL을 막는다.
    """

    persisted = read_persisted_high_water(getattr(row, "raw_data", None))
    observed = max(entry, current_price, ZERO)
    if persisted is None or persisted <= ZERO:
        persist_high_water(row, high_water=observed)
        # trailing은 highest > entry 필요 — entry만 주면 미발화
        return entry, False
    new_high = max(persisted, observed)
    if new_high > persisted:
        persist_high_water(row, high_water=new_high)
        # peak 갱신 시 trailing armed provenance (가벼운 write)
        mark_trailing_armed(
            row,
            peak_price=new_high,
            binding_id=None,
        )
    return new_high, True


def _exit_monitor_nested(raw_data: object) -> dict[str, Any]:
    if not isinstance(raw_data, dict):
        return {}
    nested = raw_data.get("exit_monitor")
    return dict(nested) if isinstance(nested, dict) else {}


def read_exit_lifecycle(raw_data: object) -> dict[str, Any]:
    """snapshot raw_data의 exit lifecycle (없으면 빈 dict)."""

    nested = _exit_monitor_nested(raw_data)
    life = nested.get("lifecycle")
    return dict(life) if isinstance(life, dict) else {}


def persist_exit_lifecycle(
    row: BrokerPositionSnapshotEntity,
    lifecycle: dict[str, Any],
) -> None:
    """exit lifecycle을 snapshot raw_data에 병합 저장."""

    payload: dict[str, Any] = {}
    current = getattr(row, "raw_data", None)
    if isinstance(current, dict):
        payload = dict(current)
    nested = dict(payload.get("exit_monitor") or {})
    nested["lifecycle"] = dict(lifecycle)
    nested["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["exit_monitor"] = nested
    row.raw_data = payload
    try:
        flag_modified(row, "raw_data")
    except Exception:  # noqa: BLE001
        pass


def mark_trailing_armed(
    row: BrokerPositionSnapshotEntity,
    *,
    peak_price: Decimal,
    binding_id: int | None,
) -> None:
    """peak > entry 구간 — TRAILING_ARMED provenance (alert 없음)."""

    life = read_exit_lifecycle(getattr(row, "raw_data", None))
    state = str(life.get("state") or STATE_OPEN_MONITORING)
    if state in _TRIGGERED_OR_PENDING:
        # trigger 이후 peak 갱신은 peak만 반영
        life["peak_price"] = str(peak_price)
        life["peak_at"] = datetime.now(timezone.utc).isoformat()
        persist_exit_lifecycle(row, life)
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    life.update(
        {
            "state": STATE_TRAILING_ARMED,
            "peak_price": str(peak_price),
            "peak_at": now_iso,
            "trailing_armed_at": life.get("trailing_armed_at") or now_iso,
            "binding_id": binding_id
            if binding_id is not None
            else life.get("binding_id"),
            "exit_rule_version": EXIT_RULE_VERSION,
        }
    )
    persist_exit_lifecycle(row, life)


def clear_exit_trigger_cycle(
    row: BrokerPositionSnapshotEntity,
) -> None:
    """조건 해제 시 새 edge cycle 허용 — submitted/filled는 유지."""

    life = read_exit_lifecycle(getattr(row, "raw_data", None))
    state = str(life.get("state") or "")
    if state in {
        STATE_EXIT_SUBMITTED,
        STATE_EXIT_FILLED,
        STATE_CLOSED,
    }:
        return
    if state not in {
        STATE_TRAILING_TRIGGERED,
        STATE_EXIT_ORDER_PENDING,
        STATE_TRAILING_ARMED,
    }:
        return
    peak = life.get("peak_price")
    persist_exit_lifecycle(
        row,
        {
            "state": STATE_OPEN_MONITORING,
            "peak_price": peak,
            "peak_at": life.get("peak_at"),
            "trailing_armed_at": life.get("trailing_armed_at"),
            "binding_id": life.get("binding_id"),
            "exit_rule_version": EXIT_RULE_VERSION,
            "cleared_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def already_notified_exit_submit(lifecycle: dict[str, Any]) -> bool:
    return bool(lifecycle.get("telegram_submitted_sent"))


def exit_cycle_key(
    *,
    uba_id: int,
    binding_id: int | None,
    reason: str,
) -> str:
    bind = int(binding_id) if binding_id is not None else 0
    return f"EXIT:{int(uba_id)}:{bind}:{str(reason).upper()}:{EXIT_RULE_VERSION}"


def load_open_strategy_binding(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    broker_code: str = "UPBIT",
) -> Any | None:
    """OPEN strategy binding — trailing/exit eligibility SoT."""

    from stock_platform.risk_engine.strategy_owned_entities import (
        BINDING_STATUS_OPEN,
        StrategyPositionBindingEntity,
    )

    return session.scalar(
        select(StrategyPositionBindingEntity)
        .where(
            StrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id),
            StrategyPositionBindingEntity.broker_code
            == str(broker_code).upper(),
            StrategyPositionBindingEntity.symbol == str(symbol).upper(),
            StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
        )
        .order_by(StrategyPositionBindingEntity.opened_at.desc())
        .limit(1)
    )


def load_broker_position_snapshot(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
) -> BrokerPositionSnapshotEntity | None:
    return session.scalar(
        select(BrokerPositionSnapshotEntity).where(
            BrokerPositionSnapshotEntity.user_broker_account_id
            == int(user_broker_account_id),
            BrokerPositionSnapshotEntity.broker_code == "UPBIT",
            BrokerPositionSnapshotEntity.symbol == str(symbol).upper(),
            BrokerPositionSnapshotEntity.snapshot_status
            == BrokerSnapshotStatus.ACTIVE.value,
        )
    )


def is_live_exit_eligible(
    *,
    quantity: Decimal,
    binding: Any | None,
    has_active_exit_order: bool,
) -> tuple[bool, str]:
    """Trailing/SL/TP 평가 전 canonical eligibility."""

    if binding is None:
        return False, "NO_OPEN_BINDING"
    qty = Decimal(str(getattr(binding, "owned_quantity", 0) or 0))
    if qty <= ZERO and quantity <= ZERO:
        return False, "ZERO_QUANTITY"
    if has_active_exit_order:
        return False, "ACTIVE_EXIT_ORDER"
    status = str(getattr(binding, "status", "") or "").upper()
    if status != "OPEN":
        return False, "BINDING_NOT_OPEN"
    return True, "OK"


def quote_is_fresh(quoted_at: datetime | None, *, stale_seconds: float) -> bool:
    if quoted_at is None:
        return False
    moment = quoted_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - moment).total_seconds()
    return age <= float(stale_seconds)


def quote_snapshot_is_fresh(
    snap: object | None,
    *,
    stale_seconds: float,
) -> bool:
    """Exit SoT freshness — quoted_at(거래시각)과 updated_at(적재 확인) 중 최신.

    거래소 ticker timestamp만 보면 적재는 됐는데 age>threshold로
    오판(false stale)할 수 있다. updated_at이 최근이면 WS 확인된 것.
    """

    if snap is None:
        return False
    quoted_at = getattr(snap, "quoted_at", None)
    updated_at = getattr(snap, "updated_at", None)
    moments: list[datetime] = []
    for value in (quoted_at, updated_at):
        if value is None:
            continue
        moment = value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        moments.append(moment)
    if not moments:
        return False
    return quote_is_fresh(max(moments), stale_seconds=stale_seconds)


def resolve_upbit_live_price(
    session: Session,
    *,
    symbol: str,
    stale_seconds: float,
) -> Decimal | None:
    """수집된 QuoteSnapshot만 사용. broker REST 금지. stale이면 None."""

    from stock_platform.markets.repository import (
        InstrumentRepository,
        QuoteSnapshotRepository,
    )
    from stock_platform.markets.service import (
        InstrumentNotFoundError,
        InstrumentService,
        QuoteSnapshotService,
    )

    try:
        service = QuoteSnapshotService(
            QuoteSnapshotRepository(session),
            InstrumentService(InstrumentRepository(session)),
        )
        snap = service.get("UPBIT", str(symbol).upper())
    except InstrumentNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        return None
    if snap is None:
        return None
    price = _as_decimal(getattr(snap, "trade_price", None))
    if price <= ZERO:
        return None
    if not quote_snapshot_is_fresh(snap, stale_seconds=stale_seconds):
        return None
    return price


def has_blocking_live_exit_sell(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    snapshot_synchronized_at: datetime | None,
) -> bool:
    """pending SELL 또는 스냅샷 이후 inflight/FILLED EXIT가 있으면 True.

    안전 기본값: 동일 포지션에 이미 EXIT가 있으면 새 SELL을 만들지 않는다.
    """

    pending = load_pending_sell_quantity(
        session,
        symbol=symbol,
        user_broker_account_id=int(user_broker_account_id),
        paper_account_id=None,
    )
    if pending > ZERO:
        return True

    stmt = select(TradingOrderEntity).where(
        TradingOrderEntity.user_broker_account_id
        == int(user_broker_account_id),
        TradingOrderEntity.symbol == str(symbol).upper(),
        TradingOrderEntity.side_code == "SELL",
        TradingOrderEntity.status_code.in_(_INFLIGHT_OR_DONE_EXIT_STATUSES),
    )
    rows = list(session.scalars(stmt))
    if not rows:
        return False
    sync_at = snapshot_synchronized_at
    if sync_at is not None and sync_at.tzinfo is None:
        sync_at = sync_at.replace(tzinfo=timezone.utc)
    for row in rows:
        if is_order_outstanding_for_sell(row):
            return True
        status = str(getattr(row, "status_code", "") or "").upper()
        meta = getattr(row, "metadata_payload", None) or {}
        source = ""
        if isinstance(meta, dict):
            source = str(meta.get("source") or "")
        created = getattr(row, "created_at", None)
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if source == SOURCE_EXIT_MONITOR and sync_at is not None:
            if created is not None and created >= sync_at:
                return True
        elif source == SOURCE_EXIT_MONITOR and status == "FILLED":
            return True
    return False


def list_upbit_live_position_rows(
    session: Session,
) -> list[tuple[BrokerPositionSnapshotEntity, UserBrokerAccount]]:
    """ACTIVE UPBIT 스냅샷 × 활성 UBA. KIWOOM 제외. 다른 UBA는 섞지 않음."""

    stmt = (
        select(BrokerPositionSnapshotEntity, UserBrokerAccount)
        .join(
            UserBrokerAccount,
            UserBrokerAccount.user_broker_account_id
            == BrokerPositionSnapshotEntity.user_broker_account_id,
        )
        .where(
            BrokerPositionSnapshotEntity.broker_code == "UPBIT",
            BrokerPositionSnapshotEntity.snapshot_status
            == BrokerSnapshotStatus.ACTIVE.value,
            BrokerPositionSnapshotEntity.quantity > ZERO,
            BrokerPositionSnapshotEntity.user_broker_account_id.is_not(
                None
            ),
            UserBrokerAccount.broker_code == "UPBIT",
            UserBrokerAccount.is_active.is_(True),
        )
    )
    return list(session.execute(stmt).all())
