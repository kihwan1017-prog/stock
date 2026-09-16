"""LIVE Execution Runner 범위 키와 Signal 라우팅.

전역 LIVE UBA 1개 바인딩을 쓰지 않는다.
키는 (user_broker_account_id, broker_code) 이다.
"""

from __future__ import annotations

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
)


SUPPORTED_LIVE_BROKERS = frozenset({"UPBIT", "KIWOOM"})
PAPER_SCOPE_KEY = (0, "PAPER")


def runner_scope_key(
    user_broker_account_id: int,
    broker_code: str,
) -> tuple[int, str]:
    """Runner 사전 키. broker는 대문자."""

    return (
        int(user_broker_account_id),
        str(broker_code or "").strip().upper(),
    )


def resolve_signal_broker_code(signal: RealtimeSignal) -> str:
    """Scope/신호의 broker_code 우선, 없으면 거래소 휴리스틱."""

    raw = getattr(signal, "broker_code", None)
    if raw:
        return str(raw).strip().upper()

    exchange = str(signal.exchange_code or "").strip().upper()
    if exchange in {"UPBIT", "CRYPTO", "BINANCE"}:
        return "UPBIT"
    return "KIWOOM"


def resolve_signal_user_broker_account_id(
    signal: RealtimeSignal,
) -> int | None:
    """USER_BROKER 신호의 UBA. 명시 필드 우선, 없으면 account_id."""

    explicit = getattr(signal, "user_broker_account_id", None)
    if explicit is not None:
        try:
            value = int(explicit)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    account_kind = str(getattr(signal, "account_kind", "") or "").upper()
    if account_kind != "USER_BROKER":
        return None
    account_id = getattr(signal, "account_id", None)
    if account_id is None:
        return None
    try:
        value = int(account_id)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def signal_matches_execution_scope(
    signal: RealtimeSignal,
    config: RealtimeExecutionConfig,
) -> bool:
    """Runner는 자기 (broker, UBA) Signal만 소비한다."""

    mode = config.mode
    cfg_uba = getattr(config, "user_broker_account_id", None)
    cfg_broker = str(getattr(config, "broker_code", "") or "").upper()

    if mode == RealtimeExecutionMode.LIVE and cfg_uba:
        signal_uba = resolve_signal_user_broker_account_id(signal)
        if signal_uba is None or int(signal_uba) != int(cfg_uba):
            return False
        signal_broker = resolve_signal_broker_code(signal)
        if cfg_broker and signal_broker != cfg_broker:
            return False
        return True

    account_kind = str(getattr(signal, "account_kind", "") or "").upper()
    if account_kind == "USER_BROKER":
        # PAPER/MOCK Runner는 LIVE UBA 신호를 주문화하지 않는다.
        return False
    if getattr(signal, "scope_key", None) and getattr(signal, "account_id", None):
        if int(signal.account_id) != int(config.account_id):
            return False
    return True
