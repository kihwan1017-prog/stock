"""STEP 8-5-9 — Scope Signal → 기존 Signal Bus / 가드."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)
from stock_platform.realtime.strategy_signal import StrategySignal


logger = structlog.get_logger(__name__)

# fingerprint 단기 중복 차단 (프로세스 메모리)
_RECENT_FINGERPRINTS: dict[str, datetime] = {}
_MAX_FINGERPRINTS = 5000


def strategy_signal_to_realtime(signal: StrategySignal) -> RealtimeSignal:
    action = RealtimeSignalAction.HOLD
    if signal.signal_type == "BUY":
        action = RealtimeSignalAction.BUY
    elif signal.signal_type in {"SELL", "EXIT"}:
        action = RealtimeSignalAction.SELL

    short = signal.metadata.get("short_average")
    long = signal.metadata.get("long_average")
    exchange = (
        signal.metadata.get("exchange_code")
        or signal.broker_code
    )
    return RealtimeSignal(
        exchange_code=str(exchange).upper(),
        symbol=signal.symbol,
        action=action,
        signal_price=signal.reference_price,
        short_average=Decimal(short) if short else None,
        long_average=Decimal(long) if long else None,
        change_rate=None,
        reason_code=signal.reason_code,
        generated_at=signal.generated_at,
        signal_id=signal.signal_id,
        fingerprint=signal.fingerprint,
        scope_key=signal.scope_key,
        user_id=signal.user_id,
        account_kind=signal.account_kind,
        account_id=signal.account_id,
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        broker_code=signal.broker_code,
        market_type=signal.market_type,
    )


def _fingerprint_seen(fingerprint: str) -> bool:
    now = datetime.now(timezone.utc)
    # 만료 정리
    expired = [
        k
        for k, ts in _RECENT_FINGERPRINTS.items()
        if (now - ts).total_seconds() > 300
    ]
    for k in expired:
        _RECENT_FINGERPRINTS.pop(k, None)
    if fingerprint in _RECENT_FINGERPRINTS:
        return True
    if len(_RECENT_FINGERPRINTS) >= _MAX_FINGERPRINTS:
        _RECENT_FINGERPRINTS.clear()
    _RECENT_FINGERPRINTS[fingerprint] = now
    return False


async def publish_scoped_signal(signal: StrategySignal) -> dict[str, Any]:
    """가드 후 Signal Bus publish. Scope 없는 신호는 차단."""

    if not (signal.scope_key or "").strip():
        logger.warning(
            "realtime_scope_less_signal_blocked",
            symbol=signal.symbol,
        )
        return {"published": False, "reason": "SCOPE_REQUIRED"}

    if _fingerprint_seen(signal.fingerprint):
        logger.info(
            "realtime_duplicate_signal_blocked",
            scope_key=signal.scope_key[:40],
            fingerprint=signal.fingerprint,
        )
        return {"published": False, "reason": "DUPLICATE_FINGERPRINT"}

    # Recovery / Calendar / Rate Limit 가드
    if not _guards_allow(signal):
        return {"published": False, "reason": "GUARD_BLOCKED"}

    from stock_platform.realtime.runtime import realtime_signal_bus

    rt = strategy_signal_to_realtime(signal)
    await realtime_signal_bus.publish(rt)
    return {
        "published": True,
        "signal_id": signal.signal_id,
        "scope_key": signal.scope_key,
    }


def _guards_allow(signal: StrategySignal) -> bool:
    """계좌 Pause / Kill / Calendar / Upbit cooldown 간단 확인."""

    try:
        from stock_platform.database.session import get_session_factory
        from stock_platform.broker.recovery_lock import (
            RecoveryAccountLockService,
        )

        session = get_session_factory()()
        try:
            lock = RecoveryAccountLockService(session)
            paused = False
            if signal.account_kind == "PAPER":
                paused = lock.is_trading_paused(
                    paper_account_id=signal.account_id,
                    broker_code=signal.broker_code,
                )
            else:
                paused = lock.is_trading_paused(
                    user_broker_account_id=signal.account_id,
                    broker_code=signal.broker_code,
                )
            if paused:
                return False
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        pass

    # KRX Calendar — STOCK LIVE만 Fail Closed
    if (
        signal.market_type.upper() in {"STOCK", "KRX", "KOSPI", "KOSDAQ"}
        and signal.broker_code.upper() == "KIWOOM"
    ):
        try:
            from stock_platform.operation.calendar_service import (
                TradingCalendarService,
            )
            from stock_platform.database.session import get_session_factory

            session = get_session_factory()()
            try:
                from datetime import date

                svc = TradingCalendarService(session)
                decision = svc.evaluate(
                    exchange_code="KRX",
                    calendar_date=date.today(),
                )
                if not getattr(decision, "live_allowed", True):
                    return False
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            # Calendar 장애 시 LIVE 신호 차단(보수적)
            return False

    # Upbit Rate Limit — UBA cooldown/418
    if signal.broker_code.upper() == "UPBIT" and signal.account_kind != "PAPER":
        try:
            from stock_platform.broker.upbit.rate_limit_coordinator import (
                get_upbit_rate_limit_coordinator,
            )

            ok, reason, _ = get_upbit_rate_limit_coordinator().check_allowed(
                user_broker_account_id=signal.account_id,
                endpoint_group="order",
            )
            if not ok:
                return False
            _ = reason
        except Exception:  # noqa: BLE001
            pass

    return True


def reset_signal_dedup_for_tests() -> None:
    _RECENT_FINGERPRINTS.clear()
