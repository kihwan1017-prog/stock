"""UBA1380 P1 Autotrading Truth Bundle — READ-ONLY observability.

Fee / position lifecycle / PnL / risk snapshot / entry provenance / exit counts.
Risk 숫자·전략·Auth/LIVE/ARM 운영값을 변경하지 않는다.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.trading.uba_truth_layer import (
    balance_sync_status,
    exit_provenance_counts,
    position_truth,
    risk_semantics_snapshot,
)

KST = ZoneInfo("Asia/Seoul")
_UNKNOWN = "UNKNOWN"

UPBIT_FEE_SOURCE = (
    "upbit.paid_fee → trading_order.metadata_payload.upbit_paid_fee "
    "→ strategy_position_binding.fees"
)
CANONICAL_FEE_SOURCE_OF_TRUTH = (
    "operation.strategy_position_binding.fees "
    "(filled from order metadata upbit_paid_fee; no fee column on trading_order)"
)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def fee_truth_summary(
    session: Session, *, user_broker_account_id: int
) -> dict[str, Any]:
    """UPBIT fee SoT + BUY/SELL/PARTIAL 지원 플래그 + 완성도 (READ-ONLY)."""

    uba = int(user_broker_account_id)
    order_rows = session.execute(
        text(
            """
            SELECT order_id, side_code, status_code, metadata_payload,
                   filled_quantity, order_quantity
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND UPPER(COALESCE(broker_code, 'UPBIT')) = 'UPBIT'
              AND UPPER(status_code) IN (
                'FILLED', 'PARTIALLY_FILLED', 'PARTIAL_FILLED', 'DONE'
              )
            ORDER BY created_at DESC NULLS LAST
            LIMIT 500
            """
        ),
        {"uba": uba},
    ).mappings().all()

    buy_with_fee = buy_missing = 0
    sell_with_fee = sell_missing = 0
    partial_with_fee = partial_missing = 0
    samples_missing: list[dict[str, Any]] = []

    for r in order_rows:
        meta = _parse_meta(r.get("metadata_payload"))
        side = str(r.get("side_code") or "").upper()
        status = str(r.get("status_code") or "").upper()
        filled = float(r.get("filled_quantity") or 0)
        ordered = float(r.get("order_quantity") or 0)
        is_partial = "PARTIAL" in status or (
            ordered > 0 and filled > 0 and filled + 1e-12 < ordered
        )
        # 키 부재 = incomplete (0원 stamp는 complete)
        bucket_missing = not (
            "upbit_paid_fee" in meta or "paid_fee" in meta
        )
        if side == "BUY":
            if bucket_missing:
                buy_missing += 1
            else:
                buy_with_fee += 1
        elif side == "SELL":
            if bucket_missing:
                sell_missing += 1
            else:
                sell_with_fee += 1
        if is_partial:
            if bucket_missing:
                partial_missing += 1
            else:
                partial_with_fee += 1
        if bucket_missing and len(samples_missing) < 20:
            samples_missing.append(
                {
                    "order_id": r["order_id"],
                    "side": side,
                    "status": status,
                    "is_partial": is_partial,
                }
            )

    binding_rows = session.execute(
        text(
            """
            SELECT binding_id, status, fees
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
              AND UPPER(COALESCE(broker_code, 'UPBIT')) = 'UPBIT'
            """
        ),
        {"uba": uba},
    ).mappings().all()
    bindings_fee_set = sum(1 for b in binding_rows if b.get("fees") is not None)
    bindings_fee_null = sum(1 for b in binding_rows if b.get("fees") is None)

    total_filled = len(order_rows)
    missing_orders = buy_missing + sell_missing
    completeness_pct = (
        round(100.0 * (total_filled - missing_orders) / total_filled, 2)
        if total_filled
        else None
    )

    return {
        "UPBIT_FEE_SOURCE": UPBIT_FEE_SOURCE,
        "CANONICAL_FEE_SOURCE_OF_TRUTH": CANONICAL_FEE_SOURCE_OF_TRUTH,
        "BUY_FEE_SUPPORTED": True,
        "SELL_FEE_SUPPORTED": True,
        "PARTIAL_FILL_FEE_SUPPORTED": True,
        "FEE_COMPLETENESS": {
            "filled_order_sample_size": total_filled,
            "buy_with_fee": buy_with_fee,
            "buy_missing_fee": buy_missing,
            "sell_with_fee": sell_with_fee,
            "sell_missing_fee": sell_missing,
            "partial_with_fee": partial_with_fee,
            "partial_missing_fee": partial_missing,
            "bindings_fees_set": bindings_fee_set,
            "bindings_fees_null": bindings_fee_null,
            "completeness_pct": completeness_pct,
            "fee_incomplete": missing_orders > 0 or bindings_fee_null > 0,
            "samples_missing_fee": samples_missing,
        },
        "NOTES": [
            "trading_order has no fee_amount column; SoT is metadata upbit_paid_fee",
            "PARTIAL support = paid_fee stamp on PARTIALLY_FILLED / partial qty",
        ],
    }


def position_lifecycle_anomalies(
    session: Session, *, user_broker_account_id: int
) -> dict[str, Any]:
    """OPEN+qty0 / CLOSED+qty>0 등 lifecycle 이상 — DB WRITE 없음."""

    uba = int(user_broker_account_id)
    items: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    bindings = session.execute(
        text(
            """
            SELECT binding_id, symbol, status, owned_quantity, realized_pnl,
                   opened_at, closed_at
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
            """
        ),
        {"uba": uba},
    ).mappings().all()
    for b in bindings:
        status = str(b.get("status") or "").upper()
        qty = float(b.get("owned_quantity") or 0)
        oa, ca = b.get("opened_at"), b.get("closed_at")
        if status == "OPEN" and qty <= 0:
            kind, classification = "OPEN_QTY0", "LIFECYCLE_DATA_BUG_OR_STALE"
        elif status == "CLOSED" and qty > 0:
            kind, classification = "CLOSED_QTY_POSITIVE", "LIFECYCLE_DATA_BUG"
        elif status == "CLOSED" and oa and ca and ca < oa:
            kind, classification = (
                "CLOSED_BEFORE_OPENED",
                "TIMESTAMP_INVARIANT_VIOLATION",
            )
        elif status == "OPEN" and ca is not None:
            kind, classification = (
                "OPEN_WITH_CLOSED_AT",
                "LIFECYCLE_DATA_BUG_OR_STALE",
            )
        else:
            continue
        counts[kind] += 1
        items.append(
            {
                "type": kind,
                "classification": classification,
                "entity": "binding",
                "binding_id": b["binding_id"],
                "symbol": b.get("symbol"),
                "status": status,
                "owned_quantity": str(b.get("owned_quantity")),
                "realized_pnl": str(b.get("realized_pnl")),
            }
        )

    slots = session.execute(
        text(
            """
            SELECT slot_id, symbol, status, opened_at, closed_at
            FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba
            """
        ),
        {"uba": uba},
    ).mappings().all()
    for r in slots:
        status = str(r.get("status") or "").upper()
        oa, ca = r.get("opened_at"), r.get("closed_at")
        if oa and ca and ca < oa:
            kind, classification = (
                "SLOT_CLOSED_BEFORE_OPENED",
                "TIMESTAMP_INVARIANT_VIOLATION",
            )
        elif status == "WAITING_SIGNAL" and oa:
            kind, classification = (
                "WAITING_WITH_OPENED_AT",
                "REUSE_BY_DESIGN_OR_DISPLAY",
            )
        elif status == "OPEN" and ca is not None:
            kind, classification = (
                "SLOT_OPEN_WITH_CLOSED_AT",
                "LIFECYCLE_DATA_BUG_OR_STALE",
            )
        else:
            continue
        counts[kind] += 1
        items.append(
            {
                "type": kind,
                "classification": classification,
                "entity": "slot",
                "slot_id": r["slot_id"],
                "symbol": r.get("symbol"),
                "status": status,
            }
        )

    return {
        "anomaly_count": len(items),
        "counts": dict(counts),
        "items": items[:100],
        "classification_legend": {
            "LIFECYCLE_DATA_BUG": "status/qty 불일치 — 조사 대상",
            "LIFECYCLE_DATA_BUG_OR_STALE": "버그 또는 미정리 stale row",
            "TIMESTAMP_INVARIANT_VIOLATION": "closed_at < opened_at",
            "REUSE_BY_DESIGN_OR_DISPLAY": "WAITING_SIGNAL reuse 표시 잔여",
        },
        "READ_ONLY": True,
    }


def pnl_fee_incomplete_from_trades(closed_trades: list[dict[str, Any]]) -> dict[str, Any]:
    """표시 로직 — gross≠0인데 fees 미기록/0이면 fee_incomplete."""

    incomplete_n = 0
    for t in closed_trades:
        raw_fee = t.get("fees")
        if raw_fee is None:
            incomplete_n += 1
            continue
        try:
            fee = Decimal(str(raw_fee))
            gross = Decimal(str(t.get("gross_pnl") or 0))
        except Exception:  # noqa: BLE001
            incomplete_n += 1
            continue
        if fee == 0 and gross != 0:
            incomplete_n += 1
    return {
        "fee_incomplete": incomplete_n > 0,
        "fee_incomplete_trade_count": incomplete_n,
        "fee_incomplete_display_note_ko": (
            "일부 체결에 수수료(upbit_paid_fee/binding.fees)가 비어 NET PnL이 "
            "과대·과소 표시될 수 있습니다."
            if incomplete_n > 0
            else None
        ),
    }


def pnl_truth_compare(
    session: Session, *, user_broker_account_id: int
) -> dict[str, Any]:
    """AutotradingPerformanceService + binding realized_pnl (7D/ALL)."""

    from stock_platform.operation.autotrading_performance_service import (
        AutotradingPerformanceService,
    )

    uba = int(user_broker_account_id)
    svc = AutotradingPerformanceService(session)
    windows: dict[str, Any] = {}
    for period in ("7D", "ALL"):
        try:
            payload = svc.build(
                broker="UPBIT",
                period=period,  # type: ignore[arg-type]
                user_broker_account_id=uba,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            windows[period] = {
                "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            }
            continue
        summary = payload.get("summary") or {}
        win_loss = payload.get("win_loss") or {}
        closed = list(payload.get("round_trips") or [])
        fee_flags = pnl_fee_incomplete_from_trades(closed)
        windows[period] = {
            "GROSS": summary.get("period_gross_pnl")
            or summary.get("cumulative_gross_pnl"),
            "FEES": summary.get("period_fees")
            or summary.get("cumulative_fees"),
            "NET": summary.get("period_net_pnl")
            or summary.get("period_realized_pnl")
            or summary.get("cumulative_net_pnl"),
            "win_loss": win_loss,
            "closed_trade_count": payload.get("closed_trade_count"),
            **fee_flags,
            "summary": {
                k: summary.get(k)
                for k in (
                    "period_gross_pnl",
                    "period_fees",
                    "period_net_pnl",
                    "period_return_pct",
                    "win_rate_pct",
                    "closed_trade_count",
                    "cumulative_gross_pnl",
                    "cumulative_fees",
                    "cumulative_net_pnl",
                )
                if k in summary
            },
        }

    binding_agg = session.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE UPPER(status)='CLOSED')::int AS closed_n,
              COALESCE(
                SUM(realized_pnl) FILTER (WHERE UPPER(status)='CLOSED'), 0
              )::text AS sum_realized_pnl,
              COALESCE(
                SUM(fees) FILTER (WHERE UPPER(status)='CLOSED'), 0
              )::text AS sum_fees,
              COUNT(*) FILTER (
                WHERE UPPER(status)='CLOSED' AND fees IS NULL
              )::int AS closed_fees_null
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
              AND UPPER(COALESCE(broker_code,'UPBIT')) = 'UPBIT'
              AND UPPER(COALESCE(ownership_code,''))
                  NOT IN ('MANUAL','USER','EXTERNAL')
            """
        ),
        {"uba": uba},
    ).mappings().first()

    any_fee_incomplete = any(
        bool(w.get("fee_incomplete"))
        for w in windows.values()
        if isinstance(w, dict)
    ) or int((binding_agg or {}).get("closed_fees_null") or 0) > 0

    return {
        "REALIZED_PNL_SOURCE_OF_TRUTH": (
            "operation.strategy_position_binding.realized_pnl"
        ),
        "FEE_SOURCE": CANONICAL_FEE_SOURCE_OF_TRUTH,
        "windows": windows,
        "binding_aggregate_all": dict(binding_agg) if binding_agg else None,
        "fee_incomplete": any_fee_incomplete,
        "fee_incomplete_display_note_ko": (
            "일부 체결에 수수료(upbit_paid_fee/binding.fees)가 비어 NET PnL이 "
            "과대·과소 표시될 수 있습니다."
            if any_fee_incomplete
            else None
        ),
    }


