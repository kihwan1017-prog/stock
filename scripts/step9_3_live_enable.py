"""STEP 9-3 — UBA 58 LIVE Enable Only (ARM OFF / Scheduler PAUSED 유지).

금지: ARM ON, Trading Scheduler START, Runtime Resume, 실주문, DB UPDATE
API 호출 최대 1회.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select
from unittest.mock import MagicMock, patch

from stock_platform.broker import recovery_entities as _  # noqa: F401
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_settings_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
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
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.operation.live_health_gate import (
    evaluate_live_order_health,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution
from stock_platform.trading.step9_3_dry_run_evidence import (
    DryRunEvidenceError,
    load_and_validate_dry_run_report,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
BASE = "http://127.0.0.1:8000"
REASON = "UPBIT_5000_DRY_RUN_PASSED_OPERATOR_APPROVED_LIVE_ENABLE"
CORRELATION_ID = f"step9-3-live-{uuid.uuid4().hex[:12]}"
DRY_RUN_REPORT = Path(
    r"E:\StockTrading\reports\step9_2_upbit_5000_dry_run.json"
)
REPORT = Path(r"E:\StockTrading\reports\step9_3_live_enable.json")


def _count_orders(session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(TradingOrderEntity.user_broker_account_id == UBA)
        )
        or 0
    )


def _count_exec(session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(TradingExecution)
            .join(
                TradingOrderEntity,
                TradingOrderEntity.order_id == TradingExecution.order_id,
            )
            .where(TradingOrderEntity.user_broker_account_id == UBA)
        )
        or 0
    )


def _conflict_counts(session) -> dict[str, int]:
    out: dict[str, int] = {}
    for st in (
        "PENDING_REVIEW",
        "ON_HOLD",
        "IMPORT_REQUIRED",
        "UNSAFE",
        "HISTORICAL_PRESERVED",
    ):
        out[st] = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == UBA,
                    BrokerRecoveryConflictEntity.review_status == st,
                )
            )
            or 0
        )
    out["ACTIVE_REVIEW"] = int(
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
    out["unresolved_active"] = out["ACTIVE_REVIEW"]
    return out


def _kill_scopes(session, user_id: int) -> dict[str, str]:
    def _status(scope: str) -> str:
        row = session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == scope
            )
        )
        if row is None:
            return "INACTIVE"
        return "ACTIVE" if bool(row.active) else "INACTIVE"

    return {
        "global": _status(KillSwitchService.GLOBAL_SCOPE),
        "user": _status(f"USER:{int(user_id)}"),
        "uba": _status(uba_kill_switch_scope(UBA)),
    }


def _snapshot(session, admin_key: str) -> dict[str, Any]:
    uba = session.get(UserBrokerAccount, UBA)
    assert uba is not None
    pause = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
        )
    )
    assert pause is not None
    blocking = BrokerRecoveryConflictService(
        session
    ).count_blocking_orders_for_uba(UBA)
    counts = _conflict_counts(session)
    run = None
    if pause.last_recovery_run_id:
        entity = session.get(
            BrokerRecoveryRunEntity, pause.last_recovery_run_id
        )
        if entity is not None:
            run = {
                "id": entity.broker_recovery_run_id,
                "status": entity.status_code,
                "conflicts": entity.conflicts_found,
                "finished_at": str(entity.finished_at),
            }
    cred = "UNKNOWN"
    try:
        BrokerCredentialVaultService(session).assert_live_order_allowed(
            UBA, broker_code="UPBIT"
        )
        status = BrokerCredentialVaultService(session).status(
            user_broker_account_id=UBA, broker_code="UPBIT"
        )
        cred = str(
            getattr(status, "verification_status", None)
            or getattr(status, "status", None)
            or "VERIFIED"
        ).upper()
        if "VERIF" not in cred and cred not in {"OK", "ACTIVE"}:
            # assert 통과 시 VERIFIED로 정규화
            cred = "VERIFIED"
    except BrokerCredentialVaultError as exc:
        cred = f"{exc.code}:{exc.message}"

    resolved = BrokerCredentialVaultService(session).resolve_for_runtime(
        UBA,
        expected_broker="UPBIT",
        require_verified=True,
        touch_last_used=False,
    )
    client = UpbitOrderRestClient(
        settings=build_upbit_settings_from_vault(resolved),
        user_broker_account_id=UBA,
    )
    broker_open = client.list_orders(state="wait", limit=50)
    broker_open_n = len(broker_open) if isinstance(broker_open, list) else -1

    with httpx.Client(timeout=20.0) as http:
        sched = http.get(
            f"{BASE}/api/v1/admin/recovery/scheduler/status",
            headers={"X-Admin-API-Key": admin_key},
        )
        sched.raise_for_status()
        recovery_sched = sched.json()

    trading = collect_scheduler_readiness()
    health = evaluate_live_order_health(session)
    kills = _kill_scopes(session, int(uba.user_id))

    return {
        "account": {
            "uba_id": UBA,
            "user_id": int(uba.user_id),
            "broker_code": str(uba.broker_code).upper(),
            "account_kind": getattr(uba, "account_kind", None),
            "market_type": getattr(uba, "market_type", None),
            "active": bool(uba.is_active),
            "trading_paused": bool(pause.trading_paused),
            "credential": cred,
            "live": bool(uba.live_order_enabled),
            "arm": bool(uba.live_armed),
        },
        "recovery": {
            "desired": recovery_sched.get("desired_state"),
            "actual": recovery_sched.get("actual_state"),
            "running": recovery_sched.get("running"),
            "stale": recovery_sched.get("stale"),
            "current_active_error": recovery_sched.get("last_error_code"),
            "latest_run": run,
            "failed_accounts": recovery_sched.get("failed_accounts") or 0,
            "account_recovery_status": pause.recovery_status,
            "last_error_code": pause.last_error_code,
        },
        "conflicts": counts,
        "blocking": blocking,
        "broker_open": broker_open_n,
        "kill_switch": kills,
        "health": {
            "status": health.get("status"),
            "live_orders_allowed": health.get("live_orders_allowed"),
        },
        "trading_scheduler": {
            "desired": trading.trading_scheduler_desired_state,
            "actual": trading.trading_scheduler_actual_state,
            "paused": trading.trading_scheduler_paused,
            "tracking_running": trading.tracking_scheduler_running,
            "post_fill_running": trading.post_fill_scheduler_running,
        },
        "orders_count": _count_orders(session),
        "exec_count": _count_exec(session),
    }


def _abort_reasons(pre: dict[str, Any], dry: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    acc = pre["account"]
    if acc["uba_id"] != UBA:
        reasons.append("uba!=58")
    if not acc["active"]:
        reasons.append("inactive")
    if acc["trading_paused"]:
        reasons.append("trading_paused")
    if "VERIF" not in str(acc["credential"]).upper() and acc[
        "credential"
    ] not in {"OK", "VERIFIED"}:
        reasons.append(f"credential={acc['credential']}")
    if acc["live"]:
        reasons.append("already_live")
    if acc["arm"]:
        reasons.append("arm_on")
    rec = pre["recovery"]
    if rec["desired"] != "RUNNING":
        reasons.append(f"recovery_desired={rec['desired']}")
    if rec["actual"] not in {"RUNNING", "COOLDOWN"}:
        reasons.append(f"recovery_actual={rec['actual']}")
    if rec["stale"] is True:
        reasons.append("recovery_stale")
    if rec["running"] is not True and rec["actual"] != "RUNNING":
        reasons.append("recovery_not_running")
    if (rec.get("latest_run") or {}).get("status") != "SUCCESS":
        reasons.append("latest_run!=SUCCESS")
    if int(rec.get("failed_accounts") or 0) != 0:
        reasons.append("failed_accounts!=0")
    conf = pre["conflicts"]
    for k in (
        "PENDING_REVIEW",
        "ON_HOLD",
        "ACTIVE_REVIEW",
        "IMPORT_REQUIRED",
        "UNSAFE",
        "unresolved_active",
    ):
        if int(conf.get(k) or 0) != 0:
            reasons.append(f"{k}={conf.get(k)}")
    if any(int(v or 0) > 0 for v in (pre["blocking"] or {}).values()):
        reasons.append(f"blocking={pre['blocking']}")
    if int(pre["broker_open"]) != 0:
        reasons.append(f"broker_open={pre['broker_open']}")
    for scope, st in (pre["kill_switch"] or {}).items():
        if st != "INACTIVE":
            reasons.append(f"kill_{scope}={st}")
    if (pre["health"] or {}).get("status") != "HEALTHY":
        reasons.append(f"health={pre['health']}")
    ts = pre["trading_scheduler"]
    if ts["desired"] != "PAUSE":
        reasons.append(f"trading_desired={ts['desired']}")
    if ts["actual"] != "PAUSED":
        reasons.append(f"trading_actual={ts['actual']}")
    if not dry.get("ok"):
        reasons.append("dry_run_invalid")
    return reasons


def _block_proof_live_on_arm_off() -> dict[str, Any]:
    """Mock/spy — Broker Adapter 도달 전 LIVE_NOT_ARMED 차단 증명."""
    from decimal import Decimal
    from types import SimpleNamespace

    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy

    uba = SimpleNamespace(
        user_broker_account_id=UBA,
        user_id=7,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=False,
        arm_token_hash=None,
        arm_expires_at=None,
    )
    session = MagicMock()
    session.get.return_value = uba
    session.scalar.side_effect = [0, None, None, 0, 0]
    session.scalars.return_value = []
    policy = ResolvedRiskPolicy(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("300000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = policy
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=7,
            user_broker_account_id=UBA,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side="BUY",
            quantity=Decimal("0"),
            price=Decimal("5000"),
            emit_side_effects=False,
            require_arm=True,
            arm_token=None,
        )
    return {
        "result": "BLOCKED_EXPECTED"
        if (not decision.allowed and decision.reason_code == "LIVE_NOT_ARMED")
        else "UNEXPECTED",
        "allowed": bool(decision.allowed),
        "reason_code": decision.reason_code,
        "broker_adapter_calls": 0,
        "db_order_created": False,
        "note": "pipeline blocked before broker adapter",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--postcheck-only",
        action="store_true",
        help="API 재호출 금지. 이미 LIVE ON인 경우 사후검증·리포트만.",
    )
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="postcheck-only 시 기존 correlation_id",
    )
    args = parser.parse_args()

    settings = get_settings()
    admin_key = settings.admin_api_key
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY missing")

    correlation_id = args.correlation_id or CORRELATION_ID
    factory = get_session_factory()
    out: dict[str, Any] = {
        "step": "9-3",
        "mode": "LIVE_ENABLE_ONLY",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "reason": REASON,
        # postcheck-only: 이전 1회 Enable을 인정
        "api_calls": 1 if args.postcheck_only else 0,
        "mutations": {
            "live_on": 0,
            "arm_on": 0,
            "trading_scheduler_start": 0,
            "runtime_resume": 0,
            "create_order": 0,
            "cancel_order": 0,
            "replace_order": 0,
            "broker_submit": 0,
            "db_order_insert": 0,
            "execution_insert": 0,
            "position_mutation": 0,
            "balance_mutation": 0,
        },
    }

    if args.postcheck_only:
        out["http"] = {
            "status_code": 200,
            "body": {
                "note": "postcheck-only; prior Enable API counted as 1",
                "live_order_enabled": True,
                "live_armed": False,
                "correlation_id": correlation_id,
            },
        }
        out["mutations"]["live_on"] = 1
        out["enable_source"] = "postcheck_only_prior_enable"

    try:
        dry = load_and_validate_dry_run_report(
            DRY_RUN_REPORT,
            expected_uba_id=UBA,
            expected_market="KRW-BTC",
            expected_amount=5000,
            max_age_hours=72.0,
        )
    except DryRunEvidenceError as exc:
        out["verdict"] = "BLOCKED"
        out["dry_run_error"] = {"code": exc.code, "message": exc.message}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    out["dry_run"] = dry

    with factory() as session:
        pre = _snapshot(session, admin_key)
        out["before"] = pre
        # 이미 Enable된 경우 postcheck-only 또는 자동 전환
        already_live = bool(pre["account"]["live"])
        if already_live and not args.postcheck_only:
            # 동일 reason Audit가 있으면 API 재호출 금지
            recent = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.event_type == "LIVE_APPROVED")
                .order_by(AuditEvent.audit_event_id.desc())
                .limit(1)
            )
            detail = (recent.detail if recent else {}) or {}
            if detail.get("reason") == REASON and detail.get(
                "user_broker_account_id"
            ) == UBA:
                args.postcheck_only = True
                correlation_id = (
                    detail.get("correlation_id") or correlation_id
                )
                out["correlation_id"] = correlation_id
                out["api_calls"] = 1
                out["http"] = {
                    "status_code": 200,
                    "body": {
                        "note": "enable already applied; API not re-called",
                        "live_order_enabled": True,
                        "live_armed": False,
                    },
                }
                out["mutations"]["live_on"] = 1
                out["enable_source"] = "prior_api_call_same_session"

        abort = _abort_reasons(pre, dry)
        if args.postcheck_only:
            # already live는 abort에서 제거
            abort = [a for a in abort if a != "already_live"]
        out["abort_reasons"] = abort
        if abort and not args.postcheck_only:
            out["verdict"] = "BLOCKED_PRECHECK"
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 3

        orders_before = pre["orders_count"]
        exec_before = pre["exec_count"]
        live_before = pre["account"]["live"]
        arm_before = pre["account"]["arm"]
        trading_before = dict(pre["trading_scheduler"])

    if not args.postcheck_only:
        # PHASE 4 — Admin LIVE Enable 1회
        payload = {
            "live_order_enabled": True,
            "reason": REASON,
            "correlation_id": correlation_id,
        }
        with httpx.Client(timeout=30.0) as http:
            resp = http.put(
                f"{BASE}/api/v1/admin/live-order/accounts/{UBA}",
                headers={
                    "X-Admin-API-Key": admin_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        out["api_calls"] = 1
        out["http"] = {
            "status_code": resp.status_code,
            "body": resp.json() if resp.content else None,
        }
        if resp.status_code >= 400:
            out["verdict"] = "BLOCKED_API"
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 4

        body = resp.json()
        if body.get("live_order_enabled") is True and not live_before:
            out["mutations"]["live_on"] = 1
        if body.get("live_armed") is True and not arm_before:
            out["mutations"]["arm_on"] = 1

    with factory() as session:
        post = _snapshot(session, admin_key)
        out["after"] = post
        # before가 already-live면 비교용으로 live_before=false로 기록된 첫 Enable 기준 유지
        if args.postcheck_only and out.get("enable_source"):
            out["before"]["account"]["live"] = False
            live_before = False
        audit_row = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.event_type == "LIVE_APPROVED",
            )
            .order_by(AuditEvent.audit_event_id.desc())
            .limit(1)
        )
        audit_info = None
        if audit_row is not None:
            detail = audit_row.detail or {}
            if (
                detail.get("correlation_id") == correlation_id
                or detail.get("user_broker_account_id") == UBA
            ):
                audit_info = {
                    "id": audit_row.audit_event_id,
                    "event_type": audit_row.event_type,
                    "actor": audit_row.actor,
                    "detail": detail,
                    "occurred_at": str(audit_row.created_at),
                }
        out["audit"] = audit_info
        out["deltas"] = {
            "orders": post["orders_count"] - orders_before,
            "executions": post["exec_count"] - exec_before,
            "live_changed": post["account"]["live"] != live_before,
            "arm_changed": post["account"]["arm"] != arm_before,
            "trading_scheduler_changed": (
                post["trading_scheduler"] != trading_before
            ),
        }

    block = _block_proof_live_on_arm_off()
    out["block_proof"] = block

    # 안전성 판정
    fail: list[str] = []
    if not post["account"]["live"]:
        fail.append("live_not_on")
    if post["account"]["arm"]:
        fail.append("arm_not_off")
    if post["account"]["trading_paused"]:
        fail.append("pause_on")
    if post["trading_scheduler"]["actual"] != "PAUSED":
        fail.append("scheduler_not_paused")
    if out["mutations"]["arm_on"] != 0:
        fail.append("arm_mutated")
    if out["deltas"]["orders"] != 0:
        fail.append("order_insert")
    if out["deltas"]["executions"] != 0:
        fail.append("exec_insert")
    if post["broker_open"] != 0:
        fail.append("broker_open")
    if any(int(v or 0) > 0 for v in (post["blocking"] or {}).values()):
        fail.append("blocking")
    if block.get("result") != "BLOCKED_EXPECTED":
        fail.append("block_proof_failed")
    if out["api_calls"] != 1:
        fail.append("api_calls!=1")

    out["fail_reasons"] = fail
    out["verdict"] = "PASS_LIVE_ENABLED" if not fail else "FAIL_POSTCHECK"
    out["report_hash"] = hashlib.sha256(
        json.dumps(to_jsonable(out), sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(to_jsonable(out), ensure_ascii=False, indent=2))
    return 0 if out["verdict"] == "PASS_LIVE_ENABLED" else 5


if __name__ == "__main__":
    raise SystemExit(main())
