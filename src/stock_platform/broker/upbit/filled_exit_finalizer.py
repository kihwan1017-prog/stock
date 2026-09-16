"""UPBIT FILLED exit → binding/slot canonical finalizer (idempotent).

ROOT CAUSE (2026-08-26): POSITION_EXIT_MONITOR SELL 주문에 strategy_id /
order_source=AUTO 가 없어 fill sync가 binding close를 early-return 함.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

ZERO = Decimal("0")
BROKER_UPBIT = "UPBIT"
EXIT_SOURCES = frozenset({"POSITION_EXIT_MONITOR", "REALTIME_SIGNAL", "AUTO"})
EXIT_ORDER_SOURCES = frozenset({"EXIT", "AUTO"})


def _meta(order: Any) -> dict[str, Any]:
    raw = getattr(order, "metadata_payload", None) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _order_source(order: Any) -> str:
    meta = _meta(order)
    return str(
        getattr(order, "order_source", None)
        or meta.get("order_source")
        or ""
    ).upper()


def is_protective_or_auto_exit_sell(order: Any) -> bool:
    """AUTO MA exit 또는 EXIT monitor protective sell."""

    if str(getattr(order, "side_code", "") or "").upper() != "SELL":
        return False
    status = str(getattr(order, "status_code", "") or "").upper()
    if status not in {"FILLED", "PARTIALLY_FILLED"}:
        return False
    meta = _meta(order)
    src = str(meta.get("source") or "").upper()
    o_src = _order_source(order)
    if o_src in EXIT_ORDER_SOURCES:
        return True
    if src in EXIT_SOURCES:
        return True
    if meta.get("exit_reason") or meta.get("signal_reason"):
        return True
    return False


def resolve_strategy_id_for_exit(
    session: Session,
    *,
    order: Any,
) -> int | None:
    """order → meta → OPEN strategy_position_binding(uba+symbol) 순 해석."""

    sid = getattr(order, "strategy_id", None)
    if sid is not None:
        try:
            return int(sid)
        except (TypeError, ValueError):
            pass
    meta = _meta(order)
    if meta.get("strategy_id") is not None:
        try:
            return int(meta["strategy_id"])
        except (TypeError, ValueError):
            pass

    uba_id = getattr(order, "user_broker_account_id", None)
    symbol = str(getattr(order, "symbol", "") or "").upper()
    if uba_id is None or not symbol:
        return None

    from stock_platform.risk_engine.strategy_owned_entities import (
        BINDING_STATUS_OPEN,
        StrategyPositionBindingEntity,
    )

    row = session.scalar(
        select(StrategyPositionBindingEntity)
        .where(
            StrategyPositionBindingEntity.user_broker_account_id
            == int(uba_id),
            StrategyPositionBindingEntity.broker_code == BROKER_UPBIT,
            StrategyPositionBindingEntity.symbol == symbol,
            StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
        )
        .order_by(StrategyPositionBindingEntity.opened_at.desc())
        .limit(1)
    )
    if row is None or row.strategy_id is None:
        return None
    return int(row.strategy_id)


def stamp_strategy_id_on_order(
    session: Session, *, order: Any, strategy_id: int
) -> None:
    """미래 sync용 meta stamp만 수행 (order column dirty 금지).

    TradingOrderEntity.strategy_id 컬럼을 건드리면 flush 시
    strategy_deployment FK 메타 오류가 날 수 있어 meta만 보강한다.
    """

    del session  # API 호환 — session 미사용
    meta = _meta(order)
    if meta.get("strategy_id") is None:
        meta = dict(meta)
        meta["strategy_id"] = int(strategy_id)
        try:
            # MutableDict / JSON 필드 — 가능하면 in-place update
            payload = getattr(order, "metadata_payload", None)
            if isinstance(payload, dict):
                payload["strategy_id"] = int(strategy_id)
            else:
                order.metadata_payload = meta
        except Exception:  # noqa: BLE001
            pass


def finalize_filled_exit(
    session: Session,
    *,
    order: Any,
    remote: dict[str, Any] | None = None,
    actor: str = "FILLED_EXIT_FINALIZER",
) -> dict[str, Any]:
    """SELL FILLED 이후 binding close + slot reconcile (멱등).

    브로커 주문은 생성하지 않는다.
    """

    remote = remote or {}
    if str(getattr(order, "side_code", "") or "").upper() != "SELL":
        return {"ok": False, "reason": "NOT_SELL"}
    status = str(getattr(order, "status_code", "") or "").upper()
    if status != "FILLED":
        return {"ok": False, "reason": "NOT_FILLED", "status": status}

    uba_id = getattr(order, "user_broker_account_id", None)
    if uba_id is None:
        return {"ok": False, "reason": "NO_UBA"}
    if str(getattr(order, "broker_code", "") or "").upper() != BROKER_UPBIT:
        return {"ok": False, "reason": "NOT_UPBIT"}

    strategy_id = resolve_strategy_id_for_exit(session, order=order)
    if strategy_id is None:
        return {
            "ok": False,
            "reason": "STRATEGY_ID_UNRESOLVED",
            "order_id": int(getattr(order, "order_id", 0) or 0),
            "symbol": getattr(order, "symbol", None),
        }

    # order.strategy_id 컬럼은 dirty 하지 않음 — binding close만 수행
    try:
        stamp_strategy_id_on_order(session, order=order, strategy_id=strategy_id)
    except Exception:  # noqa: BLE001
        pass

    from stock_platform.broker.upbit.order_status import upbit_fill_summary
    from stock_platform.risk_engine.strategy_owned_risk_service import (
        StrategyOwnedRiskService,
    )

    summary = upbit_fill_summary(remote) if remote else {}
    qty = Decimal(str(summary.get("executed_volume") or 0))
    if qty <= ZERO:
        qty = Decimal(str(getattr(order, "filled_quantity", 0) or 0))
    px = Decimal(str(summary.get("avg_price") or 0))
    if px <= ZERO:
        px = Decimal(str(getattr(order, "average_fill_price", 0) or 0))
    fees = Decimal(str(summary.get("paid_fee") or 0))
    if fees <= ZERO:
        meta = _meta(order)
        fees = Decimal(str(meta.get("upbit_paid_fee") or 0))
    filled_at = getattr(order, "filled_at", None) or datetime.now(timezone.utc)
    # expired attribute 접근 회피 — deployment_id는 선택
    try:
        deployment_id = order.__dict__.get("strategy_deployment_id")
    except Exception:  # noqa: BLE001
        deployment_id = None

    svc = StrategyOwnedRiskService(session)
    binding = svc.ensure_binding_from_fill(
        user_broker_account_id=int(uba_id),
        broker_code=BROKER_UPBIT,
        strategy_id=int(strategy_id),
        deployment_id=deployment_id,
        symbol=str(getattr(order, "symbol", "") or ""),
        entry_order_id=None,
        broker_order_id=str(getattr(order, "broker_order_id", "") or "")
        or None,
        quantity=qty,
        entry_price=None,
        side="SELL",
        fees=fees,
        fill_price=px if px > ZERO else None,
        exit_order_id=int(order.order_id),
        filled_at=filled_at,
    )
    svc.compute_and_persist(
        user_broker_account_id=int(uba_id),
        broker_code=BROKER_UPBIT,
        strategy_id=int(strategy_id),
        deployment_id=deployment_id,
    )

    # research-only exit observation (전략 파라미터 변경 아님)
    if binding is not None:
        try:
            meta_b = dict(binding.meta_json or {})
            exit_obs = dict(meta_b.get("exit_observation") or {})
            om = _meta(order)
            exit_obs.update(
                {
                    "exit_order_id": int(order.order_id),
                    "exit_reason": str(
                        om.get("exit_reason")
                        or om.get("signal_reason")
                        or "NOT_RECORDED"
                    ),
                    "exit_source": str(om.get("source") or ""),
                    "exit_price": float(px) if px > ZERO else None,
                    "exit_at": filled_at.isoformat()
                    if hasattr(filled_at, "isoformat")
                    else str(filled_at),
                    "finalizer_actor": str(actor)[:80],
                }
            )
            meta_b["exit_observation"] = exit_obs
            binding.meta_json = meta_b
        except Exception:  # noqa: BLE001
            pass

    try:
        from stock_platform.operation.upbit_full_market.constants import (
            is_full_market_portfolio,
        )
        from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
            reconcile_portfolio_slot_lifecycle,
        )
        from stock_platform.operation.upbit_full_market.service import (
            UpbitFullMarketAssignmentService,
        )

        assignment = UpbitFullMarketAssignmentService(session).get_or_create(
            int(uba_id)
        )
        if is_full_market_portfolio(assignment.mode):
            reconcile_portfolio_slot_lifecycle(
                session,
                user_broker_account_id=int(uba_id),
                symbol=str(getattr(order, "symbol", "") or ""),
                actor=actor,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "filled_exit_slot_reconcile_failed",
            order_id=int(getattr(order, "order_id", 0) or 0),
            error=str(exc)[:200],
        )

    session.flush()
    binding_status = (
        str(getattr(binding, "status", None) or "") if binding else None
    )
    logger.info(
        "filled_exit_finalized",
        order_id=int(order.order_id),
        symbol=str(getattr(order, "symbol", "") or ""),
        strategy_id=int(strategy_id),
        binding_status=binding_status,
        actor=str(actor)[:80],
    )
    # Observability V1 — post-trade MFE/MAE/post-exit (analytics only, fail-open)
    try:
        if (
            binding is not None
            and str(binding_status or "").upper() == "CLOSED"
            and getattr(binding, "binding_id", None)
        ):
            from stock_platform.operation.upbit_strategy_observability.post_trade import (
                compute_post_trade_analytics_safe,
            )

            compute_post_trade_analytics_safe(
                binding_id=int(binding.binding_id),
                user_broker_account_id=int(uba_id),
                strategy_id=int(strategy_id),
                symbol=str(getattr(order, "symbol", "") or ""),
                opened_at=getattr(binding, "opened_at", None),
                closed_at=getattr(binding, "closed_at", None) or filled_at,
                entry_price=getattr(binding, "entry_price", None),
                exit_price=px if px > ZERO else None,
            )
            # fill stamp on timeline
            from stock_platform.operation.upbit_strategy_observability.hooks import (
                observe_order_timeline_stamp,
            )

            observe_order_timeline_stamp(
                user_broker_account_id=int(uba_id),
                symbol=str(getattr(order, "symbol", "") or ""),
                side_code="SELL",
                order_id=int(order.order_id),
                strategy_id=int(strategy_id),
                binding_id=int(binding.binding_id),
                stamps={"fill_at": filled_at},
            )
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "order_id": int(order.order_id),
        "symbol": str(getattr(order, "symbol", "") or ""),
        "strategy_id": int(strategy_id),
        "binding_id": int(binding.binding_id)
        if binding is not None and getattr(binding, "binding_id", None)
        else None,
        "binding_status": binding_status,
        "actor": actor,
    }


def detect_filled_exit_with_open_binding(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Invariant: FILLED protective/AUTO SELL + OPEN binding same symbol.

    동시 종목 재진입/병행 exit 오탐 방지:
    - OPEN SELL(잔량≈owned)이 있으면 ACTIVE_EXIT → ghost 아님
    - FILLED SELL 수량이 owned와 불일치하면 해당 sell은 무시
    """

    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.risk_engine.strategy_owned_entities import (
        BINDING_STATUS_OPEN,
        StrategyPositionBindingEntity,
    )

    open_q = select(StrategyPositionBindingEntity).where(
        StrategyPositionBindingEntity.broker_code == BROKER_UPBIT,
        StrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
    )
    if user_broker_account_id is not None:
        open_q = open_q.where(
            StrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    opens = list(session.scalars(open_q))
    ghosts: list[dict[str, Any]] = []
    skipped_active_exit = 0
    skipped_qty_mismatch = 0
    for binding in opens:
        uba = int(binding.user_broker_account_id)
        sym = str(binding.symbol or "").upper()
        owned = Decimal(str(binding.owned_quantity or 0))

        # 활성 exit 주문(대기/부분체결)이 owned 잔량과 맞으면 ghost 아님
        open_sells = list(
            session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.broker_code == BROKER_UPBIT,
                    TradingOrderEntity.symbol == sym,
                    TradingOrderEntity.side_code == "SELL",
                    TradingOrderEntity.status_code.in_(
                        ["NEW", "ACCEPTED", "PARTIALLY_FILLED", "SUBMITTING"]
                    ),
                )
            )
        )
        active_exit = False
        for osell in open_sells:
            rem = Decimal(
                str(
                    getattr(osell, "remaining_quantity", None)
                    or getattr(osell, "order_quantity", None)
                    or 0
                )
            )
            if owned > ZERO and abs(rem - owned) <= Decimal("0.00000001"):
                active_exit = True
                break
            if owned > ZERO and rem > ZERO:
                # 동일 심볼 open exit 존재 + owned>0 → 진행 중으로 간주
                active_exit = True
                break
        if active_exit:
            skipped_active_exit += 1
            continue

        sells = list(
            session.scalars(
                select(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id == uba,
                    TradingOrderEntity.broker_code == BROKER_UPBIT,
                    TradingOrderEntity.symbol == sym,
                    TradingOrderEntity.side_code == "SELL",
                    TradingOrderEntity.status_code == "FILLED",
                )
                .order_by(TradingOrderEntity.order_id.desc())
            )
        )
        for sell in sells:
            if not is_protective_or_auto_exit_sell(sell):
                continue
            filled_qty = Decimal(str(getattr(sell, "filled_quantity", None) or 0))
            # 병행 entry의 다른 exit을 현재 binding ghost로 묶지 않음
            if owned > ZERO and filled_qty > ZERO:
                if abs(filled_qty - owned) > Decimal("0.0001"):
                    skipped_qty_mismatch += 1
                    continue
            sell_ts = getattr(sell, "filled_at", None) or getattr(
                sell, "created_at", None
            )
            if binding.entry_order_id is not None:
                entry = session.get(
                    TradingOrderEntity, int(binding.entry_order_id)
                )
                entry_ts = (
                    getattr(entry, "filled_at", None)
                    or getattr(entry, "created_at", None)
                    if entry
                    else None
                )
                # 재진입: entry가 sell 이후면 이 sell의 ghost 아님
                if entry_ts and sell_ts and entry_ts > sell_ts:
                    continue
                if entry_ts and sell_ts and sell_ts < entry_ts:
                    continue
            meta = _meta(sell)
            ghosts.append(
                {
                    "binding_id": int(binding.binding_id),
                    "symbol": sym,
                    "user_broker_account_id": uba,
                    "entry_order_id": int(binding.entry_order_id)
                    if binding.entry_order_id
                    else None,
                    "sell_order_id": int(sell.order_id),
                    "exit_reason": str(
                        meta.get("exit_reason")
                        or meta.get("signal_reason")
                        or ""
                    ),
                    "owned_quantity": str(binding.owned_quantity),
                }
            )
            break

    return {
        "invariant": "FILLED_EXIT_WITH_OPEN_BINDING",
        "count": len(ghosts),
        "symbols": sorted({g["symbol"] for g in ghosts}),
        "binding_ids": [g["binding_id"] for g in ghosts],
        "items": ghosts,
        "skipped_active_exit": skipped_active_exit,
        "skipped_qty_mismatch": skipped_qty_mismatch,
    }


