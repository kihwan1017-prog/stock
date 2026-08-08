"""자동매매 Signal → Order idempotency / provenance 헬퍼."""

from __future__ import annotations

from typing import Any


def build_autotrading_idempotency_key(
    signal: Any,
    *,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
) -> str:
    """동일 signal 재발행 시 Outbox/Order 중복 생성 방지.

    우선순위:
    1) strategy:{id}:signal:{fingerprint}:uba:{uba} (또는 paper)
    2) RT:{exchange}:{symbol}:{action}:{generated_at} (레거시 fallback)
    """

    fingerprint = str(
        getattr(signal, "fingerprint", None)
        or getattr(signal, "signal_id", None)
        or ""
    ).strip()
    strategy_id = getattr(signal, "strategy_id", None)
    if fingerprint:
        sid = strategy_id if strategy_id is not None else "na"
        if user_broker_account_id is not None:
            return (
                f"strategy:{sid}:signal:{fingerprint}"
                f":uba:{int(user_broker_account_id)}"
            )
        if paper_account_id is not None:
            return (
                f"strategy:{sid}:signal:{fingerprint}"
                f":paper:{int(paper_account_id)}"
            )
        return f"strategy:{sid}:signal:{fingerprint}"

    exchange = str(getattr(signal, "exchange_code", "") or "")
    symbol = str(getattr(signal, "symbol", "") or "")
    action = getattr(signal, "action", None)
    action_value = (
        action.value if hasattr(action, "value") else str(action or "")
    )
    generated = getattr(signal, "generated_at", None)
    generated_s = (
        generated.isoformat() if generated is not None else "unknown"
    )
    return f"RT:{exchange}:{symbol}:{action_value}:{generated_s}"
