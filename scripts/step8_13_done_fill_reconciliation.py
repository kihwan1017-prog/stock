"""STEP 8-13 — DONE 20건 Historical Fill Reconciliation (조회·분석 전용).

금지: Import / Ignore / Pause Resume / LIVE / ARM / create·cancel·replace / DB UPDATE
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from stock_platform.broker import recovery_entities as _recovery_entities  # noqa: F401
from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_private_client_for_uba,
    build_upbit_settings_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.json_safe import to_jsonable
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.daily_loss_entities import AccountDailyLossEntity
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution
from stock_platform.trading.step8_12a2_cancel_guard import (
    STEP8_12A2_DONE_ALLOWLIST,
)
from stock_platform.trading.step8_13_done_fill_classifier import (
    classify_done_fill,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
REPORT_DIR = Path(r"E:\StockTrading\reports")
DONE_IDS = sorted(STEP8_12A2_DONE_ALLOWLIST)


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _mask(uuid_value: str | None) -> str:
    text = str(uuid_value or "").strip()
    if len(text) <= 8:
        return "****"
    return text[:4] + "…" + text[-4:]


def _base_currency(market: str | None) -> str:
    text = str(market or "")
    if "-" in text:
        return text.split("-", 1)[1]
    return text


def main() -> int:
    session = get_session_factory()()
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "step": "8-13",
        "checked_at": now.isoformat(),
        "mutation_executed": False,
        "create_order_calls": 0,
        "cancel_order_calls": 0,
        "replace_order_calls": 0,
        "approve_import_calls": 0,
        "ignore_calls": 0,
        "pause_resume_calls": 0,
        "done_ids": DONE_IDS,
    }

    try:
        pause = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == UBA
            )
        )
        uba = session.get(UserBrokerAccount, UBA)
        report["account"] = {
            "trading_paused": bool(pause.trading_paused) if pause else False,
            "recovery_status": pause.recovery_status if pause else None,
            "last_error_code": pause.last_error_code if pause else None,
            "live_order_enabled": bool(uba.live_order_enabled) if uba else None,
            "live_armed": bool(uba.live_armed) if uba else None,
        }

        # Broker live balances
        private = build_upbit_private_client_for_uba(session, UBA)

        async def _accounts() -> list:
            return await private.list_accounts()

        broker_accounts = asyncio.run(_accounts())
        broker_bal: dict[str, dict[str, Any]] = {
            str(row.get("currency")): row
            for row in (broker_accounts or [])
            if isinstance(row, dict) and row.get("currency")
        }
        report["broker_balances"] = {
            k: {
                "balance": v.get("balance"),
                "locked": v.get("locked"),
                "avg_buy_price": v.get("avg_buy_price"),
            }
            for k, v in broker_bal.items()
            if k != "KRW" or _dec(v.get("balance")) > 0
        }

        # Internal ACTIVE position snapshot
        snap = session.scalar(
            select(BrokerAccountSnapshotEntity)
            .where(
                BrokerAccountSnapshotEntity.user_broker_account_id == UBA,
                BrokerAccountSnapshotEntity.snapshot_status == "ACTIVE",
            )
            .order_by(
                BrokerAccountSnapshotEntity.broker_account_snapshot_id.desc()
            )
            .limit(1)
        )
        positions = []
        if snap is not None:
            positions = list(
                session.scalars(
                    select(BrokerPositionSnapshotEntity).where(
                        BrokerPositionSnapshotEntity.user_broker_account_id
                        == UBA,
                        BrokerPositionSnapshotEntity.snapshot_status
                        == "ACTIVE",
                    )
                ).all()
            )
        pos_by_symbol: dict[str, BrokerPositionSnapshotEntity] = {
            str(p.symbol).upper(): p for p in positions
        }
        report["internal_snapshot"] = {
            "broker_account_snapshot_id": (
                int(snap.broker_account_snapshot_id) if snap else None
            ),
            "deposit_amount": str(snap.deposit_amount) if snap else None,
            "snapshot_time": (
                snap.snapshot_time.isoformat()
                if snap and snap.snapshot_time
                else None
            ),
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": str(p.quantity),
                    "available_quantity": str(p.available_quantity),
                    "average_purchase_price": str(p.average_purchase_price),
                }
                for p in positions
            ],
        }

        # Daily loss
        daily = session.scalar(
            select(AccountDailyLossEntity).where(
                AccountDailyLossEntity.user_broker_account_id == UBA
            )
        )
        report["daily_loss"] = None
        if daily is not None:
            report["daily_loss"] = {
                "realized_profit_loss": str(
                    getattr(daily, "realized_profit_loss", None)
                ),
                "unrealized_profit_loss": str(
                    getattr(daily, "unrealized_profit_loss", None)
                ),
                "loss_limit": str(getattr(daily, "loss_limit", None)),
            }

        # Order client for remote order+trades
        resolved = BrokerCredentialVaultService(session).resolve_for_runtime(
            UBA,
            expected_broker="UPBIT",
            require_verified=True,
            touch_last_used=False,
        )
        order_client = UpbitOrderRestClient(
            settings=build_upbit_settings_from_vault(resolved),
            user_broker_account_id=UBA,
        )

        rows: list[dict[str, Any]] = []
        class_counts: Counter[str] = Counter()
        rec_counts: Counter[str] = Counter()
        impact_counts = Counter()

        for cid in DONE_IDS:
            conflict = session.get(BrokerRecoveryConflictEntity, cid)
            if conflict is None:
                rows.append(
                    {
                        "conflict_id": cid,
                        "error": "conflict_not_found",
                        "classification": "UNSAFE",
                        "recommendation": "MANUAL_REVIEW",
                    }
                )
                class_counts["UNSAFE"] += 1
                rec_counts["MANUAL_REVIEW"] += 1
                continue

            remote = order_client.get_order(
                uuid=str(conflict.external_order_id)
            )
            trades_raw = remote.get("trades")
            trades: list[dict[str, Any]] = []
            if isinstance(trades_raw, list):
                for trade in trades_raw:
                    if not isinstance(trade, dict):
                        continue
                    trades.append(
                        {
                            "trade_uuid_masked": _mask(trade.get("uuid")),
                            "trade_uuid_len": len(str(trade.get("uuid") or "")),
                            "trade_price": str(trade.get("price")),
                            "trade_volume": str(trade.get("volume")),
                            "trade_funds": str(trade.get("funds")),
                            "trade_fee": str(
                                trade.get("fee")
                                if trade.get("fee") is not None
                                else remote.get("paid_fee")
                            ),
                            "executed_at": trade.get("created_at"),
                            "side": trade.get("side"),
                        }
                    )

            market = str(
                remote.get("market") or conflict.market_code or ""
            )
            base = _base_currency(market)
            # Upbit 심볼은 BTC / KRW-BTC 혼재 가능
            pos = (
                pos_by_symbol.get(base.upper())
                or pos_by_symbol.get(market.upper())
                or pos_by_symbol.get(f"KRW-{base}".upper())
            )
            bal = broker_bal.get(base) or {}
            broker_qty = _dec(bal.get("balance")) + _dec(bal.get("locked"))
            internal_qty = _dec(pos.quantity) if pos is not None else None
            position_known = pos is not None or base in broker_bal
            # 잔고 0이고 포지션 행 없음 = 일치(둘 다 없음)
            if pos is None and base in broker_bal and broker_qty == 0:
                position_matches = True
                internal_qty = Decimal("0")
            elif pos is None and base not in broker_bal:
                position_matches = True  # broker에 currency 없음 = 0
                internal_qty = Decimal("0")
                broker_qty = Decimal("0")
            elif pos is not None and base in broker_bal:
                position_matches = abs(internal_qty - broker_qty) <= Decimal(
                    "1e-8"
                )
            elif pos is not None and base not in broker_bal:
                position_matches = _dec(pos.quantity) == 0
            else:
                position_matches = False

            # Internal order by broker uuid
            order = session.scalar(
                select(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id == UBA,
                    TradingOrderEntity.broker_order_id
                    == str(conflict.external_order_id),
                )
                .limit(1)
            )
            if order is None and conflict.linked_internal_order_id:
                order = session.get(
                    TradingOrderEntity,
                    int(conflict.linked_internal_order_id),
                )

            executions: list[TradingExecution] = []
            if order is not None:
                executions = list(
                    session.scalars(
                        select(TradingExecution).where(
                            TradingExecution.order_id == int(order.order_id)
                        )
                    ).all()
                )
            # broker_order_id로도 조회
            if not executions:
                executions = list(
                    session.scalars(
                        select(TradingExecution).where(
                            TradingExecution.broker_order_id
                            == str(conflict.external_order_id)
                        )
                    ).all()
                )

            exec_qty_sum = sum(
                (_dec(e.execution_quantity) for e in executions),
                Decimal("0"),
            )
            remote_exec = _dec(remote.get("executed_volume"))
            qty_match = bool(executions) and abs(
                exec_qty_sum - remote_exec
            ) <= Decimal("1e-8")

            # Audit 연결 (JSONB path 실패 시 최근 이벤트로 폴백)
            audit_count = 0
            try:
                recent = session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.event_type.like("RECOVERY_CONFLICT%")
                    )
                    .order_by(AuditEvent.audit_event_id.desc())
                    .limit(300)
                ).all()
                audit_count = sum(
                    1
                    for a in recent
                    if isinstance(a.detail, dict)
                    and a.detail.get("conflict_id") == cid
                )
            except Exception:  # noqa: BLE001
                audit_count = 0

            verdict = classify_done_fill(
                conflict_id=cid,
                executed_volume=remote.get("executed_volume"),
                trades_count=int(remote.get("trades_count") or len(trades)),
                has_internal_order=order is not None,
                has_internal_execution=len(executions) > 0,
                execution_qty_matches_trades=qty_match,
                broker_balance_known=True,
                internal_position_known=True,
                position_matches_broker=position_matches,
                snapshot_synced_from_broker=snap is not None,
                remote_status=str(remote.get("state") or ""),
            )
            class_counts[verdict.classification] += 1
            rec_counts[verdict.recommendation] += 1
            for key, flag in verdict.impact.to_dict().items():
                if flag:
                    impact_counts[key] += 1

            rows.append(
                {
                    "conflict_id": cid,
                    "market": market,
                    "side": remote.get("side") or conflict.side_code,
                    "broker_uuid_masked": _mask(conflict.external_order_id),
                    "created_at": remote.get("created_at"),
                    "done_at": remote.get("created_at"),
                    "order_type": remote.get("ord_type")
                    or conflict.order_type_code,
                    "requested_price": str(remote.get("price")),
                    "requested_volume": str(remote.get("volume")),
                    "executed_volume": str(remote.get("executed_volume")),
                    "remaining_volume": str(remote.get("remaining_volume")),
                    "paid_fee": str(remote.get("paid_fee")),
                    "trades_count": remote.get("trades_count"),
                    "trades": trades,
                    "internal": {
                        "order_exists": order is not None,
                        "order_id": int(order.order_id) if order else None,
                        "order_status": (
                            order.status_code if order else None
                        ),
                        "order_filled_quantity": (
                            str(order.filled_quantity) if order else None
                        ),
                        "execution_count": len(executions),
                        "execution_qty_sum": str(exec_qty_sum),
                        "execution_qty_matches": qty_match,
                        "strategy_code": (
                            order.strategy_code if order else None
                        ),
                        "portfolio_id": (
                            int(order.portfolio_id)
                            if order and order.portfolio_id
                            else None
                        ),
                        "position_id": (
                            int(order.position_id)
                            if order and order.position_id
                            else None
                        ),
                    },
                    "position_balance": {
                        "currency": base,
                        "broker_balance": str(bal.get("balance")),
                        "broker_locked": str(bal.get("locked")),
                        "broker_qty_total": str(broker_qty),
                        "broker_avg_buy_price": str(
                            bal.get("avg_buy_price")
                        ),
                        "internal_qty": (
                            str(internal_qty)
                            if internal_qty is not None
                            else None
                        ),
                        "internal_avg_purchase_price": (
                            str(pos.average_purchase_price)
                            if pos is not None
                            else None
                        ),
                        "position_matches_broker": position_matches,
                    },
                    "links": {
                        "audit_events_for_conflict": audit_count,
                        "runtime": "N/A_READ_ONLY",
                        "daily_loss_row_present": daily is not None,
                    },
                    "classification": verdict.classification,
                    "recommendation": verdict.recommendation,
                    "impact": verdict.impact.to_dict(),
                    "notes": verdict.notes,
                    "review_status_unchanged": conflict.review_status,
                }
            )

        report["rows"] = rows
        report["class_counts"] = dict(class_counts)
        report["recommendation_counts"] = dict(rec_counts)
        report["impact_counts"] = dict(impact_counts)

        # Scheduler readiness (read-only)
        try:
            readiness = collect_scheduler_readiness(session)
            report["scheduler"] = (
                readiness.to_dict()
                if hasattr(readiness, "to_dict")
                else str(readiness)
            )
        except Exception as exc:  # noqa: BLE001
            report["scheduler_error"] = str(exc)

        # Pause 해제 가능? — DONE unresolved 남아 있으면 불가
        unresolved = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == UBA,
                    BrokerRecoveryConflictEntity.review_status.in_(
                        ["PENDING_REVIEW", "ON_HOLD"]
                    ),
                )
            )
            or 0
        )
        report["unresolved_conflicts"] = unresolved
        all_safe_ignore = (
            rec_counts.get("SAFE_IGNORE", 0) == len(DONE_IDS)
            and class_counts.get("UNSAFE", 0) == 0
            and class_counts.get("IMPORT_REQUIRED", 0) == 0
        )
        # SAFE_IGNORE만이어도 Conflict 미해결이면 Pause resume은 별도 STEP
        report["pause_resume_allowed_now"] = False
        report["pause_resume_reason"] = (
            "DONE conflicts still PENDING_REVIEW; "
            "8-13 is analysis-only (Ignore/Import forbidden)"
        )
        report["release_blocker"] = (
            f"unresolved_done_conflicts={unresolved}"
        )
        report["analysis_suggests_all_safe_ignore"] = all_safe_ignore

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / "step8_13_done_fill_reconciliation.json"
        path.write_text(
            json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"WROTE {path}")
        print(
            json.dumps(
                {
                    "done_total": len(DONE_IDS),
                    "class_counts": report["class_counts"],
                    "recommendation_counts": report[
                        "recommendation_counts"
                    ],
                    "impact_counts": report["impact_counts"],
                    "unresolved": unresolved,
                    "pause": report["account"],
                    "mutations": {
                        "import": 0,
                        "ignore": 0,
                        "resume": 0,
                        "orders": 0,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        report["error"] = str(exc)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "step8_13_done_fill_reconciliation.json").write_text(
            json.dumps(to_jsonable(report), default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