def dry_run_ghost_reconciliation(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """SAFE_TO_CLOSE / NOT_SAFE_TO_CLOSE 판정 only — mutation 없음."""

    from stock_platform.order.entities import TradingOrderEntity

    detected = detect_filled_exit_with_open_binding(
        session, user_broker_account_id=user_broker_account_id
    )
    decisions: list[dict[str, Any]] = []
    for item in detected["items"]:
        reasons_ok: list[str] = []
        reasons_block: list[str] = []
        buy_id = item.get("entry_order_id")
        sell_id = item.get("sell_order_id")
        buy = session.get(TradingOrderEntity, int(buy_id)) if buy_id else None
        sell = (
            session.get(TradingOrderEntity, int(sell_id)) if sell_id else None
        )
        if buy is None or str(buy.status_code).upper() != "FILLED":
            reasons_block.append("BUY_MISSING_OR_NOT_FILLED")
        else:
            reasons_ok.append("BUY_FILLED")
        if sell is None or str(sell.status_code).upper() != "FILLED":
            reasons_block.append("SELL_MISSING_OR_NOT_FILLED")
        else:
            reasons_ok.append("SELL_FILLED")
            if is_protective_or_auto_exit_sell(sell):
                reasons_ok.append("EXIT_PROVENANCE_OK")
            else:
                reasons_block.append("EXIT_PROVENANCE_UNCLEAR")

        open_sells = list(
            session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    TradingOrderEntity.broker_code == BROKER_UPBIT,
                    TradingOrderEntity.symbol == item["symbol"],
                    TradingOrderEntity.side_code == "SELL",
                    TradingOrderEntity.status_code.in_(
                        ["NEW", "ACCEPTED", "PARTIALLY_FILLED", "SUBMITTING"]
                    ),
                )
            )
        )
        if open_sells:
            reasons_block.append("OPEN_SELL_ORDER_EXISTS")
        else:
            reasons_ok.append("NO_OPEN_SELL")

        broker_qty: Decimal | None = None
        try:
            row = session.execute(
                text(
                    """
                    SELECT quantity FROM trading.broker_position_snapshot
                    WHERE user_broker_account_id = :uba
                      AND UPPER(symbol) = :sym
                    ORDER BY synchronized_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"uba": int(user_broker_account_id), "sym": item["symbol"]},
            ).first()
            if row is not None:
                broker_qty = Decimal(str(row[0] or 0))
        except Exception:  # noqa: BLE001
            broker_qty = None

        if broker_qty is not None:
            if broker_qty <= ZERO:
                reasons_ok.append("BROKER_QTY_ZERO")
            else:
                reasons_block.append(f"BROKER_QTY_REMAINING={broker_qty}")
        else:
            # snapshot 없으면 FILLED SELL + linkage만으로 SAFE 허용
            # (audit: broker snapshot stale로 qty=0 누락되는 경우 있음)
            reasons_ok.append("BROKER_SNAPSHOT_UNAVAILABLE_ALLOW_LINKAGE")

        safe = len(reasons_block) == 0
        decisions.append(
            {
                **item,
                "verdict": "SAFE_TO_CLOSE" if safe else "NOT_SAFE_TO_CLOSE",
                "reasons_ok": reasons_ok,
                "reasons_block": reasons_block,
                "broker_qty": str(broker_qty) if broker_qty is not None else None,
            }
        )

    return {
        "user_broker_account_id": int(user_broker_account_id),
        "ghost_count": len(decisions),
        "safe_count": sum(
            1 for d in decisions if d["verdict"] == "SAFE_TO_CLOSE"
        ),
        "decisions": decisions,
    }


def reconcile_safe_ghost_bindings(
    session: Session,
    *,
    user_broker_account_id: int,
    actor: str = "GHOST_BINDING_RECONCILE",
    dry_run: bool = True,
) -> dict[str, Any]:
    """SAFE_TO_CLOSE 만 canonical finalizer로 정리. dry_run 기본 True."""

    from stock_platform.order.entities import TradingOrderEntity

    report = dry_run_ghost_reconciliation(
        session, user_broker_account_id=user_broker_account_id
    )
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for d in report["decisions"]:
        if d["verdict"] != "SAFE_TO_CLOSE":
            skipped.append(d)
            continue
        if dry_run:
            applied.append({**d, "action": "DRY_RUN_WOULD_CLOSE"})
            continue
        sell = session.get(TradingOrderEntity, int(d["sell_order_id"]))
        if sell is None:
            skipped.append({**d, "skip": "SELL_GONE"})
            continue
        meta = _meta(sell)
        remote = {
            "state": "done",
            "executed_volume": str(sell.filled_quantity or 0),
            "avg_price": str(sell.average_fill_price or 0),
            "paid_fee": str(meta.get("upbit_paid_fee") or 0),
            "trades": [],
        }
        result = finalize_filled_exit(
            session, order=sell, remote=remote, actor=actor
        )
        applied.append({**d, "action": "FINALIZED", "result": result})
        logger.info(
            "ghost_binding_reconciled",
            binding_id=d["binding_id"],
            sell_order_id=d["sell_order_id"],
            symbol=d["symbol"],
            actor=actor,
            result_ok=result.get("ok"),
        )

    if not dry_run and applied:
        session.flush()

    return {
        "dry_run": dry_run,
        "user_broker_account_id": int(user_broker_account_id),
        "report": report,
        "applied": applied,
        "skipped": skipped,
        "RECONCILED_COUNT": len(
            [a for a in applied if a.get("action") == "FINALIZED"]
        ),
    }
