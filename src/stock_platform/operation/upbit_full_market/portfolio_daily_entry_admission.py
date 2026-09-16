"""UPBIT portfolio 일일 REAL AUTO BUY — atomic final admission.

WAITING_SIGNAL은 quota를 소비하지 않는다.
REAL AUTO BUY persist 직전에 UBA+KST-day 잠금 후 canonical count로 최종 허용한다.

lock:
  - PostgreSQL: pg_advisory_xact_lock (트랜잭션 종료까지)
  - 전 환경: 프로세스 내 threading lock (SQLite/테스트 직렬화 보조)
"""

from __future__ import annotations

import hashlib
import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
)
from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
    count_portfolio_daily_real_entries,
)
from stock_platform.order.daily_risk_order_count import day_start_kst_as_utc

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# legacy alias — UI/로그 호환. canonical은 DAILY_ENTRY_LIMIT_REACHED.
REASON_PORTFOLIO_DAILY_ENTRY_LIMIT = "PORTFOLIO_DAILY_ENTRY_LIMIT"
REASON_DAILY_ENTRY_LIMIT_REACHED = "DAILY_ENTRY_LIMIT_REACHED"

MODE_LIMITED = "LIMITED"
MODE_UNLIMITED = "UNLIMITED"

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def normalize_daily_entry_limit_mode(raw: Any) -> str:
    text = str(raw or MODE_LIMITED).strip().upper()
    if text == MODE_UNLIMITED:
        return MODE_UNLIMITED
    return MODE_LIMITED


def resolve_portfolio_daily_entry_policy(
    session: Session,
    user_broker_account_id: int,
) -> tuple[str, int | None]:
    """(mode, limit). UNLIMITED면 limit=None."""

    from stock_platform.operation.upbit_full_market.entities import (
        UpbitPortfolioPolicyEntity,
    )

    row = session.scalar(
        select(UpbitPortfolioPolicyEntity).where(
            UpbitPortfolioPolicyEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    )
    if row is None:
        return MODE_LIMITED, int(DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT)
    mode = normalize_daily_entry_limit_mode(
        getattr(row, "portfolio_daily_entry_limit_mode", MODE_LIMITED)
    )
    if mode == MODE_UNLIMITED:
        return MODE_UNLIMITED, None
    try:
        return MODE_LIMITED, max(1, int(row.portfolio_daily_entry_limit))
    except (TypeError, ValueError):
        return MODE_LIMITED, int(DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT)


def kst_trading_date(now: datetime | None = None) -> date:
    """Asia/Seoul 달력일."""

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(KST).date()


def _lock_scope_key(uba_id: int, trading_day: date) -> str:
    return f"upbit-daily-entry|{int(uba_id)}|{trading_day.isoformat()}"


def _advisory_lock_key(uba_id: int, trading_day: date) -> int:
    raw = _lock_scope_key(uba_id, trading_day).encode()
    digest = hashlib.blake2b(raw, digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF


def _process_lock(uba_id: int, trading_day: date) -> threading.RLock:
    key = _lock_scope_key(uba_id, trading_day)
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def acquire_portfolio_daily_entry_xact_lock(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
) -> None:
    """PostgreSQL 트랜잭션 advisory lock. 비-PG는 no-op."""

    uba_id = int(user_broker_account_id)
    day = kst_trading_date(now)
    try:
        bind = session.get_bind()
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "")
        if dialect != "postgresql":
            return
        session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"),
            {"k": _advisory_lock_key(uba_id, day)},
        )
    except Exception:  # noqa: BLE001
        return


def resolve_portfolio_daily_entry_limit(
    session: Session,
    user_broker_account_id: int,
) -> int:
    """정책 row의 limit (없으면 DEFAULT).

    UNLIMITED는 int sentinel 대신 resolve_portfolio_daily_entry_policy 사용.
    레거시 int-only 호출부는 비차단용 큰 값을 받되, 신규 경로는 mode를 본다.
    """

    mode, limit = resolve_portfolio_daily_entry_policy(
        session, user_broker_account_id
    )
    if mode == MODE_UNLIMITED or limit is None:
        return 10**9
    return int(limit)


def applies_final_daily_entry_admission(
    *,
    side: str,
    broker_code: str,
    environment: str,
    order_source: str,
    user_broker_account_id: int | None,
    is_risk_reducing: bool = False,
) -> bool:
    """REAL UPBIT AUTO BUY (NEW ENTRY)에만 final admission 적용."""

    if is_risk_reducing:
        return False
    if str(side or "").strip().upper() != "BUY":
        return False
    if str(broker_code or "").strip().upper() != "UPBIT":
        return False
    if str(environment or "").strip().upper() != "LIVE":
        return False
    if str(order_source or "").strip().upper() != "AUTO":
        return False
    if user_broker_account_id is None:
        return False
    return True


