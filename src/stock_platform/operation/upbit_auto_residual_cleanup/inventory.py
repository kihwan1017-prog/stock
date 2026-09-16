# -*- coding: utf-8 -*-
"""DB/스냅샷에서 residual cleanup preview inventory 구성 (READ + eligibility)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    ALLOWED_CLEANUP_KINDS,
    ARCHITECTURE,
    KIND_HISTORICAL_ONLY,
    MANUAL_PROTECTED_CURRENCIES,
    ZERO,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    ResidualCleanupContext,
    symbol_currency,
)
from stock_platform.operation.upbit_auto_residual_cleanup.service import (
    preview_cleanup,
)
from stock_platform.risk_engine.exit_risk import load_pending_sell_quantity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_identity import uba_kill_switch_scope


def _dec(value: Any) -> Decimal:
    if value is None:
        return ZERO
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return ZERO


def load_binding_truth_rows(
    session: Session,
    *,
    user_broker_account_id: int,
) -> list[dict[str, Any]]:
    """auto_residual_truth 가 있는 AUTO binding 목록."""

    rows = session.execute(
        text(
            """
            SELECT binding_id,
                   symbol,
                   status,
                   ownership_code,
                   broker_code,
                   owned_quantity,
                   meta_json
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
              AND meta_json ? 'auto_residual_truth'
            ORDER BY binding_id
            """
        ),
        {"uba": int(user_broker_account_id)},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        meta = r["meta_json"] if isinstance(r["meta_json"], dict) else {}
        truth = meta.get("auto_residual_truth")
        if not isinstance(truth, dict):
            continue
        out.append(
            {
                "binding_id": int(r["binding_id"]),
                "symbol": str(r["symbol"]),
                "status": str(r["status"]),
                "ownership_code": str(r["ownership_code"] or ""),
                "broker_code": str(r["broker_code"] or "UPBIT"),
                "owned_quantity": _dec(r["owned_quantity"]),
                "truth": dict(truth),
            }
        )
    return out


def _recovery_conflict_count(session: Session, uba_id: int) -> int:
    try:
        row = session.execute(
            text(
                """
                SELECT COUNT(*) AS c
                FROM trading.recovery_conflict
                WHERE user_broker_account_id = :uba
                  AND UPPER(status) IN ('OPEN','ACTIVE','PENDING','MANUAL_REVIEW')
                """
            ),
            {"uba": int(uba_id)},
        ).mappings().first()
        return int(row["c"] if row else 0)
    except Exception:  # noqa: BLE001
        session.rollback()
        return 0


def _ambiguous_order_count(session: Session, uba_id: int) -> int:
    try:
        row = session.execute(
            text(
                """
                SELECT COUNT(*) AS c
                FROM trading.trading_order
                WHERE user_broker_account_id = :uba
                  AND UPPER(COALESCE(status_code,'')) IN ('AMBIGUOUS','MANUAL_REVIEW')
                """
            ),
            {"uba": int(uba_id)},
        ).mappings().first()
        return int(row["c"] if row else 0)
    except Exception:  # noqa: BLE001
        session.rollback()
        return 0


def _unresolved_exit_count(session: Session, uba_id: int) -> int:
    try:
        row = session.execute(
            text(
                """
                SELECT COUNT(*) AS c
                FROM operation.strategy_position_binding
                WHERE user_broker_account_id = :uba
                  AND UPPER(status) IN ('EXIT_PENDING','UNRESOLVED_EXIT')
                """
            ),
            {"uba": int(uba_id)},
        ).mappings().first()
        return int(row["c"] if row else 0)
    except Exception:  # noqa: BLE001
        session.rollback()
        return 0


def preview_uba_residual_cleanup(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_balances: dict[str, Decimal],
    mark_prices: dict[str, Decimal],
    allowed_uba_ids: frozenset[int] | None = None,
) -> dict[str, Any]:
    """UBA 단위 PREVIEW — broker_submit=false · status mutation 없음.

    broker_balances / mark_prices 는 호출측이 fresh READ로 채운다.
    """

    uba = int(user_broker_account_id)
    allowed = allowed_uba_ids or frozenset({1380})
    kill_active = KillSwitchService(session).is_active_for_scopes(
        [uba_kill_switch_scope(uba), KillSwitchService.GLOBAL_SCOPE]
    )
    recovery_n = _recovery_conflict_count(session, uba)
    ambiguous_n = _ambiguous_order_count(session, uba)
    unresolved_n = _unresolved_exit_count(session, uba)

    bindings = load_binding_truth_rows(session, user_broker_account_id=uba)

    # same-symbol CURRENT residual qty sum (historical-only 제외)
    current_by_symbol: dict[str, Decimal] = {}
    for b in bindings:
        kind = str(b["truth"].get("kind") or "").upper()
        if kind in ALLOWED_CLEANUP_KINDS:
            from stock_platform.operation.upbit_auto_residual_cleanup.quantity import (
                provenance_current_qty,
            )

            current_by_symbol[b["symbol"]] = current_by_symbol.get(
                b["symbol"], ZERO
            ) + provenance_current_qty(b["truth"])

    previews: list[dict[str, Any]] = []
    historical_blocked: list[int] = []

    for b in bindings:
        truth = b["truth"]
        kind = str(truth.get("kind") or "").upper()
        sym = b["symbol"]
        currency = symbol_currency(sym)
        broker_qty = _dec(broker_balances.get(currency) or broker_balances.get(sym) or 0)
        mark = mark_prices.get(sym) or mark_prices.get(currency)

        if kind == KIND_HISTORICAL_ONLY:
            historical_blocked.append(b["binding_id"])

        # 이 binding 외 동일 심볼 CURRENT qty — double-count 방지용 차감
        from stock_platform.operation.upbit_auto_residual_cleanup.quantity import (
            provenance_current_qty,
        )

        own_prov = provenance_current_qty(truth)
        other_current = max(ZERO, current_by_symbol.get(sym, ZERO) - own_prov)

        pending_sell = load_pending_sell_quantity(
            session,
            symbol=sym,
            user_broker_account_id=uba,
            paper_account_id=None,
            broker_code="UPBIT",
        )

        manual_contamination = currency in MANUAL_PROTECTED_CURRENCIES
        # 동일 심볼 broker > (모든 current residual 합) 이면 초과분은 manual 가능
        if (
            not manual_contamination
            and kind in ALLOWED_CLEANUP_KINDS
            and broker_qty > current_by_symbol.get(sym, ZERO) + Decimal("0.00000001")
        ):
            # 초과분 존재 — 이 경로에서는 contamination 플래그로 차단하지 않고
            # quantity 쪽에서 provenance cap 으로만 제한 (manual 전량 SELL 금지)
            manual_contamination = False

        ctx = ResidualCleanupContext(
            uba_id=uba,
            binding_id=b["binding_id"],
            broker_code=b["broker_code"] or "UPBIT",
            symbol=sym,
            binding_status=b["status"],
            ownership_code=b["ownership_code"],
            truth=truth,
            broker_qty=broker_qty,
            mark_price=Decimal(str(mark)) if mark is not None else None,
            kill_switch_active=bool(kill_active),
            has_ambiguous_order=ambiguous_n > 0,
            has_unresolved_exit=unresolved_n > 0,
            has_recovery_conflict=recovery_n > 0,
            broker_account_ready=True,
            credential_ready=True,
            existing_open_sell_qty=pending_sell,
            existing_cleanup_request_status=None,
            manual_contamination=manual_contamination,
            ownership_confidence="HIGH",
            same_symbol_other_current_qty=other_current,
            allowed_uba_ids=allowed,
        )
        result = preview_cleanup(ctx)
        previews.append(
            {
                "binding_id": b["binding_id"],
                "symbol": sym,
                "binding_status": b["status"],
                "kind": kind,
                "preview": result.as_dict(),
            }
        )

    return {
        "user_broker_account_id": uba,
        "architecture": dict(ARCHITECTURE),
        "gates": {
            "kill_switch_active": bool(kill_active),
            "recovery_conflict_count": recovery_n,
            "ambiguous_order_count": ambiguous_n,
            "unresolved_exit_count": unresolved_n,
        },
        "historical_only_blocked": historical_blocked,
        "previews": previews,
        "broker_submit": False,
    }
