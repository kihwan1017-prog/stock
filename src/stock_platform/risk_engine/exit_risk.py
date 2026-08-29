"""Risk-reducing EXIT 분류 (서버 검증).

클라이언트의 is_risk_reducing 플래그는 신뢰하지 않는다.
보유 수량 SoT:
- LIVE/MOCK/LIVE_SHADOW: BrokerPositionSnapshot (UBA)
- PAPER: PaperPosition
outstanding SELL: 동일 계좌 TradingOrder remaining_quantity
"""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterator

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import TERMINAL_ORDER_STATUSES, OrderStatus


ZERO = Decimal("0")

# 기존 reason code 재사용
REASON_NO_POSITION_TO_SELL = "NO_POSITION_TO_SELL"
REASON_SELL_QUANTITY = "SELL_QUANTITY"
REASON_INVALID_ORDER_QUANTITY = "INVALID_ORDER_QUANTITY"

# 미체결 inflight — remaining을 sellable에서 차감
OUTSTANDING_INFLIGHT_SELL_STATUSES = (
    OrderStatus.CREATED.value,
    OrderStatus.PENDING.value,
    OrderStatus.SUBMITTING.value,
    OrderStatus.SENT.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
    OrderStatus.CANCEL_REQUESTED.value,
    OrderStatus.REPLACE_REQUESTED.value,
    # 일부 경로/모니터가 쓰는 비정규 표기
    "SUBMITTED",
    "QUEUED",
)

# broker 존재 불명 — oversell 방지로 outstanding
OUTSTANDING_UNKNOWN_SELL_STATUSES = (
    OrderStatus.AMBIGUOUS_SUBMISSION.value,
    OrderStatus.REMOTE_LOOKUP_PENDING.value,
    OrderStatus.MANUAL_REVIEW_REQUIRED.value,
)

# 하위 호환 alias (Exit Monitor 등)
PENDING_SELL_STATUSES = OUTSTANDING_INFLIGHT_SELL_STATUSES + (
    OUTSTANDING_UNKNOWN_SELL_STATUSES
)

_TERMINAL_STATUS_VALUES = frozenset(
    item.value for item in TERMINAL_ORDER_STATUSES
)

_LIVE_ENVIRONMENTS = {"LIVE", "LIVE_SHADOW", "MOCK"}

_PROCESS_EXIT_LOCKS: dict[tuple[int, int, str], threading.RLock] = {}
_PROCESS_EXIT_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True, slots=True)
class ExitClassification:
    """서버 측 EXIT 판정 결과."""

    is_risk_reducing_exit: bool
    reason_code: str | None
    held_quantity: Decimal
    pending_sell_quantity: Decimal
    sellable_quantity: Decimal
    side: str


def _as_qty(value: object) -> Decimal:
    try:
        qty = Decimal(str(value if value is not None else 0))
    except Exception:  # noqa: BLE001
        return ZERO
    return qty if qty > ZERO else ZERO


def _symbol_matches(item_symbol: object, symbol: str) -> bool:
    return str(item_symbol or "").strip().upper() == symbol


def _exchange_matches(item_exchange: object, exchange_code: str) -> bool:
    wanted = str(exchange_code or "").strip().upper()
    got = str(item_exchange or "").strip().upper()
    if not wanted or not got:
        return True
    if got == wanted:
        return True
    # UPBIT 스냅샷/주문 표기 차이
    aliases = {"UPBIT", "CRYPTO"}
    return got in aliases and wanted in aliases


def _remaining_sell_qty(row: Any) -> Decimal:
    remaining = _as_qty(getattr(row, "remaining_quantity", None))
    if remaining <= ZERO:
        remaining = _as_qty(getattr(row, "order_quantity", None)) - _as_qty(
            getattr(row, "filled_quantity", None)
        )
    return remaining if remaining > ZERO else ZERO


