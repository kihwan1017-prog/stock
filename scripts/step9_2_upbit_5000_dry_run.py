"""STEP 9-2 — UPBIT 5,000원 Dry Run CLI (--market 필수).

금지: LIVE/ARM/Scheduler/실주문/DB trading_order insert
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from stock_platform.broker import recovery_entities as _  # noqa: F401
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
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.broker.recovery_entities import BrokerRecoveryRunEntity
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.api.deps_admin import AuditLogService
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution
from stock_platform.trading.step9_2_upbit_dry_run import (
    DEFAULT_SMOKE_AMOUNT,
    Step92UpbitDryRunService,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
BASE = "http://127.0.0.1:8000"
REPORT = Path(r"E:\StockTrading\reports\step9_2_upbit_5000_dry_run.json")


def _count_orders(session, uba_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(TradingOrderEntity.user_broker_account_id == int(uba_id))
        )
        or 0
    )


def _count_exec(session, uba_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(TradingExecution)
            .join(
                TradingOrderEntity,
                TradingOrderEntity.order_id == TradingExecution.order_id,
            )
            .where(
                TradingOrderEntity.user_broker_account_id == int(uba_id)
            )
        )
        or 0
    )


def _precheck(session, admin_key: str, market: str) -> dict[str, Any]:
    abort: list[str] = []
    uba = session.get(UserBrokerAccount, UBA)
    pause = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
        )
    )
    if uba is None or not uba.is_active:
        abort.append("uba_inactive")
    if pause and pause.trading_paused:
        abort.append("trading_paused")
    if uba and uba.live_order_enabled:
        abort.append("live_on")
    if uba and uba.live_armed:
        abort.append("arm_on")

    cred = BrokerCredentialVaultService(session).status(UBA).as_dict()
    if str(cred.get("verification_status") or "").upper() != "VERIFIED":
        abort.append("credential_not_verified")

    with httpx.Client(timeout=20.0) as http:
        sched = http.get(
            f"{BASE}/api/v1/admin/recovery/scheduler/status",
            headers={"X-Admin-API-Key": admin_key},
        )
        sched.raise_for_status()
        recovery = sched.json()
    if recovery.get("desired_state") != "RUNNING":
        abort.append("recovery_desired")
    if recovery.get("actual_state") not in {"RUNNING", "COOLDOWN"}:
        abort.append(f"recovery_actual={recovery.get('actual_state')}")
    if recovery.get("stale") is True:
        abort.append("recovery_stale")

    active = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.user_broker_account_id == UBA,
                BrokerRecoveryConflictEntity.review_status.in_(
                    list(ACTIVE_REVIEW_STATUSES)
                ),
            )
        )
        or 0
    )
    pending = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.user_broker_account_id == UBA,
                BrokerRecoveryConflictEntity.review_status == "PENDING_REVIEW",
            )
        )
        or 0
    )
    if active or pending:
        abort.append(f"conflicts active={active} pending={pending}")

    blocking = BrokerRecoveryConflictService(session).count_blocking_orders_for_uba(
        UBA
    )
    if any(blocking.values()):
        abort.append(f"blocking={blocking}")

    client = UpbitOrderRestClient(
        settings=build_upbit_settings_from_vault(
            BrokerCredentialVaultService(session).resolve_for_runtime(
                UBA,
                expected_broker="UPBIT",
                require_verified=True,
                touch_last_used=False,
            )
        ),
        user_broker_account_id=UBA,
    )
    opens = client.list_orders(state="wait", limit=50)
    client.close()
    broker_open = len(opens) if isinstance(opens, list) else -1
    if broker_open != 0:
        abort.append(f"broker_open={broker_open}")

    try:
        kill = bool(KillSwitchService(session).is_active())
    except Exception:  # noqa: BLE001
        kill = True
    if kill:
        abort.append("kill_switch")

    trading = collect_scheduler_readiness(get_settings())
    if trading.trading_scheduler_actual_state != "PAUSED":
        abort.append("trading_not_paused")
    if trading.trading_scheduler_desired_state != "PAUSE":
        abort.append("trading_desired_not_pause")

    last_run = None
    if pause and pause.last_recovery_run_id:
        run = session.get(BrokerRecoveryRunEntity, pause.last_recovery_run_id)
        if run:
            last_run = {
                "id": run.broker_recovery_run_id,
                "status": run.status_code,
            }
            if run.status_code != "SUCCESS":
                abort.append("last_run_not_success")

    return {
        "market_arg": market,
        "abort_reasons": abort,
        "account": {
            "uba_id": UBA,
            "active": bool(uba.is_active) if uba else False,
            "trading_paused": bool(pause.trading_paused) if pause else None,
            "live": bool(uba.live_order_enabled) if uba else None,
            "arm": bool(uba.live_armed) if uba else None,
            "credential": cred.get("verification_status"),
        },
        "recovery": {
            "desired": recovery.get("desired_state"),
            "actual": recovery.get("actual_state"),
            "stale": recovery.get("stale"),
            "last_run": last_run,
        },
        "conflicts": {"active": active, "pending": pending},
        "broker_open": broker_open,
        "blocking": blocking,
        "kill_switch": kill,
        "trading_scheduler": {
            "desired": trading.trading_scheduler_desired_state,
            "actual": trading.trading_scheduler_actual_state,
        },
        "orders_before": _count_orders(session, UBA),
        "exec_before": _count_exec(session, UBA),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="STEP 9-2 UPBIT 5000 dry-run")
    parser.add_argument(
        "--market",
        required=True,
        help="Allowlist market e.g. KRW-BTC (no auto-fallback)",
    )
    parser.add_argument(
        "--amount",
        default=str(DEFAULT_SMOKE_AMOUNT),
        help="Requested KRW amount (default 5000)",
    )
    args = parser.parse_args()
    market = args.market.strip().upper()
    amount = Decimal(str(args.amount))

    settings = get_settings()
    admin_key = (settings.admin_api_key or "").strip()
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY required")

    session = get_session_factory()()
    corr = f"step9-2-dry-{uuid.uuid4().hex[:12]}"
    report: dict[str, Any] = {
        "step": "9-2",
        "mode": "DRY_RUN",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": corr,
        "mutations": {
            "live_on": 0,
            "arm_on": 0,
            "trading_scheduler_start": 0,
            "create_order": 0,
            "cancel_order": 0,
            "replace_order": 0,
        },
    }
    try:
        pre = _precheck(session, admin_key, market)
        report["precheck"] = pre
        print("PRECHECK", json.dumps({"abort": pre["abort_reasons"], "market": market}, ensure_ascii=False))
        if pre["abort_reasons"]:
            report["verdict"] = "ABORT"
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return 2

        # KRW available (read-only)
        import asyncio

        private = build_upbit_private_client_for_uba(session, UBA)
        accounts = asyncio.run(private.list_accounts())
        krw = Decimal("0")
        for row in accounts:
            if str(row.get("currency") or "").upper() == "KRW":
                krw = Decimal(str(row.get("balance") or 0))
                break

        svc = Step92UpbitDryRunService(session)
        result = svc.run(
            uba_id=UBA,
            market=market,
            amount=amount,
            actor="admin:step9_2",
            correlation_id=corr,
        )
        # Dry Run Audit (실주문 Audit 아님)
        AuditLogService(session).record(
            event_type="ORDER_DRY_RUN_VALIDATED",
            actor="admin:step9_2",
            request_id=corr,
            detail={
                "uba_id": UBA,
                "market": market,
                "side": "BUY",
                "requested_amount": str(amount),
                "result": result.verdict,
                "risk_decision": result.preflight.get("dry_run_ready"),
                "reason_codes": result.reason_codes,
                "correlation_id": corr,
                "broker_submit": 0,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        session.commit()

        session.expire_all()
        orders_after = _count_orders(session, UBA)
        exec_after = _count_exec(session, UBA)
        client = UpbitOrderRestClient(
            settings=build_upbit_settings_from_vault(
                BrokerCredentialVaultService(session).resolve_for_runtime(
                    UBA,
                    expected_broker="UPBIT",
                    require_verified=True,
                    touch_last_used=False,
                )
            ),
            user_broker_account_id=UBA,
        )
        opens_after = client.list_orders(state="wait", limit=50)
        client.close()
        broker_open_after = len(opens_after) if isinstance(opens_after, list) else -1

        uba = session.get(UserBrokerAccount, UBA)
        fee = result.fee_model
        remaining_krw = krw - Decimal(str(fee.get("requested_order_amount") or amount))

        report["dry_run"] = result.to_dict()
        report["krw_available"] = str(krw)
        report["remaining_krw_after_order_amount"] = str(remaining_krw)
        report["post"] = {
            "broker_open_before": pre["broker_open"],
            "broker_open_after": broker_open_after,
            "db_orders_before": pre["orders_before"],
            "db_orders_after": orders_after,
            "exec_before": pre["exec_before"],
            "exec_after": exec_after,
            "live": bool(uba.live_order_enabled) if uba else None,
            "arm": bool(uba.live_armed) if uba else None,
            "order_delta": orders_after - pre["orders_before"],
            "exec_delta": exec_after - pre["exec_before"],
        }
        ok = (
            result.verdict == "PASS_DRY_RUN"
            and result.counters.get("create_order", 0) == 0
            and report["post"]["order_delta"] == 0
            and report["post"]["exec_delta"] == 0
            and broker_open_after == 0
            and not (uba and uba.live_order_enabled)
            and not (uba and uba.live_armed)
        )
        report["verdict"] = "PASS" if ok else f"FAIL:{result.verdict}"
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(to_jsonable(report), ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
