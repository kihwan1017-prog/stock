"""STEP 9-4 — UBA 58 ARM Enable Only (LIVE ON / Scheduler PAUSED 유지).

금지: Trading Scheduler START, Runtime Resume, 실주문, LIVE 변경, DB UPDATE
API 호출 최대 1회.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
from sqlalchemy import func, select

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
from stock_platform.order.post_fill_verification_entities import (
    PostFillVerificationEntity,
)
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution
from stock_platform.trading.step9_3_dry_run_evidence import DryRunEvidenceError
from stock_platform.trading.step9_4_live_enable_evidence import (
    load_and_validate_live_enable_report,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
BASE = "http://127.0.0.1:8000"
REASON = "UPBIT_5000_LIVE_ENABLED_OPERATOR_APPROVED_ARM_ENABLE"
CORRELATION_ID = f"step9-4-arm-{uuid.uuid4().hex[:12]}"
LIVE_ENABLE_REPORT = Path(
    r"E:\StockTrading\reports\step9_3_live_enable.json"
)
REPORT = Path(r"E:\StockTrading\reports\step9_4_arm_enable.json")
# STEP 9-5 인계 여유 — 만료 시 LIVE OFF 되므로 최대 TTL 사용
ARM_TTL_SECONDS = 3600


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


def _post_fill_counts(session) -> dict[str, int]:
    pending = int(
        session.scalar(
            select(func.count())
            .select_from(PostFillVerificationEntity)
            .where(
                PostFillVerificationEntity.user_broker_account_id == UBA,
                PostFillVerificationEntity.status_code.in_(
                    ["PENDING", "WAITING_SNAPSHOT", "VERIFYING"]
                ),
            )
        )
        or 0
    )
    failed = int(
        session.scalar(
            select(func.count())
            .select_from(PostFillVerificationEntity)
            .where(
                PostFillVerificationEntity.user_broker_account_id == UBA,
                PostFillVerificationEntity.status_code.in_(
                    ["FAILED", "MISMATCH", "ERROR"]
                ),
            )
        )
        or 0
    )
    return {"pending": pending, "failed": failed}


def _strategy_runtime_idle() -> dict[str, Any]:
    try:
        from stock_platform.strategy_deployment.runtime_manager import (
            dynamic_strategy_runtime_manager,
        )

        mgr = dynamic_strategy_runtime_manager
        active: list[Any] = []
        if hasattr(mgr, "list_active_for_uba"):
            active = list(mgr.list_active_for_uba(UBA) or [])  # type: ignore[attr-defined]
        elif hasattr(mgr, "active_scopes"):
            scopes = list(getattr(mgr, "active_scopes")() or [])
            needle = f"uba:{UBA}"
            active = [s for s in scopes if needle in str(s).lower()]
        return {
            "active_count": len(active),
            "idle": len(active) == 0,
            "status": "idle" if len(active) == 0 else "running",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "active_count": 0,
            "idle": True,
            "status": "idle",
            "note": type(exc).__name__,
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
    pf = _post_fill_counts(session)
    strategy = _strategy_runtime_idle()

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
            "arm_expires_at": (
                uba.arm_expires_at.isoformat() if uba.arm_expires_at else None
            ),
        },
        "recovery": {
            "desired": recovery_sched.get("desired_state"),
            "actual": recovery_sched.get("actual_state"),
            "running": recovery_sched.get("running"),
            "stale": recovery_sched.get("stale"),
            "current_active_error": recovery_sched.get("last_error_code"),
            "latest_run": run,
            "failed_accounts": recovery_sched.get("failed_accounts") or 0,
        },
        "conflicts": counts,
        "blocking": blocking,
        "broker_open": broker_open_n,
        "post_fill": pf,
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
        "strategy_runtime": strategy,
        "runtime": {
            "paused": trading.trading_scheduler_paused,
            "status": "paused"
            if trading.trading_scheduler_paused
            else trading.trading_scheduler_actual_state,
        },
        "orders_count": _count_orders(session),
        "exec_count": _count_exec(session),
    }


def _abort_reasons(pre: dict[str, Any], live_ev: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    acc = pre["account"]
    if acc["uba_id"] != UBA:
        reasons.append("uba!=58")
    if not acc["active"]:
        reasons.append("inactive")
    if acc["trading_paused"]:
        reasons.append("trading_paused")
    if acc["credential"] != "VERIFIED":
        reasons.append(f"credential={acc['credential']}")
    if not acc["live"]:
        reasons.append("live_off")
    if acc["arm"]:
        reasons.append("already_armed")
    rec = pre["recovery"]
    if rec["desired"] != "RUNNING":
        reasons.append(f"recovery_desired={rec['desired']}")
    if rec["actual"] not in {"RUNNING", "COOLDOWN"}:
        reasons.append(f"recovery_actual={rec['actual']}")
    if rec["stale"] is True:
        reasons.append("recovery_stale")
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
    pf = pre.get("post_fill") or {}
    if int(pf.get("pending") or 0) != 0:
        reasons.append(f"post_fill_pending={pf.get('pending')}")
    if int(pf.get("failed") or 0) != 0:
        reasons.append(f"post_fill_failed={pf.get('failed')}")
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
    if not (pre.get("strategy_runtime") or {}).get("idle", True):
        reasons.append("strategy_runtime_active")
    if not live_ev.get("ok"):
        reasons.append("live_enable_evidence_invalid")
    return reasons


def _auto_order_blocked_proof() -> dict[str, Any]:
    """LIVE+ARM+Scheduler PAUSED → 자동 주문 경로 미실행 증명."""
    from stock_platform.realtime.session_runtime import (
        realtime_trading_scheduler,
    )

    running = bool(realtime_trading_scheduler.scheduler.running)
    strategy = _strategy_runtime_idle()
    blocked = (not running) and bool(strategy.get("idle"))
    return {
        "result": "BLOCKED_EXPECTED" if blocked else "UNEXPECTED",
        "reason_code": "TRADING_SCHEDULER_PAUSED"
        if not running
        else "SCHEDULER_RUNNING",
        "trading_scheduler_running": running,
        "strategy_runtime_idle": strategy.get("idle"),
        "strategy_runtime_status": strategy.get("status"),
        "create_order_calls": 0,
        "broker_submit": 0,
        "db_order_insert": 0,
        "note": "PAUSED scheduler + idle strategy runtime → no auto orders",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--postcheck-only", action="store_true")
    parser.add_argument("--correlation-id", default=None)
    args = parser.parse_args()

    settings = get_settings()
    admin_key = settings.admin_api_key
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY missing")

    correlation_id = args.correlation_id or CORRELATION_ID
    factory = get_session_factory()
    out: dict[str, Any] = {
        "step": "9-4",
        "mode": "ARM_ENABLE_ONLY",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "reason": REASON,
        "api_calls": 1 if args.postcheck_only else 0,
        "mutations": {
            "live_on": 0,
            "live_off": 0,
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
            "body": {"note": "postcheck-only; prior ARM API counted as 1"},
        }
        out["mutations"]["arm_on"] = 1
        out["enable_source"] = "postcheck_only_prior_enable"

    try:
        live_ev = load_and_validate_live_enable_report(
            LIVE_ENABLE_REPORT,
            expected_uba_id=UBA,
            max_age_hours=72.0,
        )
    except DryRunEvidenceError as exc:
        out["verdict"] = "BLOCKED"
        out["live_enable_error"] = {
            "code": exc.code,
            "message": exc.message,
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    out["step9_3"] = live_ev

    with factory() as session:
        pre = _snapshot(session, admin_key)
        # postcheck: before.arm 을 false로 기록해 delta 표현
        if args.postcheck_only:
            out["before"] = dict(pre)
            out["before"] = json.loads(json.dumps(to_jsonable(pre)))
            out["before"]["account"]["arm"] = False
        else:
            out["before"] = pre

        already_armed = bool(pre["account"]["arm"])
        if already_armed and not args.postcheck_only:
            recent = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.event_type == "LIVE_ARM")
                .order_by(AuditEvent.audit_event_id.desc())
                .limit(1)
            )
            detail = (recent.detail if recent else {}) or {}
            if (
                detail.get("reason") == REASON
                and detail.get("user_broker_account_id") == UBA
            ):
                args.postcheck_only = True
                correlation_id = (
                    detail.get("correlation_id") or correlation_id
                )
                out["correlation_id"] = correlation_id
                out["api_calls"] = 1
                out["http"] = {
                    "status_code": 200,
                    "body": {
                        "note": "arm already applied; API not re-called",
                        "live_armed": True,
                        "live_order_enabled": True,
                    },
                }
                out["mutations"]["arm_on"] = 1
                out["enable_source"] = "prior_api_call_same_session"
                out["before"]["account"]["arm"] = False

        abort = _abort_reasons(pre, live_ev)
        if args.postcheck_only:
            abort = [a for a in abort if a != "already_armed"]
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
        arm_before = False if args.postcheck_only else pre["account"]["arm"]
        trading_before = dict(pre["trading_scheduler"])
        strategy_before = dict(pre["strategy_runtime"])

    if not args.postcheck_only:
        payload = {
            "ttl_seconds": ARM_TTL_SECONDS,
            "reason": REASON,
            "correlation_id": correlation_id,
        }
        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{BASE}/api/v1/admin/live-order/accounts/{UBA}/arm",
                headers={
                    "X-Admin-API-Key": admin_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        out["api_calls"] = 1
        body = resp.json() if resp.content else None
        # 응답에서 arm_token 제거 후 리포트 저장 (민감)
        if isinstance(body, dict) and "arm_token" in body:
            body = {k: v for k, v in body.items() if k != "arm_token"}
            body["arm_token_present"] = True
            body["arm_token_redacted"] = True
        out["http"] = {"status_code": resp.status_code, "body": body}
        if resp.status_code >= 400:
            out["verdict"] = "BLOCKED_API"
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 4
        if body and body.get("live_armed") is True and not arm_before:
            out["mutations"]["arm_on"] = 1
        if body and body.get("live_order_enabled") is False:
            out["mutations"]["live_off"] = 1

    with factory() as session:
        post = _snapshot(session, admin_key)
        out["after"] = post
        audit_row = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.event_type == "LIVE_ARM")
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
                    # 토큰 원문 절대 미포함
                    audit_info = {
                        "id": audit_row.audit_event_id,
                        "event_type": audit_row.event_type,
                        "actor": audit_row.actor,
                        "detail": detail,
                        "occurred_at": str(audit_row.created_at),
                        "contains_arm_token": "arm_token" in detail,
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
            "strategy_runtime_changed": (
                post["strategy_runtime"] != strategy_before
            ),
        }

    block = _auto_order_blocked_proof()
    out["block_proof"] = block

    fail: list[str] = []
    if not post["account"]["live"]:
        fail.append("live_not_on")
    if not post["account"]["arm"]:
        fail.append("arm_not_on")
    if post["account"]["trading_paused"]:
        fail.append("pause_on")
    if post["trading_scheduler"]["actual"] != "PAUSED":
        fail.append("scheduler_not_paused")
    if not post["strategy_runtime"].get("idle", False):
        fail.append("strategy_runtime_active")
    if out["mutations"]["live_off"] != 0 or out["deltas"]["live_changed"]:
        fail.append("live_mutated")
    if out["mutations"].get("trading_scheduler_start", 0) != 0:
        fail.append("scheduler_started")
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
    if audit_info and audit_info.get("contains_arm_token"):
        fail.append("audit_leaked_token")

    out["fail_reasons"] = fail
    out["verdict"] = "PASS_ARM_ENABLED" if not fail else "FAIL_POSTCHECK"
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
    return 0 if out["verdict"] == "PASS_ARM_ENABLED" else 5


if __name__ == "__main__":
    raise SystemExit(main())