def _is_submission_unknown(row: Any) -> bool:
    status = str(getattr(row, "status_code", "") or "").strip().upper()
    if status in OUTSTANDING_UNKNOWN_SELL_STATUSES:
        return True
    reason = str(getattr(row, "reason_code", "") or "").strip().upper()
    if reason in {
        "SUBMISSION_UNKNOWN",
        "AMBIGUOUS_SUBMISSION",
        "REMOTE_LOOKUP_PENDING",
        "MANUAL_REVIEW_REQUIRED",
        "MANUAL_REVIEW",
        "AMBIGUOUS",
    }:
        return True
    if "SUBMISSION_UNKNOWN" in reason:
        return True
    meta = getattr(row, "metadata_payload", None) or {}
    if not isinstance(meta, dict):
        return False
    if meta.get("submission_unknown") is True:
        return True
    state = str(meta.get("submission_state") or "").strip().upper()
    return state in {"UNKNOWN", "SUBMISSION_UNKNOWN"}


# Outbox 상태가 broker 전송 불명이면 fail-closed outstanding
_OUTSTANDING_CONFIRMATION = frozenset(
    {
        "BROKER_CONFIRMATION_REQUIRED",
        "REMOTE_LOOKUP_PENDING",
        "MANUAL_REVIEW_REQUIRED",
        "MANUAL_REVIEW",
    }
)
# 운영자 재조정으로 "미전송"이 증명된 경우에만 outstanding에서 제외.
# CONFIRMED_ABSENT = resolve-not-submitted API가 쓰는 confirmation_status.
_DEFINITIVE_NOT_SUBMITTED = frozenset(
    {
        "CONFIRMED_NOT_SUBMITTED",
        "BROKER_NOT_REACHED_LOCAL_VALIDATION_FAILURE",
        "CONFIRMED_ABSENT",
    }
)


def _is_real_datetime_or_text(value: Any) -> bool:
    if value is None:
        return False
    # 단위테스트 MagicMock 이 truthy 로 잡히지 않게
    if type(value).__name__ in {"MagicMock", "Mock", "AsyncMock"}:
        return False
    return True


def outbox_counts_as_outstanding_sell(outbox: Any | None) -> bool:
    """dispatch_intent/AMBIGUOUS 는 원격 미존재 증명 전까지 outstanding."""

    if outbox is None:
        return False
    confirmation = str(
        getattr(outbox, "confirmation_status", "") or ""
    ).strip().upper()
    manual_reason = str(
        getattr(outbox, "manual_review_reason", "") or ""
    ).strip().upper()
    last_error = str(getattr(outbox, "last_error", "") or "").strip().upper()
    if (
        confirmation in _DEFINITIVE_NOT_SUBMITTED
        or manual_reason in _DEFINITIVE_NOT_SUBMITTED
        or any(code in last_error for code in _DEFINITIVE_NOT_SUBMITTED)
    ):
        return False
    status = str(getattr(outbox, "status_code", "") or "").strip().upper()
    if status in {"AMBIGUOUS", "MANUAL_REVIEW"}:
        return True
    if confirmation in _OUTSTANDING_CONFIRMATION:
        return True
    intent = getattr(outbox, "dispatch_intent_at", None)
    if _is_real_datetime_or_text(intent):
        return True
    if status in {"PROCESSING", "RETRY"}:
        return True
    return False


def _related_outbox(session: Session, row: Any) -> Any | None:
    attached = getattr(row, "outbox", None)
    if attached is not None:
        return attached
    raw_id = getattr(row, "order_id", None)
    try:
        order_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    try:
        from stock_platform.order.outbox_entities import OrderOutbox

        return session.scalar(
            select(OrderOutbox)
            .where(OrderOutbox.order_id == order_id)
            .order_by(OrderOutbox.outbox_id.desc())
            .limit(1)
        )
    except Exception:  # noqa: BLE001
        return None


def _order_row_counts_as_outstanding_sell(row: Any) -> bool:
    """TradingOrder 행만 보고 outstanding 여부. Outbox는 별도."""

    status = str(getattr(row, "status_code", "") or "").strip().upper()
    if status in OUTSTANDING_INFLIGHT_SELL_STATUSES:
        return True
    if _is_submission_unknown(row):
        return True
    broker_id = str(getattr(row, "broker_order_id", None) or "").strip()
    if status == OrderStatus.FAILED.value:
        return bool(broker_id)
    if status == OrderStatus.IDENTITY_CONFLICT.value:
        return True
    if status in _TERMINAL_STATUS_VALUES:
        return False
    # 미등록 상태는 remaining이 있으면 fail-closed
    return _remaining_sell_qty(row) > ZERO


