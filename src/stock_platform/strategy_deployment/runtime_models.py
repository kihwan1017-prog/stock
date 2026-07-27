"""STEP 8-5-5 — Runtime 모델 (Scope Key 포함)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)


def build_runtime_scope_key(
    *,
    user_id: int | None,
    account_id: int | None,
    user_broker_account_id: int | None,
    strategy_id: int | None,
    strategy_code: str,
    market_code: str,
    market_type: str | None = None,
    strategy_version: str | None = None,
    broker_code: str | None = None,
) -> str:
    """레거시 호출 호환 — 가능하면 StrategyRuntimeScope.scope_key 사용."""

    if (
        user_id is not None
        and strategy_id is not None
        and (
            account_id is not None
            or user_broker_account_id is not None
        )
    ):
        kind = (
            AccountKind.USER_BROKER
            if user_broker_account_id is not None
            else AccountKind.PAPER
        )
        acct = (
            int(user_broker_account_id)
            if user_broker_account_id is not None
            else int(account_id)  # type: ignore[arg-type]
        )
        broker = (
            (broker_code or "").upper()
            or ("PAPER" if kind == AccountKind.PAPER else "UNKNOWN")
        )
        scope = StrategyRuntimeScope(
            user_id=int(user_id),
            account_kind=kind,
            account_id=acct,
            strategy_id=int(strategy_id),
            strategy_version=(
                strategy_version or f"code:{strategy_code}"
            ),
            market_type=(market_type or "STOCK").upper(),
            broker_code=broker,
            strategy_code=strategy_code,
            market_code=market_code,
        )
        return scope.scope_key

    # 불완전 메타 — 명시적 실패용 키 (전역 fallback 금지)
    account_part = (
        f"uba:{user_broker_account_id}"
        if user_broker_account_id is not None
        else (
            f"paper:{account_id}"
            if account_id is not None
            else "acct:none"
        )
    )
    return "|".join(
        [
            f"user:{user_id if user_id is not None else 'missing'}",
            account_part,
            f"sid:{strategy_id if strategy_id is not None else 'none'}",
            f"code:{strategy_code}",
            f"mkt:{market_code}",
            f"type:{market_type or 'STOCK'}",
            "incomplete:1",
        ]
    )


@dataclass(frozen=True, slots=True)
class LoadedStrategyRuntime:
    deployment_id: int
    strategy_code: str
    market_code: str
    symbol: str | None
    parameter_payload: dict[str, Any]
    loaded_at: datetime
    user_id: int | None = None
    account_id: int | None = None
    user_broker_account_id: int | None = None
    strategy_id: int | None = None
    strategy_version: str | None = None
    market_type: str | None = None
    scope_key: str | None = None
    broker_code: str | None = None
    account_kind: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyRuntimeReloadResult:
    changed: bool
    previous_deployment_id: int | None
    current_deployment_id: int | None
    strategy_code: str | None
    message: str
    reloaded_at: datetime
    scope_key: str | None = None
