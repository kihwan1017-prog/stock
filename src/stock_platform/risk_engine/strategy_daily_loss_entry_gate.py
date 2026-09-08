# -*- coding: utf-8 -*-
"""Strategy-owned daily-loss entry gate helpers (canonical P1/P2/P3 reuse).

AUTO BUY는 numeric strategy_id + StrategyOwnedRiskService 만 사용한다.
account_daily_loss TELEMETRY 와 effective policy limit 혼합 금지.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
    parse_strategy_id,
)

KST = ZoneInfo("Asia/Seoul")
ZERO = Decimal("0")

# Telegram: (uba_id, trading_date_iso, reason) → 최초 1회만
_TELEGRAM_EMITTED: set[tuple[int, str, str]] = set()
_TELEGRAM_LOCK = Lock()


def trading_date_kst(now: datetime | None = None) -> date:
    """KST trading-day boundary."""
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).date()


def resolve_canonical_strategy_id(
    *,
    strategy_id: Any = None,
    metadata: dict[str, Any] | None = None,
    strategy_code: Any = None,
) -> int | None:
    """숫자 strategy identity만 허용. reason/label 문자열은 무시."""

    sid = parse_strategy_id(strategy_id)
    if sid is not None:
        return sid
    if metadata and isinstance(metadata, dict):
        sid = parse_strategy_id(metadata.get("strategy_id"))
        if sid is not None:
            return sid
    # strategy_code 는 identity 가 아님 — 숫자처럼 보이면 실수 혼동 가능하나
    # PORTFOLIO_* 같은 라벨은 절대 id 로 쓰지 않는다.
    _ = strategy_code
    return None


def is_auto_order_source(order_source: str | None) -> bool:
    return str(order_source or "").strip().upper() == "AUTO"


def strategy_owned_daily_loss_hit(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str,
    strategy_id: int,
    deployment_id: int | None,
    limit: Decimal,
) -> tuple[bool, dict[str, Any]]:
    """Canonical strategy-owned PnL — StrategyOwnedRiskService 재사용."""

    if limit <= ZERO:
        return False, {"mode": "NO_LIMIT", "source": "STRATEGY_OWNED"}
    hit, detail = StrategyOwnedRiskService(session).strategy_daily_loss_breached(
        user_broker_account_id=int(user_broker_account_id),
        broker_code=str(broker_code or "").upper(),
        strategy_id=int(strategy_id),
        deployment_id=deployment_id,
        limit=Decimal(str(limit)),
    )
    out = {**detail, "mode": "STRATEGY_OWNED", "source": "STRATEGY_OWNED"}
    return bool(hit), out


def should_suppress_auto_buy_for_daily_loss(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str,
    strategy_id: int | None,
    deployment_id: int | None,
    limit: Decimal,
) -> tuple[bool, dict[str, Any]]:
    """Upstream BUY suppress — hit=true 일 때만. SELL 경로에서 호출 금지."""

    if strategy_id is None:
        return True, {
            "mode": "STRATEGY_IDENTITY_INVALID",
            "suppress": True,
            "reason_code": "STRATEGY_IDENTITY_INVALID",
        }
    hit, detail = strategy_owned_daily_loss_hit(
        session,
        user_broker_account_id=user_broker_account_id,
        broker_code=broker_code,
        strategy_id=int(strategy_id),
        deployment_id=deployment_id,
        limit=limit,
    )
    if hit:
        return True, {
            **detail,
            "suppress": True,
            "reason_code": "DAILY_LOSS_LIMIT_REACHED",
        }
    return False, {**detail, "suppress": False}


def should_emit_daily_loss_telegram(
    *,
    user_broker_account_id: int,
    reason_code: str = "DAILY_LOSS_LIMIT_REACHED",
    trading_day: date | None = None,
) -> bool:
    """동일 UBA·KST day·reason 은 최초 1회만 Telegram."""

    day = trading_day or trading_date_kst()
    key = (int(user_broker_account_id), day.isoformat(), str(reason_code))
    with _TELEGRAM_LOCK:
        if key in _TELEGRAM_EMITTED:
            return False
        _TELEGRAM_EMITTED.add(key)
        return True


def reset_daily_loss_telegram_dedupe_for_tests() -> None:
    """테스트 전용 상태 초기화."""

    with _TELEGRAM_LOCK:
        _TELEGRAM_EMITTED.clear()