def is_order_outstanding_for_sell(
    order: Any,
    outbox: Any | None = None,
) -> bool:
    """동일 포지션 전량 EXIT를 막을 outstanding SELL 여부 (주문+Outbox).

    이 함수가 DatabaseBackedRiskOrderGuard / EXIT 분류 /
    Strategy duplicate / Exit Monitor / pending-sell loader 의 단일 SoT.

    CANCELLED/FILLED 등 터미널 주문은 Outbox에 남은 dispatch_intent_at 만으로
    재차단하지 않는다 (과거 zero-fill cancel 후 신규 EXIT 불능 방지).
    """

    if outbox is None:
        outbox = getattr(order, "outbox", None)
    if _order_row_counts_as_outstanding_sell(order):
        return True
    status = str(getattr(order, "status_code", "") or "").strip().upper()
    if status in _TERMINAL_STATUS_VALUES:
        return False
    if outbox_counts_as_outstanding_sell(outbox):
        return True
    return False


def order_counts_as_outstanding_sell(
    row: Any,
    outbox: Any | None = None,
) -> bool:
    """하위 호환 alias — is_order_outstanding_for_sell 과 동일."""

    return is_order_outstanding_for_sell(row, outbox)


def _scope_key(
    user_broker_account_id: int | None,
    paper_account_id: int | None,
    symbol: str,
) -> tuple[int, int, str]:
    return (
        int(user_broker_account_id or 0),
        int(paper_account_id or 0),
        str(symbol or "").strip().upper(),
    )


def _process_lock_for(key: tuple[int, int, str]) -> threading.RLock:
    with _PROCESS_EXIT_LOCKS_GUARD:
        lock = _PROCESS_EXIT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_EXIT_LOCKS[key] = lock
        return lock


def _advisory_lock_key(scope: tuple[int, int, str]) -> int:
    raw = f"exit-sell|{scope[0]}|{scope[1]}|{scope[2]}".encode()
    digest = hashlib.blake2b(raw, digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF


def acquire_exit_sell_scope_lock(
    session: Session,
    *,
    user_broker_account_id: int | None,
    paper_account_id: int | None,
    symbol: str,
) -> None:
    """UBA+symbol SELL 직렬화. PostgreSQL xact advisory lock (없으면 no-op)."""

    scope = _scope_key(user_broker_account_id, paper_account_id, symbol)
    if not scope[2]:
        return
    try:
        bind = session.get_bind()
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "")
        if dialect != "postgresql":
            return
        session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"),
            {"k": _advisory_lock_key(scope)},
        )
    except Exception:  # noqa: BLE001
        # SQLite/MagicMock/테스트 — 프로세스 lock이 보조한다
        return


@contextmanager
def exit_sell_transaction_fence(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
    symbol: str = "",
    side: str = "",
) -> Iterator[None]:
    """동일 계좌·종목 SELL을 한 트랜잭션/프로세스에서 직렬화한다."""

    if str(side or "").strip().upper() != "SELL":
        yield
        return
    scope = _scope_key(user_broker_account_id, paper_account_id, symbol)
    lock = _process_lock_for(scope)
    lock.acquire()
    try:
        acquire_exit_sell_scope_lock(
            session,
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
            symbol=symbol,
        )
        yield
    finally:
        lock.release()


def load_held_quantity(
    session: Session,
    *,
    symbol: str,
    exchange_code: str,
    user_broker_account_id: int | None,
    paper_account_id: int | None,
    environment: str,
) -> Decimal:
    """해당 계좌가 실제로 보유한 수량. 다른 UBA 포지션은 보이지 않는다."""

    env = (environment or "").strip().upper()
    sym = str(symbol or "").strip().upper()
    exchange = str(exchange_code or "").strip().upper()
    if not sym:
        return ZERO

    if paper_account_id is not None and env not in _LIVE_ENVIRONMENTS:
        from stock_platform.trading.account_models import PaperPosition

        rows = list(
            session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == int(paper_account_id),
                    PaperPosition.quantity > ZERO,
                )
            )
        )
        held = ZERO
        for row in rows:
            if _symbol_matches(row.symbol, sym) and _exchange_matches(
                getattr(row, "exchange_code", ""), exchange
            ):
                held += _as_qty(row.quantity)
        return held

    if user_broker_account_id is None:
        return ZERO

    from stock_platform.broker.account_repository import (
        BrokerAccountSnapshotRepository,
    )

    _account, positions = BrokerAccountSnapshotRepository(
        session
    ).get_active_by_uba(int(user_broker_account_id))
    held = ZERO
    for item in positions:
        if not _symbol_matches(item.symbol, sym):
            continue
        if not _exchange_matches(getattr(item, "exchange_code", ""), exchange):
            continue
        held += _as_qty(item.quantity)
    return held