def try_final_admit_portfolio_daily_entry(
    session: Session,
    *,
    user_broker_account_id: int,
    daily_limit: int | None = None,
    symbol: str | None = None,
    binding_id: int | None = None,
    candidate_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """잠금 획득 후 canonical count로 1건 허용 여부 판정.

    호출자는 같은 세션/트랜잭션에서 즉시 order를 생성해야 한다.
    별도 reservation row는 두지 않는다 — order INSERT가 admission 소비.
    """

    uba_id = int(user_broker_account_id)
    now_utc = now or datetime.now(timezone.utc)
    trading_day = kst_trading_date(now_utc)
    mode, resolved_limit = resolve_portfolio_daily_entry_policy(session, uba_id)
    if daily_limit is not None:
        mode = MODE_LIMITED
        resolved_limit = max(1, int(daily_limit))

    if mode == MODE_UNLIMITED or resolved_limit is None:
        count_before = count_portfolio_daily_real_entries(
            session, uba_id, now=now_utc
        )
        day_start = day_start_kst_as_utc(now_utc)
        return {
            "uba_id": uba_id,
            "kst_date": trading_day.isoformat(),
            "day_start_utc": day_start.isoformat(),
            "count_before": count_before,
            "limit": None,
            "mode": MODE_UNLIMITED,
            "symbol": symbol,
            "binding_id": binding_id,
            "candidate_id": candidate_id,
            "timezone": "Asia/Seoul",
            "count_source": "REAL_AUTO_BUY_CONSUMED_OR_RESERVED",
            "allowed": True,
            "reason": None,
            "event": "DAILY_ENTRY_FINAL_ADMISSION_ALLOWED_UNLIMITED",
        }

    limit = max(1, int(resolved_limit))

    acquire_portfolio_daily_entry_xact_lock(
        session, user_broker_account_id=uba_id, now=now_utc
    )
    count_before = count_portfolio_daily_real_entries(
        session, uba_id, now=now_utc
    )
    day_start = day_start_kst_as_utc(now_utc)
    base = {
        "uba_id": uba_id,
        "kst_date": trading_day.isoformat(),
        "day_start_utc": day_start.isoformat(),
        "count_before": count_before,
        "limit": limit,
        "mode": MODE_LIMITED,
        "symbol": symbol,
        "binding_id": binding_id,
        "candidate_id": candidate_id,
        "timezone": "Asia/Seoul",
        "count_source": "REAL_AUTO_BUY_CONSUMED_OR_RESERVED",
    }

    if count_before >= limit:
        logger.info(
            "DAILY_ENTRY_FINAL_ADMISSION_BLOCKED",
            extra={
                "event": "DAILY_ENTRY_FINAL_ADMISSION_BLOCKED",
                **base,
            },
        )
        try:
            from stock_platform.notification.telegram_policy import (
                maybe_emit_upbit_daily_limit_edge,
            )

            maybe_emit_upbit_daily_limit_edge(
                usage={
                    "blocking": True,
                    "entry_count": count_before,
                    "entry_limit": limit,
                },
                uba_id=uba_id,
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            **base,
            "allowed": False,
            "reason": REASON_DAILY_ENTRY_LIMIT_REACHED,
            "reason_legacy": REASON_PORTFOLIO_DAILY_ENTRY_LIMIT,
            "event": "DAILY_ENTRY_FINAL_ADMISSION_BLOCKED",
        }

    logger.info(
        "DAILY_ENTRY_FINAL_ADMISSION_ALLOWED",
        extra={
            "event": "DAILY_ENTRY_FINAL_ADMISSION_ALLOWED",
            **base,
        },
    )
    try:
        from stock_platform.notification.telegram_policy import (
            maybe_emit_upbit_daily_limit_edge,
        )

        maybe_emit_upbit_daily_limit_edge(
            usage={
                "blocking": False,
                "entry_count": count_before,
                "entry_limit": limit,
            },
            uba_id=uba_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return {
        **base,
        "allowed": True,
        "reason": None,
        "event": "DAILY_ENTRY_FINAL_ADMISSION_ALLOWED",
    }


@contextmanager
def portfolio_daily_entry_buy_fence(
    session: Session,
    *,
    side: str,
    broker_code: str,
    environment: str,
    order_source: str,
    user_broker_account_id: int | None,
    is_risk_reducing: bool = False,
    now: datetime | None = None,
) -> Iterator[Callable[..., dict[str, Any]]]:
    """BUY persist 구간을 UBA+KST-day 단위로 직렬화.

    yield: admit(**kwargs) → try_final_admit_... 결과
    applies=False면 admit은 항상 allowed skipped.
    """

    applies = applies_final_daily_entry_admission(
        side=side,
        broker_code=broker_code,
        environment=environment,
        order_source=order_source,
        user_broker_account_id=user_broker_account_id,
        is_risk_reducing=is_risk_reducing,
    )
    if not applies or user_broker_account_id is None:

        def _skip_admit(**_kwargs: Any) -> dict[str, Any]:
            return {
                "allowed": True,
                "skipped": True,
                "reason": None,
                "event": "DAILY_ENTRY_FINAL_ADMISSION_SKIPPED",
            }

        yield _skip_admit
        return

    uba_id = int(user_broker_account_id)
    trading_day = kst_trading_date(now)
    lock = _process_lock(uba_id, trading_day)
    with lock:

        def _admit(**kwargs: Any) -> dict[str, Any]:
            return try_final_admit_portfolio_daily_entry(
                session,
                user_broker_account_id=uba_id,
                now=now,
                **kwargs,
            )

        yield _admit