def build_risk_decision_snapshot(
    *,
    allowed: bool,
    result: str | None = None,
    reason_codes: list[str] | str | None = None,
    limits: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """미래 BUY metadata용 immutable risk 결정 스냅샷 (과거 백필 금지)."""

    if isinstance(reason_codes, str):
        codes = [reason_codes] if reason_codes else []
    elif isinstance(reason_codes, list):
        codes = [str(c) for c in reason_codes if c is not None]
    else:
        codes = []
    snap: dict[str, Any] = {
        "schema": "risk_decision_snapshot_v1",
        "allowed": bool(allowed),
        "result": result
        or ("PASS" if allowed else (codes[0] if codes else "BLOCKED")),
        "reason_codes": codes,
        "limits": dict(limits or {}),
        "usage": dict(usage or {}),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        for k, v in extra.items():
            if k not in snap:
                snap[k] = v
    return snap


def maybe_stamp_risk_decision_snapshot(
    metadata: dict[str, Any] | None,
    snapshot: dict[str, Any],
    *,
    side: str | None = None,
) -> dict[str, Any]:
    """BUY만 · 이미 있으면 덮지 않음."""

    meta = dict(metadata or {})
    side_u = str(side or "").upper()
    if side_u and side_u != "BUY":
        return meta
    if meta.get("risk_decision_snapshot"):
        return meta
    meta["risk_decision_snapshot"] = dict(snapshot)
    return meta


def build_scanner_to_fill_provenance(
    session: Session,
    *,
    order_id: int | None = None,
    binding_id: int | None = None,
) -> dict[str, Any]:
    """scanner → selection → trace → order → fill ID 조인 (없으면 UNKNOWN)."""

    def _id_or_unknown(val: Any) -> Any:
        if val is None or val == "":
            return _UNKNOWN
        return val

    order_row = None
    binding_row = None
    resolved_order_id = order_id
    if binding_id is not None:
        binding_row = session.execute(
            text(
                """
                SELECT binding_id, entry_order_id, symbol, meta_json,
                       user_broker_account_id
                FROM operation.strategy_position_binding
                WHERE binding_id = :bid
                """
            ),
            {"bid": int(binding_id)},
        ).mappings().first()
        if (
            binding_row
            and binding_row.get("entry_order_id")
            and resolved_order_id is None
        ):
            resolved_order_id = int(binding_row["entry_order_id"])

    if resolved_order_id is not None:
        order_row = session.execute(
            text(
                """
                SELECT order_id, symbol, metadata_payload, broker_order_id,
                       client_order_id, user_broker_account_id
                FROM trading.trading_order
                WHERE order_id = :oid
                """
            ),
            {"oid": int(resolved_order_id)},
        ).mappings().first()

    meta = _parse_meta((order_row or {}).get("metadata_payload"))
    bmeta = _parse_meta((binding_row or {}).get("meta_json"))

    trace_id = meta.get("execution_trace_id") or bmeta.get("execution_trace_id")
    selection_id = (
        meta.get("candidate_selection_id")
        or meta.get("selection_id")
        or bmeta.get("candidate_selection_id")
        or bmeta.get("selection_id")
    )
    candidate_id = meta.get("candidate_id") or bmeta.get("candidate_id")
    waiting_id = meta.get("waiting_id") or bmeta.get("waiting_id")
    scanner_run_id = meta.get("scanner_run_id") or bmeta.get("scanner_run_id")

    if (trace_id or selection_id or resolved_order_id) and order_row is not None:
        uba = order_row.get("user_broker_account_id")
        try:
            trow = session.execute(
                text(
                    """
                    SELECT execution_trace_id, selection_id, candidate_id
                    FROM operation.upbit_entry_execution_trace
                    WHERE user_broker_account_id = :uba
                      AND (
                        (:tid IS NOT NULL AND execution_trace_id = :tid)
                        OR (:sid IS NOT NULL AND selection_id = :sid)
                        OR order_id = :oid
                      )
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {
                    "uba": int(uba) if uba is not None else -1,
                    "tid": str(trace_id) if trace_id else None,
                    "sid": (
                        int(selection_id) if selection_id is not None else None
                    ),
                    "oid": (
                        int(resolved_order_id)
                        if resolved_order_id is not None
                        else -1
                    ),
                },
            ).mappings().first()
            if trow:
                trace_id = trace_id or trow.get("execution_trace_id")
                selection_id = selection_id or trow.get("selection_id")
                candidate_id = candidate_id or trow.get("candidate_id")
        except Exception:  # noqa: BLE001
            session.rollback()

    exit_order_id = bmeta.get("exit_order_id")
    ids = {
        "order_id": _id_or_unknown(
            resolved_order_id or (order_row or {}).get("order_id")
        ),
        "binding_id": _id_or_unknown(
            binding_id or (binding_row or {}).get("binding_id")
        ),
        "scanner_run_id": _id_or_unknown(scanner_run_id),
        "candidate_selection_id": _id_or_unknown(selection_id),
        "selection_id": _id_or_unknown(selection_id),
        "candidate_id": _id_or_unknown(candidate_id),
        "waiting_id": _id_or_unknown(waiting_id),
        "execution_trace_id": _id_or_unknown(trace_id),
        "broker_order_id": _id_or_unknown(
            (order_row or {}).get("broker_order_id")
        ),
        "client_order_id": _id_or_unknown(
            (order_row or {}).get("client_order_id")
        ),
        "symbol": _id_or_unknown(
            (order_row or {}).get("symbol")
            or (binding_row or {}).get("symbol")
        ),
        "exit_order_id": _id_or_unknown(exit_order_id),
    }
    return {
        **ids,
        "missing_any": any(
            ids[k] == _UNKNOWN
            for k in (
                "scanner_run_id",
                "candidate_selection_id",
                "execution_trace_id",
            )
        ),
        "SOURCE": "order.metadata + upbit_entry_execution_trace + binding.meta",
    }


def auth_lease_truth_summary(
    session: Session, *, user_broker_account_id: int
) -> dict[str, Any]:
    """Auth 만료 / lease auto renew / auth auto extend 표시 (READ-ONLY)."""

    uba = int(user_broker_account_id)
    auth = session.execute(
        text(
            """
            SELECT live_unattended_authorization_id, status_code,
                   authorized_until, auto_renew_enabled,
                   last_renewal_detail, approved_at
            FROM operation.live_unattended_authorization
            WHERE user_broker_account_id = :uba
            ORDER BY approved_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"uba": uba},
    ).mappings().first()
    detail = _parse_meta((auth or {}).get("last_renewal_detail"))
    auto_renew = bool((auth or {}).get("auto_renew_enabled"))
    auth_auto_extend = bool(
        detail.get("auth_auto_extend_enabled")
        or detail.get("authorization_auto_extend_enabled")
    )
    until = _aware((auth or {}).get("authorized_until"))
    now = datetime.now(KST)
    expired = until is not None and until < now
    return {
        "authorized_until": until.isoformat() if until else None,
        "auth_expired": expired,
        "auth_expiry_label": (
            "EXPIRED" if expired else ("ACTIVE" if until else "NONE")
        ),
        "lease_auto_renew_enabled": auto_renew,
        "lease_auto_renew_label": "ON" if auto_renew else "OFF",
        "auth_auto_extend_enabled": auth_auto_extend,
        "auth_auto_extend_label": "ON" if auth_auto_extend else "OFF",
        "status_code": (auth or {}).get("status_code"),
        "authorization_id": (auth or {}).get(
            "live_unattended_authorization_id"
        ),
    }


def build_uba_truth_bundle(
    session: Session,
    *,
    user_broker_account_id: int,
    exit_since_hours: int = 24 * 7,
) -> dict[str, Any]:
    """Admin truth-bundle — position/fee/pnl/risk/entry/exit/auth READ-ONLY."""

    uba = int(user_broker_account_id)
    since = datetime.now(KST) - timedelta(hours=int(exit_since_hours))
    fee = fee_truth_summary(session, user_broker_account_id=uba)
    anomalies = position_lifecycle_anomalies(
        session, user_broker_account_id=uba
    )
    pnl = pnl_truth_compare(session, user_broker_account_id=uba)
    exits = exit_provenance_counts(
        session, user_broker_account_id=uba, since=since
    )
    auth = auth_lease_truth_summary(session, user_broker_account_id=uba)
    return {
        "user_broker_account_id": uba,
        "broker_scope": "UPBIT",
        "generated_at": datetime.now(KST).isoformat(),
        "READ_ONLY": True,
        "position": position_truth(session, user_broker_account_id=uba),
        "position_lifecycle_anomalies": anomalies,
        "fee": fee,
        "pnl": pnl,
        "risk_semantics": risk_semantics_snapshot(
            session, user_broker_account_id=uba
        ),
        "balance_sync": balance_sync_status(
            session, user_broker_account_id=uba
        ),
        "exit_reason_counts": exits,
        "auth": auth,
        "fee_incomplete": bool(
            (fee.get("FEE_COMPLETENESS") or {}).get("fee_incomplete")
            or pnl.get("fee_incomplete")
        ),
        "fee_incomplete_display_note_ko": pnl.get(
            "fee_incomplete_display_note_ko"
        )
        or (
            "수수료 기록이 일부 누락되어 있습니다."
            if (fee.get("FEE_COMPLETENESS") or {}).get("fee_incomplete")
            else None
        ),
    }

