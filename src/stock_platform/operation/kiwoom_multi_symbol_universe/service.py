"""KIWOOM multi-symbol universe orchestration — SHADOW + REAL promotion."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    BLOCK_INSUFFICIENT_HISTORY,
    BLOCK_NO_FRESH_GOLDEN_CROSS,
    CROSS_STATE_FRESH_CROSS,
    SIGNAL_STATUS_REAL_DISPATCHED,
    SIGNAL_STATUS_REAL_DUPLICATE_BLOCKED,
    SIGNAL_STATUS_REAL_GUARD_BLOCKED,
    SIGNAL_STATUS_SHADOW_RECORDED,
    SOURCE_MULTI_SYMBOL_V1,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.entities import (
    KiwoomMultiSymbolCrossStateEntity,
    KiwoomMultiSymbolMonitorEntity,
    KiwoomMultiSymbolRefreshRunEntity,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ma_eval import (
    build_signal_fingerprint,
    evaluate_daily_ma_cross,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.mode import (
    is_kiwoom_multi_symbol_real_enabled,
    is_kiwoom_multi_symbol_shadow_observability_enabled,
    resolve_kiwoom_multi_symbol_mode,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ranking import (
    prefilter_and_rank_candidates,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.real_signal import (
    dispatch_multi_symbol_real_signal,
    resolve_kiwoom_multi_symbol_scope,
    update_multi_symbol_runtime_cache,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.universe import (
    load_krx_tradable_universe,
)
from stock_platform.realtime.daily_bar_seed import (
    load_completed_daily_closes,
    today_kst,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    EXCHANGE_KRX,
    MIN_COMPLETED_BARS,
)

logger = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_real_feed_symbols(
    session: Session,
    *,
    user_broker_account_id: int,
) -> list[str]:
    """기존 REAL stack restore SoT — 변경하지 않음."""

    from stock_platform.trading.kiwoom_unattended_stack_restore import (
        _resolve_kiwoom_stack_feed_symbols,
    )
    from stock_platform.strategy_deployment.definition_entities import (
        AccountStrategyLinkEntity,
    )

    uba_id = int(user_broker_account_id)
    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id == uba_id,
            AccountStrategyLinkEntity.is_active.is_(True),
        ).limit(1)
    )
    strategy_id = int(link.strategy_id) if link is not None else None
    return _resolve_kiwoom_stack_feed_symbols(
        session,
        user_broker_account_id=uba_id,
        strategy_id=strategy_id,
        symbols=None,
    )


def union_real_and_shadow_symbols(
    session: Session,
    *,
    user_broker_account_id: int,
    shadow_symbols: list[str],
    extra_owned_symbols: set[str] | None = None,
) -> list[str]:
    """REAL deployment + TOP10 monitor + strategy-owned position union."""

    real = resolve_real_feed_symbols(
        session, user_broker_account_id=user_broker_account_id
    )
    owned = extra_owned_symbols or _strategy_owned_symbols(
        session, uba_id=int(user_broker_account_id)
    )
    merged = sorted(
        {
            str(s).strip().upper()
            for s in (real or []) + (shadow_symbols or []) + list(owned)
            if s
        }
    )
    return merged


async def reconcile_shadow_feed_subscriptions(
    session: Session,
    *,
    user_broker_account_id: int,
    shadow_symbols: list[str],
    extra_owned_symbols: set[str] | None = None,
    actor: str = "SYSTEM_KIWOOM_MULTI_SYMBOL_SHADOW",
) -> dict[str, Any]:
    """REAL feed + shadow TOP10 + owned position union subscribe — physical socket 1개 유지."""

    owned = extra_owned_symbols or _strategy_owned_symbols(
        session, uba_id=int(user_broker_account_id)
    )
    symbols = union_real_and_shadow_symbols(
        session,
        user_broker_account_id=user_broker_account_id,
        shadow_symbols=shadow_symbols,
        extra_owned_symbols=owned,
    )
    if not symbols:
        return {"ok": False, "reason": "NO_SYMBOLS"}

    from stock_platform.trading.kiwoom_feed_recovery import (
        ensure_kiwoom_feed_running,
    )

    feed = await ensure_kiwoom_feed_running(
        session,
        user_broker_account_id=int(user_broker_account_id),
        symbols=symbols,
        actor=actor,
    )
    return {
        "ok": True,
        "symbols": symbols,
        "real_count": len(
            resolve_real_feed_symbols(
                session, user_broker_account_id=user_broker_account_id
            )
        ),
        "shadow_count": len(shadow_symbols),
        "feed": feed,
    }


def _load_cross_state(
    session: Session, *, uba_id: int, symbol: str
) -> KiwoomMultiSymbolCrossStateEntity | None:
    return session.scalar(
        select(KiwoomMultiSymbolCrossStateEntity).where(
            KiwoomMultiSymbolCrossStateEntity.user_broker_account_id == uba_id,
            KiwoomMultiSymbolCrossStateEntity.symbol == symbol.upper(),
        )
    )


def _upsert_cross_state(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    ma_eval: Any,
    now: datetime,
    last_cross_at: datetime | None = None,
    fingerprint: str | None = None,
) -> KiwoomMultiSymbolCrossStateEntity:
    row = _load_cross_state(session, uba_id=uba_id, symbol=symbol)
    if row is None:
        row = KiwoomMultiSymbolCrossStateEntity(
            user_broker_account_id=uba_id,
            symbol=symbol.upper(),
        )
        session.add(row)
    row.sma5 = ma_eval.sma5
    row.sma20 = ma_eval.sma20
    row.prev_sma5 = ma_eval.prev_sma5
    row.prev_sma20 = ma_eval.prev_sma20
    row.cross_state = ma_eval.cross_state
    row.insufficient_history = ma_eval.insufficient_history
    row.last_evaluated_at = now
    if last_cross_at is not None:
        row.last_cross_at = last_cross_at
    if fingerprint:
        row.last_signal_fingerprint = fingerprint
    return row


def _strategy_owned_symbols(session: Session, *, uba_id: int) -> set[str]:
    from stock_platform.risk_engine.strategy_owned_entities import (
        StrategyPositionBindingEntity,
    )

    rows = session.scalars(
        select(StrategyPositionBindingEntity.symbol).where(
            StrategyPositionBindingEntity.user_broker_account_id == uba_id,
            StrategyPositionBindingEntity.broker_code == "KIWOOM",
            StrategyPositionBindingEntity.status.in_(("OPEN", "ACTIVE", "PARTIAL")),
        )
    )
    return {str(s).upper() for s in rows if s}


def _pending_order_symbols(session: Session, *, uba_id: int) -> set[str]:
    from stock_platform.order.entities import TradingOrderEntity

    rows = session.scalars(
        select(TradingOrderEntity.symbol).where(
            TradingOrderEntity.user_broker_account_id == uba_id,
            TradingOrderEntity.broker_code == "KIWOOM",
            TradingOrderEntity.status_code.in_(
                (
                    "PENDING",
                    "SUBMITTING",
                    "SENT",
                    "CREATED",
                    "ACCEPTED",
                    "PARTIALLY_FILLED",
                )
            ),
        )
    )
    return {str(s).upper() for s in rows if s}


def _record_shadow_signal(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    ma_eval: Any,
    price: Decimal | None,
    observed_at: datetime,
) -> dict[str, Any]:
    """기존 kiwoom_entry_signal_shadow 재사용 — executor 미호출."""

    from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.constants import (
        VARIANT_K0,
    )
    from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.service import (
        enroll_golden_cross_observation,
    )

    return enroll_golden_cross_observation(
        session,
        uba_id=uba_id,
        symbol=symbol,
        short_ma=ma_eval.sma5 or Decimal("0"),
        long_ma=ma_eval.sma20 or Decimal("0"),
        prev_short=ma_eval.prev_sma5 or Decimal("0"),
        prev_long=ma_eval.prev_sma20 or Decimal("0"),
        observed_at=observed_at,
        entry_reference_price=price,
        scope_key=f"SHADOW:{SOURCE_MULTI_SYMBOL_V1}",
        source=SOURCE_MULTI_SYMBOL_V1,
        commit=False,
    )


class KiwoomMultiSymbolUniverseService:
    """SHADOW observability + optional REAL executor signal source."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()

    async def refresh(
        self,
        *,
        user_broker_account_id: int,
        actor: str = "SYSTEM_KIWOOM_MULTI_SYMBOL",
        trigger_source: str = "SCHEDULER",
    ) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        started = _utc_now()
        t0 = time.perf_counter()
        batch_id = uuid.uuid4().hex[:32]
        audit_row = KiwoomMultiSymbolRefreshRunEntity(
            user_broker_account_id=uba_id,
            refresh_batch_id=batch_id,
            trigger_source=str(trigger_source or "SCHEDULER").upper(),
            started_at=started,
        )
        self._session.add(audit_row)
        monitor_target = int(
            getattr(self._settings, "kiwoom_multi_symbol_monitor_target", 10) or 10
        )
        min_tv = Decimal(
            str(
                getattr(
                    self._settings, "kiwoom_multi_symbol_min_trade_value", 100_000_000
                )
            )
        )
        mode = resolve_kiwoom_multi_symbol_mode(self._settings)
        real_enabled = mode == "REAL"
        shadow_obs = is_kiwoom_multi_symbol_shadow_observability_enabled(
            self._settings
        ) or bool(getattr(self._settings, "kiwoom_multi_symbol_shadow_enabled", False))

        universe = load_krx_tradable_universe(self._session)
        t_rank = time.perf_counter()
        ranked, stats = prefilter_and_rank_candidates(
            self._session,
            universe,
            monitor_target=monitor_target,
            min_trade_value=min_tv,
        )
        timing = dict(stats.get("timing") or {})
        timing["ranking_ms"] = round((time.perf_counter() - t_rank) * 1000, 2)
        symbols = [c.symbol for c in ranked]
        now = _utc_now()

        # 이전 roster — subscription churn 방지 비교
        prev_rows = list(
            self._session.scalars(
                select(KiwoomMultiSymbolMonitorEntity.symbol)
                .where(
                    KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id,
                )
                .distinct()
            )
        )
        prev_set = {str(s).upper() for s in prev_rows}
        new_set = set(symbols)
        roster_changed = prev_set != new_set

        owned = _strategy_owned_symbols(self._session, uba_id=uba_id)
        pending = _pending_order_symbols(self._session, uba_id=uba_id)

        fresh_cross_count = 0
        shadow_signal_count = 0
        real_signal_count = 0
        duplicate_real_blocked = 0
        fake_cross_prevented = 0
        scope_ctx = (
            resolve_kiwoom_multi_symbol_scope(self._session, user_broker_account_id=uba_id)
            if real_enabled
            else None
        )

        # roster 교체
        self._session.execute(
            delete(KiwoomMultiSymbolMonitorEntity).where(
                KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id
            )
        )

        for cand in ranked:
            block_reason = BLOCK_NO_FRESH_GOLDEN_CROSS
            signal_status = "NONE"
            if cand.insufficient_history:
                block_reason = BLOCK_INSUFFICIENT_HISTORY
            elif cand.symbol in owned:
                block_reason = "ALREADY_POSITIONED"
            elif cand.symbol in pending:
                block_reason = "PENDING_ORDER"
            elif cand.cross_state == CROSS_STATE_FRESH_CROSS:
                block_reason = None
                signal_status = "REAL_CANDIDATE" if real_enabled else "SHADOW_CANDIDATE"

            prev_row = _load_cross_state(
                self._session, uba_id=uba_id, symbol=cand.symbol
            )
            closes_tuples = load_completed_daily_closes(
                self._session,
                exchange_code=EXCHANGE_KRX,
                symbol=cand.symbol,
                required=MIN_COMPLETED_BARS,
                today=today_kst(),
            )
            closes = [c for _, c in closes_tuples]
            if cand.price is not None:
                closes = closes + [cand.price]

            ma_eval = evaluate_daily_ma_cross(
                symbol=cand.symbol,
                closes=closes,
            )

            fingerprint = None
            last_cross_at = prev_row.last_cross_at if prev_row else None
            if ma_eval.is_fresh_golden_cross and not ma_eval.insufficient_history:
                fp = build_signal_fingerprint(
                    symbol=cand.symbol, cross_day=today_kst(now)
                )
                if prev_row and prev_row.last_signal_fingerprint == fp:
                    fake_cross_prevented += 1
                else:
                    fresh_cross_count += 1
                    last_cross_at = now
                    fingerprint = fp
                    # shadow observability — REAL mode에서도 lineage 유지
                    if shadow_obs or not real_enabled:
                        sig = _record_shadow_signal(
                            self._session,
                            uba_id=uba_id,
                            symbol=cand.symbol,
                            ma_eval=ma_eval,
                            price=cand.price,
                            observed_at=now,
                        )
                        if sig.get("ok") or sig.get("created"):
                            shadow_signal_count += 1
                            if not real_enabled:
                                signal_status = SIGNAL_STATUS_SHADOW_RECORDED
                    if (
                        real_enabled
                        and block_reason is None
                        and cand.symbol not in owned
                        and cand.symbol not in pending
                    ):
                        real_out = await dispatch_multi_symbol_real_signal(
                            self._session,
                            user_broker_account_id=uba_id,
                            symbol=cand.symbol,
                            ma_eval=ma_eval,
                            price=cand.price,
                            observed_at=now,
                            refresh_batch_id=batch_id,
                            rank=cand.rank,
                            scope_ctx=scope_ctx,
                        )
                        if real_out.get("reason") == "DUPLICATE_REAL_SIGNAL":
                            duplicate_real_blocked += 1
                            signal_status = SIGNAL_STATUS_REAL_DUPLICATE_BLOCKED
                        elif real_out.get("published"):
                            real_signal_count += 1
                            signal_status = SIGNAL_STATUS_REAL_DISPATCHED
                        elif real_out.get("ok"):
                            real_signal_count += 1
                            signal_status = SIGNAL_STATUS_REAL_DISPATCHED
                        else:
                            signal_status = SIGNAL_STATUS_REAL_GUARD_BLOCKED
                    elif real_enabled and signal_status not in (
                        SIGNAL_STATUS_REAL_DISPATCHED,
                        SIGNAL_STATUS_REAL_DUPLICATE_BLOCKED,
                    ):
                        if cand.symbol in owned:
                            signal_status = "REAL_BLOCKED_ALREADY_POSITIONED"
                        elif cand.symbol in pending:
                            signal_status = "REAL_BLOCKED_PENDING_ORDER"

            _upsert_cross_state(
                self._session,
                uba_id=uba_id,
                symbol=cand.symbol,
                ma_eval=ma_eval,
                now=now,
                last_cross_at=last_cross_at,
                fingerprint=fingerprint,
            )

            self._session.add(
                KiwoomMultiSymbolMonitorEntity(
                    user_broker_account_id=uba_id,
                    refresh_batch_id=batch_id,
                    rank=cand.rank,
                    symbol=cand.symbol,
                    name=cand.name,
                    price=cand.price,
                    volume=cand.volume,
                    trading_value=cand.trading_value,
                    change_pct=cand.change_pct,
                    selection_reason=cand.selection_reason,
                    sma5=ma_eval.sma5,
                    sma20=ma_eval.sma20,
                    cross_state=ma_eval.cross_state,
                    block_reason=block_reason,
                    signal_status=signal_status,
                    selected_at=now,
                    meta_json={
                        "mode": mode,
                        "real_enabled": real_enabled,
                        "shadow_observability": shadow_obs,
                    },
                )
            )

        update_multi_symbol_runtime_cache(
            user_broker_account_id=uba_id,
            monitor_symbols=symbols,
            owned_symbols=owned,
        )

        feed_result: dict[str, Any] | None = None
        if symbols or owned:
            feed_result = await reconcile_shadow_feed_subscriptions(
                self._session,
                user_broker_account_id=uba_id,
                shadow_symbols=symbols,
                extra_owned_symbols=owned,
                actor=actor,
            )

        self._session.commit()

        finished = _utc_now()
        duration_ms = int((time.perf_counter() - t0) * 1000)
        audit_row.finished_at = finished
        audit_row.duration_ms = duration_ms
        audit_row.stats_json = stats
        audit_row.timing_json = timing
        self._session.commit()

        return {
            "ok": True,
            "mode": mode,
            "real_enabled": real_enabled,
            "shadow_observability_enabled": shadow_obs,
            "refresh_batch_id": batch_id,
            "trigger_source": trigger_source,
            "duration_ms": duration_ms,
            "timing": timing,
            "query_count": stats.get("query_count"),
            "roster_changed": roster_changed,
            "stats": stats,
            "monitored_symbols": symbols,
            "owned_symbols": sorted(owned),
            "fresh_cross_count": fresh_cross_count,
            "shadow_signal_count": shadow_signal_count,
            "real_signal_count": real_signal_count,
            "duplicate_real_blocked": duplicate_real_blocked,
            "fake_cross_prevented": fake_cross_prevented,
            "feed": feed_result,
            "DUPLICATE_REAL_SIGNAL_PROTECTED": True,
            "REAL_ORDER_MUTATION": real_signal_count,
            "EXECUTOR_DISPATCH": real_signal_count > 0,
        }
