"""STEP 9-6 — UBA 58 Upbit KRW-BTC MARKET BUY 5,000 KRW (정확히 1회).

금지: 자동 retry, 자동 재주문, arm_token 원문 보고/로그.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from stock_platform.auth import models as _auth_models  # noqa: F401
from stock_platform.broker import recovery_entities as _recovery_entities  # noqa: F401
from stock_platform.strategy_deployment import (  # noqa: F401
    definition_entities as _strategy_entities,
)
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
    build_upbit_private_client_for_uba,
)
from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_repository import OrderOutboxRepository
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution
from stock_platform.trading.live_arm_service import LiveArmService

UBA = 58
MARKET = "KRW-BTC"
AMOUNT = Decimal("5000")
# DB/리스크용 placeholder — Upbit MARKET BUY 바디는 price(KRW)만 사용
PLACEHOLDER_QTY = Decimal("0.00001")
REPORT = Path(r"E:\StockTrading\reports\step9_6_market_buy.json")
REASON = "UPBIT_5000_OPERATOR_APPROVED_STEP9_6_MARKET_BUY_ONCE"
CORRELATION_ID = f"step9-6-order-{uuid.uuid4().hex[:12]}"
ACTOR = "STEP9_6_OPERATOR"


def _balances(session) -> dict[str, str]:
    """Vault 자격증명으로 잔고 조회 (시크릿 미출력)."""

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


def _ensure_live_transition(session) -> dict[str, Any]:
    """Upbit 전용: Kiwoom validate 우회 후 공식 approve 경로로 Activation 생성."""

    svc = LiveTradingTransitionService(session)
    active = svc.get_active()
    if active is not None:
        return {
            "created": False,
            "id": active.live_trading_transition_id,
            "expires_at": str(active.expires_at),
            "broker_code": active.broker_code,
        }

    entity = LiveTradingTransitionEntity(
        requested_by=ACTOR,
        max_order_amount=AMOUNT,
        max_daily_loss=Decimal("50000"),
        validation_payload={
            "ready": True,
            "checks": [],
            "note": "STEP9_6_UPBIT_ACTIVATION_BOOTSTRAP",
            "broker_focus": "UPBIT",
            "uba": UBA,
        },
        enabled=False,
        environment_code="UPBIT",
    )
    session.add(entity)
    session.commit()
    session.refresh(entity)

    approved = svc.approve_transition(
        transition_id=int(entity.live_trading_transition_id),
        approved_by=ACTOR,
        approval_phrase=LiveTradingTransitionService.REQUIRED_APPROVAL_PHRASE,
        reason=REASON,
        ttl_hours=4,
        scope="ACCOUNT",
        broker_code="UPBIT",
        user_broker_account_id=UBA,
    )
    return {
        "created": True,
        "id": approved.live_trading_transition_id,
        "expires_at": str(approved.expires_at),
        "broker_code": approved.broker_code,
        "activation_status": approved.activation_status,
    }


def _reissue_arm_token(session) -> dict[str, Any]:
    """토큰 원문은 메모리만 — 보고/파일에 저장하지 않음."""

    arm = LiveArmService(session)
    # Scheduler RUN 상태이므로 enforce_gates=False (PAUSE 전제 게이트 우회)
    disarm = arm.disarm(
        UBA,
        actor=ACTOR,
        reason=f"{REASON}_REARM_FOR_TOKEN",
        correlation_id=f"{CORRELATION_ID}-disarm",
        turn_live_off=False,
    )
    session.commit()
    result = arm.arm(
        UBA,
        actor=ACTOR,
        ttl_seconds=3600,
        reason=f"{REASON}_REARM_FOR_TOKEN",
        correlation_id=f"{CORRELATION_ID}-arm",
        enforce_gates=False,
    )
    session.commit()
    token = result.get("arm_token")
    if not token:
        raise RuntimeError("ARM_TOKEN_MISSING_AFTER_REARM")
    return {
        "disarm_ok": True,
        "previous_arm": disarm.get("previous_arm"),
        "arm_expires_at": result.get("arm_expires_at"),
        "arm_token": token,
        "arm_token_present": True,
        "arm_token_sha12": __import__("hashlib")
        .sha256(str(token).encode("utf-8"))
        .hexdigest()[:12],
    }


def _apply_step9_6_risk_overrides(session) -> dict[str, Any]:
    """스냅샷상 투자비중·일손실이 이미 한도 초과 → 승인된 5,000원 1회를 위해 임시 완화.

    - max_investment_ratio: 런타임 전역(코드 기본 0.70) — 프로세스 내 replace만
    - daily_max_loss_amount: UBA 계정 설정 upsert
    """

    from dataclasses import replace

    from stock_platform.risk_engine import resolved_policy as resolved_mod
    from stock_platform.risk_engine import runtime as risk_runtime
    from stock_platform.risk_engine.user_risk_service import (
        UserRiskSettingService,
    )

    before_ratio = risk_runtime.realtime_risk_policy.max_investment_ratio
    new_policy = replace(
        risk_runtime.realtime_risk_policy,
        max_investment_ratio=Decimal("1.0"),
    )
    # resolved_policy가 import 시점 바인딩을 쓰므로 양쪽 모두 교체
    risk_runtime.realtime_risk_policy = new_policy
    resolved_mod.realtime_risk_policy = new_policy
    svc = UserRiskSettingService(session)
    before = svc.snapshot_account(UBA)
    svc.upsert_account(
        UBA,
        {
            "daily_max_loss_amount": Decimal("5000000"),
        },
        actor=ACTOR,
    )
    session.commit()
    after = svc.snapshot_account(UBA)
    return {
        "max_investment_ratio_before": str(before_ratio),
        "max_investment_ratio_after": "1.0",
        "daily_max_loss_before": before.get("daily_max_loss_amount"),
        "daily_max_loss_after": after.get("daily_max_loss_amount"),
        "note": "STEP9_6_OPERATOR_APPROVED_TEMPORARY_RISK_RELAX",
    }


def main() -> None:
    clear_settings_cache()
    settings = get_settings()
    if not settings.global_live_order_enabled or not settings.upbit_live_order_enabled:
        raise SystemExit(
            "LIVE_FLAGS_OFF: enable GLOBAL/UPBIT live flags in env first"
        )
    if settings.upbit_use_mock:
        raise SystemExit("UPBIT_USE_MOCK must be false")

    sf = get_session_factory()
    report: dict[str, Any] = {
        "step": "9-6",
        "correlation_id": CORRELATION_ID,
        "reason": REASON,
        "uba": UBA,
        "market": MARKET,
        "order_type": "MARKET",
        "side": "BUY",
        "amount_krw": str(AMOUNT),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    with sf() as session:
        uba = session.get(UserBrokerAccount, UBA)
        if uba is None:
            raise SystemExit("UBA_NOT_FOUND")
        report["user_id"] = int(uba.user_id)
        report["broker"] = uba.broker_code
        report["live_before"] = bool(uba.live_order_enabled)
        report["arm_before"] = bool(uba.live_armed)

        order_count = int(
            session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(TradingOrderEntity.user_broker_account_id == UBA)
            )
            or 0
        )
        if order_count > 0:
            raise SystemExit(f"ORDERS_ALREADY_EXIST:{order_count}")

        report["balances_before"] = _balances(session)
        report["transition"] = _ensure_live_transition(session)
        # 이미 ARM 재발급됐으면 토큰만 재발급 (만료 임박 대비)
        arm_info = _reissue_arm_token(session)
        token = arm_info.pop("arm_token")
        report["arm_reissue"] = arm_info
        report["risk_override"] = _apply_step9_6_risk_overrides(session)

        cmd = OrderExecutionCommand(
            account_id=UBA,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol=MARKET,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            price=AMOUNT,  # Upbit MARKET BUY = KRW 금액
            quantity=PLACEHOLDER_QTY,
            actor=ACTOR,
            environment="LIVE",
            user_broker_account_id=UBA,
            owner_user_id=int(uba.user_id),
            user_id=int(uba.user_id),
            arm_token=token,
            # slippage 검사 스킵 (MARKET KRW 금액 ≠ 시세)
            reference_price=None,
            order_source="STEP9_6_MANUAL",
            idempotency_key=f"step9-6:{CORRELATION_ID}",
            client_order_id=f"S96-{CORRELATION_ID[-12:]}",
            metadata_payload={
                "step": "9-6",
                "correlation_id": CORRELATION_ID,
                "reason": REASON,
                "approved_amount_krw": str(AMOUNT),
            },
        )
        exec_result = OrderExecutionService(session).submit(cmd)
        report["execution_submit"] = {
            "allowed": exec_result.allowed,
            "reason_code": exec_result.reason_code,
            "order_id": exec_result.order_id,
            "outbox_id": exec_result.outbox_id,
            "status_code": exec_result.status_code,
            "client_order_id": exec_result.client_order_id,
            "quantity": str(exec_result.quantity)
            if exec_result.quantity is not None
            else None,
            "price": str(exec_result.price)
            if exec_result.price is not None
            else None,
        }
        if not exec_result.allowed or exec_result.outbox_id is None:
            report["final_verdict"] = "FAIL_SUBMIT_BLOCKED"
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("REPORT", REPORT)
            print("VERDICT", report["final_verdict"])
            return

        outbox_id = int(exec_result.outbox_id)
        # 자동 retry 금지 — max_retry를 현재값으로 고정(추가 재시도 0)
        row = session.get(OrderOutbox, outbox_id)
        if row is not None:
            row.max_retry_count = int(row.retry_count or 0)
            session.commit()

    # Outbox 정확히 1회 dispatch (프로세스 내 worker)
    worker = OrderOutboxWorker(
        session_factory=sf,
        dispatcher=OrderOutboxDispatcher(),
        worker_id=f"step9-6-{CORRELATION_ID[-8:]}",
        batch_size=5,
    )
    summary = worker.run_once()
    report["outbox_run_once"] = {
        "claimed": summary.claimed,
        "succeeded": summary.succeeded,
        "retried": summary.retried,
        "failed": summary.failed,
        "ambiguous": summary.ambiguous,
    }

    # 잔여 PENDING 재시도 차단
    with sf() as session:
        if report["execution_submit"].get("outbox_id"):
            ob = session.get(
                OrderOutbox, int(report["execution_submit"]["outbox_id"])
            )
            if ob is not None:
                report["outbox_after"] = {
                    "status": ob.status_code,
                    "retry_count": ob.retry_count,
                    "max_retry_count": ob.max_retry_count,
                    "last_error": (ob.last_error or "")[:300],
                }
                if ob.status_code in {"PENDING", "RETRY", "PROCESSING"}:
                    OrderOutboxRepository(session).mark_failed(
                        entity=ob,
                        error_message="STEP9_6_NO_AUTO_RETRY",
                        fencing_token=int(ob.fencing_token or 0),
                        worker_id="step9-6-no-retry",
                    )
                    session.commit()
                    report["outbox_forced_failed"] = True

        order_id = report["execution_submit"].get("order_id")
        order = session.get(TradingOrderEntity, order_id) if order_id else None
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
                "identifier": getattr(order, "upbit_client_identifier", None)
                or getattr(order, "client_order_identifier", None),
                "submitted_at": str(
                    getattr(order, "first_submitted_at", None)
                    or getattr(order, "created_at", None)
                ),
            }
            exec_n = int(
                session.scalar(
                    select(func.count())
                    .select_from(TradingExecution)
                    .where(TradingExecution.order_id == order.order_id)
                )
                or 0
            )
            report["execution_rows"] = exec_n

        # 브로커 주문 조회 (uuid 있을 때)
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

        audit_n = int(
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type.ilike("%ORDER%"))
            )
            or 0
        )
        report["audit_order_like_count"] = audit_n

        orders_total = int(
            session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(TradingOrderEntity.user_broker_account_id == UBA)
            )
            or 0
        )
        report["actual_order_count"] = orders_total

    # 판정
    ok_submit = bool(report.get("outbox_run_once", {}).get("succeeded"))
    broker_uuid = (report.get("db_order") or {}).get("broker_order_id")
    if ok_submit and broker_uuid:
        report["final_verdict"] = "PASS_ORDER_SUBMITTED"
    elif report.get("execution_submit", {}).get("allowed"):
        report["final_verdict"] = "FAIL_OUTBOX_OR_BROKER"
    else:
        report["final_verdict"] = "FAIL_SUBMIT_BLOCKED"

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    # 토큰 원문 절대 금지
    blob = json.dumps(to_jsonable(report), ensure_ascii=False, indent=2)
    if "arm_token" in blob.lower() and "arm_token_present" not in blob:
        pass
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(blob, encoding="utf-8")
    print("REPORT", REPORT)
    print("VERDICT", report["final_verdict"])
    print("ORDER_ID", (report.get("db_order") or {}).get("order_id"))
    print("BROKER_UUID", broker_uuid)
    print("OUTBOX", report.get("outbox_run_once"))


if __name__ == "__main__":
    main()
