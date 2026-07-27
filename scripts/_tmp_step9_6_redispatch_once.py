"""STEP 9-6 — 동일 주문(#250) Outbox 1회 재디스패치 (브로커 미도달 KeyError 복구).

신규 create_order / 재주문 금지. 동일 outbox·order만 PENDING 복구 후 run_once 1회.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dataclasses import replace
from sqlalchemy import func, select

from stock_platform.auth import models as _auth_models  # noqa: F401
from stock_platform.broker import recovery_entities as _recovery_entities  # noqa: F401
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
    build_upbit_private_client_for_uba,
)
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.risk_engine import resolved_policy as resolved_mod
from stock_platform.risk_engine import runtime as risk_runtime
from stock_platform.strategy_deployment import (  # noqa: F401
    definition_entities as _strategy_entities,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution

ORDER_ID = 250
OUTBOX_ID = 156
UBA = 58
REPORT = Path(r"E:\StockTrading\reports\step9_6_market_buy.json")
PREV = Path(r"E:\StockTrading\reports\step9_6_market_buy.json")


def _balances(session) -> dict[str, str]:
    client = build_upbit_private_client_for_uba(session, UBA)
    rows = asyncio.run(client.list_accounts())
    out = {"KRW": "0", "BTC": "0"}
    for row in rows or []:
        cur = str(row.get("currency") or "").upper()
        if cur in out:
            bal = Decimal(str(row.get("balance") or "0"))
            locked = Decimal(str(row.get("locked") or "0"))
            out[cur] = str(bal + locked)
    return out


def main() -> None:
    clear_settings_cache()
    settings = get_settings()
    if not (
        settings.global_live_order_enabled and settings.upbit_live_order_enabled
    ):
        raise SystemExit("LIVE_FLAGS_OFF")

    # 투자비중 게이트 — 동일 STEP 완화 유지
    new_policy = replace(
        risk_runtime.realtime_risk_policy,
        max_investment_ratio=Decimal("1.0"),
    )
    risk_runtime.realtime_risk_policy = new_policy
    resolved_mod.realtime_risk_policy = new_policy

    sf = get_session_factory()
    prev: dict[str, Any] = {}
    if PREV.exists():
        prev = json.loads(PREV.read_text(encoding="utf-8"))

    with sf() as session:
        order = session.get(TradingOrderEntity, ORDER_ID)
        outbox = session.get(OrderOutbox, OUTBOX_ID)
        if order is None or outbox is None:
            raise SystemExit("ORDER_OR_OUTBOX_MISSING")
        if order.user_broker_account_id != UBA:
            raise SystemExit("UBA_MISMATCH")
        if order.broker_order_id:
            raise SystemExit("ALREADY_HAS_BROKER_ID")

        balances_before = _balances(session)
        payload = dict(outbox.payload_json or {})
        payload["order_id"] = ORDER_ID
        outbox.payload_json = payload
        outbox.status_code = OutboxStatus.PENDING.value
        outbox.retry_count = 0
        outbox.max_retry_count = 0  # 추가 자동 retry 없음
        outbox.last_error = None
        outbox.next_retry_at = None
        outbox.locked_by = None
        outbox.locked_at = None
        outbox.dispatch_intent_at = None

        # FAILED → PENDING 복구 (동일 주문 1건 완료용)
        order.status_code = OrderStatus.PENDING.value
        session.commit()

    worker = OrderOutboxWorker(
        session_factory=sf,
        dispatcher=OrderOutboxDispatcher(),
        worker_id="step9-6-redispatch-once",
        batch_size=5,
    )
    summary = worker.run_once()

    report = dict(prev)
    report["redispatch"] = {
        "order_id": ORDER_ID,
        "outbox_id": OUTBOX_ID,
        "reason": "payload_missing_order_id_before_broker",
        "outbox_run_once": {
            "claimed": summary.claimed,
            "succeeded": summary.succeeded,
            "retried": summary.retried,
            "failed": summary.failed,
            "ambiguous": summary.ambiguous,
        },
        "balances_before_redispatch": balances_before,
        "at": datetime.now(timezone.utc).isoformat(),
    }

    with sf() as session:
        order = session.get(TradingOrderEntity, ORDER_ID)
        outbox = session.get(OrderOutbox, OUTBOX_ID)
        report["outbox_after"] = {
            "status": outbox.status_code if outbox else None,
            "retry_count": outbox.retry_count if outbox else None,
            "max_retry_count": outbox.max_retry_count if outbox else None,
            "last_error": ((outbox.last_error or "")[:500] if outbox else None),
        }
        if order is not None:
            report["db_order"] = {
                "order_id": order.order_id,
                "client_order_id": order.client_order_id,
                "broker_order_id": order.broker_order_id,
                "status": order.status_code,
                "quantity": str(order.order_quantity),
                "price": str(order.order_price)
                if order.order_price is not None
                else None,
                "identifier": getattr(order, "upbit_client_identifier", None),
                "submitted_at": str(
                    getattr(order, "first_submitted_at", None)
                    or getattr(order, "created_at", None)
                ),
            }
            report["execution_rows"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(TradingExecution)
                    .where(TradingExecution.order_id == ORDER_ID)
                )
                or 0
            )

        broker_uuid = (report.get("db_order") or {}).get("broker_order_id")
        if broker_uuid:
            try:
                adapter = build_upbit_adapter_for_uba(session, UBA)
                payload = adapter._client.get_order(uuid=str(broker_uuid))
                report["broker_order"] = {
                    "uuid": payload.get("uuid"),
                    "identifier": payload.get("identifier"),
                    "state": payload.get("state"),
                    "side": payload.get("side"),
                    "ord_type": payload.get("ord_type"),
                    "price": payload.get("price"),
                    "avg_price": payload.get("avg_price")
                    or payload.get("avg_fill_price"),
                    "executed_volume": payload.get("executed_volume"),
                    "remaining_volume": payload.get("remaining_volume"),
                    "paid_fee": payload.get("paid_fee"),
                    "created_at": payload.get("created_at"),
                    "market": payload.get("market"),
                }
            except Exception as exc:  # noqa: BLE001
                report["broker_order_error"] = f"{type(exc).__name__}:{exc}"[:300]

        report["balances_after"] = _balances(session)
        uba = session.get(UserBrokerAccount, UBA)
        report["live_after"] = bool(uba.live_order_enabled) if uba else None
        report["arm_after"] = bool(uba.live_armed) if uba else None
        report["arm_expires_at"] = str(uba.arm_expires_at) if uba else None
        report["actual_order_count"] = int(
            session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(TradingOrderEntity.user_broker_account_id == UBA)
            )
            or 0
        )

    broker_uuid = (report.get("db_order") or {}).get("broker_order_id")
    if summary.succeeded and broker_uuid:
        report["final_verdict"] = "PASS_ORDER_SUBMITTED"
    else:
        report["final_verdict"] = "FAIL_OUTBOX_OR_BROKER"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    REPORT.write_text(
        json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("REPORT", REPORT)
    print("VERDICT", report["final_verdict"])
    print("BROKER_UUID", broker_uuid)
    print("OUTBOX", report["redispatch"]["outbox_run_once"])
    print("ORDER_STATUS", (report.get("db_order") or {}).get("status"))


if __name__ == "__main__":
    main()
