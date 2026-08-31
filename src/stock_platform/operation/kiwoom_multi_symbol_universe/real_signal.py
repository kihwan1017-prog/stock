"""REAL multi-symbol signal dispatch — 기존 scoped_signal_pipeline 재사용."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    SOURCE_MULTI_SYMBOL_V1,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ma_eval import (
    build_signal_fingerprint,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.mode import (
    is_kiwoom_multi_symbol_real_enabled,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.kst_date import today_kst

logger = structlog.get_logger(__name__)

# refresh 직후 legacy ma_evaluator BUY defer + runtime consumer union 용
_ROSTER_CACHE: dict[int, tuple[float, set[str]]] = {}
_OWNED_CACHE: dict[int, tuple[float, set[str]]] = {}
_CACHE_TTL_SECONDS = 600.0


def update_multi_symbol_runtime_cache(
    *,
    user_broker_account_id: int,
    monitor_symbols: list[str],
    owned_symbols: set[str],
) -> None:
    """refresh 후 monitor/owned roster 캐시 — ma_evaluator·runtime_bridge READ."""

    now = time.monotonic()
    uba_id = int(user_broker_account_id)
    _ROSTER_CACHE[uba_id] = (
        now,
        {str(s).upper() for s in monitor_symbols if s},
    )
    _OWNED_CACHE[uba_id] = (now, {str(s).upper() for s in owned_symbols if s})


def _cached_set(cache: dict[int, tuple[float, set[str]]], uba_id: int) -> set[str]:
    row = cache.get(int(uba_id))
    if row is None:
        return set()
    ts, symbols = row
    if (time.monotonic() - ts) > _CACHE_TTL_SECONDS:
        return set()
    return set(symbols)


def get_cached_monitor_roster(user_broker_account_id: int) -> set[str]:
    return _cached_set(_ROSTER_CACHE, int(user_broker_account_id))


def get_cached_owned_symbols(user_broker_account_id: int) -> set[str]:
    return _cached_set(_OWNED_CACHE, int(user_broker_account_id))


def multi_symbol_real_defers_legacy_ma_buy(
    *,
    broker_code: str,
    uba_id: int,
    symbol: str,
) -> bool:
    """REAL mode + monitor roster symbol → legacy ma_evaluator BUY defer."""

    if str(broker_code or "").upper() != "KIWOOM":
        return False
    if not is_kiwoom_multi_symbol_real_enabled():
        return False
    return str(symbol or "").upper() in get_cached_monitor_roster(int(uba_id))


def extend_kiwoom_consumer_symbols(
    base_symbols: list[str],
    *,
    user_broker_account_id: int | None,
) -> list[str]:
    """REAL mode: monitor roster + strategy-owned position union (exit feed 유지)."""

    if user_broker_account_id is None or not is_kiwoom_multi_symbol_real_enabled():
        return base_symbols
    uba_id = int(user_broker_account_id)
    merged = {
        str(s).strip().upper() for s in base_symbols if str(s or "").strip()
    }
    merged.update(get_cached_monitor_roster(uba_id))
    merged.update(get_cached_owned_symbols(uba_id))
    return sorted(merged)


def resolve_kiwoom_multi_symbol_scope(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any] | None:
    """Strategy 17579 scope — 기존 runtime scope_key 재사용."""

    from stock_platform.strategy_deployment.definition_entities import (
        AccountStrategyLinkEntity,
    )
    from stock_platform.strategy_deployment.entities import (
        StrategyDeploymentEntity,
    )
    from stock_platform.strategy_deployment.runtime_models import (
        build_runtime_scope_key,
    )
    from stock_platform.trading.account_models import UserBrokerAccount

    uba_id = int(user_broker_account_id)
    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None:
        return None
    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id == uba_id,
            AccountStrategyLinkEntity.is_active.is_(True),
        ).limit(1)
    )
    if link is None:
        return None
    strategy_id = int(link.strategy_id)
    dep = session.scalar(
        select(StrategyDeploymentEntity).where(
            StrategyDeploymentEntity.strategy_id == strategy_id,
            StrategyDeploymentEntity.status_code == "ACTIVE",
        ).limit(1)
    )
    if dep is None:
        return None
    strategy_version = str(dep.strategy_version or "1")
    scope_key = build_runtime_scope_key(
        user_id=int(uba.user_id),
        account_id=uba_id,
        user_broker_account_id=uba_id,
        strategy_id=strategy_id,
        strategy_code=str(dep.strategy_code or ""),
        market_code=str(dep.market_code or "KRX"),
        market_type=str(dep.market_type or "STOCK"),
        strategy_version=strategy_version,
        broker_code="KIWOOM",
    )
    return {
        "user_id": int(uba.user_id),
        "user_broker_account_id": uba_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "scope_key": scope_key,
        "broker_code": "KIWOOM",
        "market_type": str(dep.market_type or "STOCK"),
    }


def build_multi_symbol_real_strategy_signal(
    *,
    scope_ctx: dict[str, Any],
    symbol: str,
    ma_eval: Any,
    price: Decimal | None,
    observed_at: datetime,
    refresh_batch_id: str,
    rank: int,
) -> Any:
    from stock_platform.realtime.strategy_signal import StrategySignal

    cross_day = today_kst(observed_at)
    gc_fp = build_signal_fingerprint(symbol=symbol, cross_day=cross_day)
    ref_price = price or ma_eval.sma5 or Decimal("0")
    return StrategySignal(
        signal_id=StrategySignal.build_id(
            scope_key=str(scope_ctx["scope_key"]),
            symbol=symbol,
        ),
        fingerprint=StrategySignal.build_fingerprint(
            scope_key=str(scope_ctx["scope_key"]),
            symbol=symbol.upper(),
            signal_type="BUY",
            reason_code="MA_GOLDEN_CROSS",
            event_time=observed_at,
            opportunity_id=f"multi_symbol:{refresh_batch_id}:{symbol.upper()}",
        ),
        scope_key=str(scope_ctx["scope_key"]),
        user_id=int(scope_ctx["user_id"]),
        account_kind="USER_BROKER",
        account_id=int(scope_ctx["user_broker_account_id"]),
        strategy_id=int(scope_ctx["strategy_id"]),
        strategy_version=str(scope_ctx["strategy_version"]),
        broker_code="KIWOOM",
        market_type=str(scope_ctx.get("market_type") or "STOCK"),
        symbol=symbol.upper(),
        signal_type="BUY",
        generated_at=datetime.now(timezone.utc),
        event_time=observed_at,
        reference_price=ref_price,
        reason_code="MA_GOLDEN_CROSS",
        metadata={
            "source_code": SOURCE_MULTI_SYMBOL_V1,
            "signal_channel": "REAL",
            "multi_symbol_refresh_batch_id": refresh_batch_id,
            "multi_symbol_rank": rank,
            "multi_symbol_gc_fingerprint": gc_fp,
            "short_average": str(ma_eval.sma5) if ma_eval.sma5 is not None else None,
            "long_average": str(ma_eval.sma20) if ma_eval.sma20 is not None else None,
            "prev_short_average": (
                str(ma_eval.prev_sma5) if ma_eval.prev_sma5 is not None else None
            ),
            "prev_long_average": (
                str(ma_eval.prev_sma20) if ma_eval.prev_sma20 is not None else None
            ),
            "exchange_code": "KRX",
        },
    )


async def dispatch_multi_symbol_real_signal(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    ma_eval: Any,
    price: Decimal | None,
    observed_at: datetime,
    refresh_batch_id: str,
    rank: int,
    scope_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """기존 publish_scoped_signal → execution_runner canonical path."""

    from stock_platform.operation.kiwoom_multi_symbol_universe.entities import (
        KiwoomMultiSymbolRealSignalEntity,
    )
    from stock_platform.realtime.scoped_signal_pipeline import publish_scoped_signal

    uba_id = int(user_broker_account_id)
    ctx = scope_ctx or resolve_kiwoom_multi_symbol_scope(
        session, user_broker_account_id=uba_id
    )
    if ctx is None:
        return {"ok": False, "reason": "SCOPE_UNRESOLVED"}

    gc_fp = build_signal_fingerprint(
        symbol=symbol, cross_day=today_kst(observed_at)
    )
    existing = session.scalar(
        select(KiwoomMultiSymbolRealSignalEntity).where(
            KiwoomMultiSymbolRealSignalEntity.user_broker_account_id == uba_id,
            KiwoomMultiSymbolRealSignalEntity.signal_fingerprint == gc_fp,
        ).limit(1)
    )
    if existing is not None:
        return {
            "ok": False,
            "reason": "DUPLICATE_REAL_SIGNAL",
            "duplicate_protected": True,
            "real_signal_id": int(existing.real_signal_id),
        }

    signal = build_multi_symbol_real_strategy_signal(
        scope_ctx=ctx,
        symbol=symbol,
        ma_eval=ma_eval,
        price=price,
        observed_at=observed_at,
        refresh_batch_id=refresh_batch_id,
        rank=rank,
    )
    publish_out = await publish_scoped_signal(signal)
    row = KiwoomMultiSymbolRealSignalEntity(
        user_broker_account_id=uba_id,
        strategy_id=int(ctx["strategy_id"]),
        refresh_batch_id=refresh_batch_id,
        rank=int(rank),
        symbol=symbol.upper(),
        signal_fingerprint=gc_fp,
        publish_fingerprint=signal.fingerprint,
        observed_at=observed_at,
        sma5=ma_eval.sma5,
        sma20=ma_eval.sma20,
        prev_sma5=ma_eval.prev_sma5,
        prev_sma20=ma_eval.prev_sma20,
        dispatch_state=(
            "PUBLISHED" if publish_out.get("published") else str(publish_out.get("reason") or "BLOCKED")
        ),
        dispatch_detail_json=dict(publish_out),
        meta_json={
            "signal_id": signal.signal_id,
            "scope_key": signal.scope_key,
            "signal_channel": "REAL",
            "source": SOURCE_MULTI_SYMBOL_V1,
        },
    )
    session.add(row)
    session.flush()
    return {
        "ok": bool(publish_out.get("published")),
        "published": bool(publish_out.get("published")),
        "reason": publish_out.get("reason"),
        "duplicate_protected": publish_out.get("reason") == "DUPLICATE_FINGERPRINT",
        "real_signal_id": int(row.real_signal_id),
        "signal_id": signal.signal_id,
        "executor_dispatch": bool(publish_out.get("published")),
    }