def load_pending_sell_quantity(
    session: Session,
    *,
    symbol: str,
    user_broker_account_id: int | None,
    paper_account_id: int | None,
    broker_code: str | None = None,
) -> Decimal:
    """동일 계좌·종목의 outstanding SELL remaining 합 (서버 DB SoT)."""

    sym = str(symbol or "").strip().upper()
    if not sym:
        return ZERO

    stmt = select(TradingOrderEntity).where(
        TradingOrderEntity.symbol == sym,
        TradingOrderEntity.side_code == "SELL",
    )
    if user_broker_account_id is not None:
        stmt = stmt.where(
            TradingOrderEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    elif paper_account_id is not None:
        stmt = stmt.where(
            TradingOrderEntity.account_id == int(paper_account_id)
        )
    else:
        return ZERO

    broker = str(broker_code or "").strip().upper()
    if broker:
        stmt = stmt.where(TradingOrderEntity.broker_code == broker)

    pending = ZERO
    for row in session.scalars(stmt):
        outbox = _related_outbox(session, row)
        if not is_order_outstanding_for_sell(row, outbox):
            continue
        remaining = _remaining_sell_qty(row)
        if remaining > ZERO:
            pending += remaining
    return pending


def classify_risk_reducing_exit(
    session: Session,
    *,
    side: str,
    symbol: str,
    exchange_code: str,
    quantity: Decimal,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
    environment: str = "LIVE",
    broker_code: str | None = None,
) -> ExitClassification:
    """SELL + 동일 UBA/Paper 보유 + 수량 ≤ sellable 이면 EXIT.

    BUY는 EXIT가 아니다 (reason_code=None).
    클라이언트 플래그는 인자로 받지 않는다.
    """

    side_u = str(side or "").strip().upper()
    empty = ExitClassification(
        is_risk_reducing_exit=False,
        reason_code=None,
        held_quantity=ZERO,
        pending_sell_quantity=ZERO,
        sellable_quantity=ZERO,
        side=side_u,
    )
    if side_u != "SELL":
        return empty

    try:
        qty = Decimal(str(quantity))
    except Exception:  # noqa: BLE001
        qty = ZERO
    if qty <= ZERO:
        return ExitClassification(
            is_risk_reducing_exit=False,
            reason_code=REASON_INVALID_ORDER_QUANTITY,
            held_quantity=ZERO,
            pending_sell_quantity=ZERO,
            sellable_quantity=ZERO,
            side=side_u,
        )

    acquire_exit_sell_scope_lock(
        session,
        user_broker_account_id=user_broker_account_id,
        paper_account_id=paper_account_id,
        symbol=symbol,
    )

    held = load_held_quantity(
        session,
        symbol=symbol,
        exchange_code=exchange_code,
        user_broker_account_id=user_broker_account_id,
        paper_account_id=paper_account_id,
        environment=environment,
    )
    pending = load_pending_sell_quantity(
        session,
        symbol=symbol,
        user_broker_account_id=user_broker_account_id,
        paper_account_id=paper_account_id,
        broker_code=broker_code,
    )
    sellable = held - pending
    if sellable < ZERO:
        sellable = ZERO

    if held <= ZERO:
        return ExitClassification(
            is_risk_reducing_exit=False,
            reason_code=REASON_NO_POSITION_TO_SELL,
            held_quantity=ZERO,
            pending_sell_quantity=pending,
            sellable_quantity=ZERO,
            side=side_u,
        )
    if qty > sellable:
        return ExitClassification(
            is_risk_reducing_exit=False,
            reason_code=REASON_SELL_QUANTITY,
            held_quantity=held,
            pending_sell_quantity=pending,
            sellable_quantity=sellable,
            side=side_u,
        )
    return ExitClassification(
        is_risk_reducing_exit=True,
        reason_code=None,
        held_quantity=held,
        pending_sell_quantity=pending,
        sellable_quantity=sellable,
        side=side_u,
    )
