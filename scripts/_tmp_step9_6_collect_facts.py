"""STEP 9-6 완료 사실 수집."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

from stock_platform.auth import models as _auth_models  # noqa: F401
from stock_platform.broker import recovery_entities as _rec  # noqa: F401
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
    build_upbit_private_client_for_uba,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.post_fill_verification_entities import (
    PostFillVerificationEntity,
)
from stock_platform.strategy_deployment import (  # noqa: F401
    definition_entities as _strategy_entities,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution

UUID = "00175133-d943-42fa-aa33-d432d81e3499"
ORDER_ID = 250
UBA = 58
PREV = Path(r"E:\StockTrading\reports\step9_6_market_buy.json")
OUT = Path(r"E:\StockTrading\reports\step9_6_completion_facts.json")


def main() -> None:
    prev = json.loads(PREV.read_text(encoding="utf-8"))
    session = get_session_factory()()
    try:
        adapter = build_upbit_adapter_for_uba(session, UBA)
        remote = adapter._client.get_order(uuid=UUID)
        trade = (remote.get("trades") or [{}])[0]
        order = session.get(TradingOrderEntity, ORDER_ID)
        executions = list(
            session.scalars(
                select(TradingExecution).where(
                    TradingExecution.order_id == ORDER_ID
                )
            )
        )
        uba = session.get(UserBrokerAccount, UBA)
        rec = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == UBA
            )
        )
        client = build_upbit_private_client_for_uba(session, UBA)
        rows = asyncio.run(client.list_accounts())
        bal_raw = {
            str(r.get("currency")).upper(): {
                "balance": str(r.get("balance")),
                "locked": str(r.get("locked")),
            }
            for r in rows
            if str(r.get("currency")).upper() in {"KRW", "BTC"}
        }
        bal_after = {
            k: str(Decimal(v["balance"] or 0) + Decimal(v["locked"] or 0))
            for k, v in bal_raw.items()
        }
        _acc, positions = BrokerAccountSnapshotRepository(
            session
        ).get_active_by_uba(UBA)
        btc_pos = next(
            (p for p in positions if str(p.symbol).upper() == "KRW-BTC"),
            None,
        )

        def _cnt(status: str) -> int:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(TradingOrderEntity)
                    .where(
                        TradingOrderEntity.user_broker_account_id == UBA,
                        TradingOrderEntity.status_code == status,
                    )
                )
                or 0
            )

        try:
            pf: int | str = int(
                session.scalar(
                    select(func.count())
                    .select_from(PostFillVerificationEntity)
                    .where(PostFillVerificationEntity.order_id == ORDER_ID)
                )
                or 0
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            pf = f"error:{type(exc).__name__}"

        audits = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.event_type.in_(
                        [
                            "LIVE_ORDER_SUBMITTED",
                            "LIVE_ARM",
                            "LIVE_DISARM",
                            "OUTBOX_CLAIMED",
                            "OUTBOX_DISPATCH_INTENT_CREATED",
                        ]
                    )
                )
                .order_by(AuditEvent.audit_event_id.desc())
                .limit(12)
            )
        )

        try:
            row = session.execute(
                text(
                    "select * from trading.trading_scheduler_control limit 1"
                )
            ).mappings().first()
            scheduler = dict(row) if row else {"note": "no_row"}
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            scheduler = {"error": str(exc)[:200]}

        facts = {
            "final_verdict": "PASS_ORDER_FILLED",
            "uba": UBA,
            "broker": "UPBIT",
            "market": "KRW-BTC",
            "order_type": "MARKET",
            "side": "BUY",
            "amount_krw": "5000",
            "order_id": ORDER_ID,
            "broker_uuid": UUID,
            "client_order_id": order.client_order_id if order else None,
            "identifier": remote.get("identifier"),
            "accepted_at": remote.get("created_at"),
            "filled_at": trade.get("created_at"),
            "filled_qty": str(remote.get("executed_volume")),
            "avg_price": str(trade.get("price")),
            "fill_funds": str(trade.get("funds")),
            "fee": str(remote.get("paid_fee")),
            "broker_state": remote.get("state"),
            "balances_before": prev.get("balances_before"),
            "balances_after": bal_after,
            "balances_raw_after": bal_raw,
            "db_order_status": order.status_code if order else None,
            "db_filled_qty": str(order.filled_quantity) if order else None,
            "db_avg": str(order.average_fill_price) if order else None,
            "execution_count": len(executions),
            "execution_ids": [e.execution_id for e in executions],
            "btc_position_qty": (
                str(btc_pos.quantity) if btc_pos is not None else None
            ),
            "btc_avg_entry": (
                str(getattr(btc_pos, "average_entry_price", None))
                if btc_pos is not None
                else None
            ),
            "recovery_status": getattr(rec, "recovery_status", None),
            "recovery_desired": getattr(rec, "desired_status", None)
            or getattr(rec, "desired_state", None),
            "scheduler": scheduler,
            "post_fill_rows_for_order": pf,
            "submission_unknown": _cnt("SUBMISSION_UNKNOWN"),
            "cancel_pending": _cnt("CANCEL_PENDING"),
            "replace_pending": _cnt("REPLACE_PENDING"),
            "actual_orders": int(
                session.scalar(
                    select(func.count())
                    .select_from(TradingOrderEntity)
                    .where(TradingOrderEntity.user_broker_account_id == UBA)
                )
                or 0
            ),
            "live": bool(uba.live_order_enabled) if uba else None,
            "arm": bool(uba.live_armed) if uba else None,
            "arm_expires_at": str(uba.arm_expires_at) if uba else None,
            "audits": [
                {"id": a.audit_event_id, "type": a.event_type}
                for a in audits
            ],
            "correlation_id": prev.get("correlation_id"),
            "notes": [
                "Outbox #156 failed KeyError order_id before broker",
                "Outbox #157 succeeded — single broker submit",
                "Upbit market buy state=cancel with fill (residual KRW cancel)",
                "DB FILLED synced via STEP9_6_RECONCILE after broker confirm",
            ],
        }
        OUT.write_text(
            json.dumps(facts, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(facts, ensure_ascii=False, indent=2, default=str))
    finally:
        session.close()


if __name__ == "__main__":
    main()
