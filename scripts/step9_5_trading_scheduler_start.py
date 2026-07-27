"""STEP 9-5 — Trading Scheduler Start Only / No Order.

금지: Strategy/Runtime Start, 재ARM, LIVE 변경, 실주문, STEP 9-6 자동
API 호출 최대 1회.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

UBA = 58
BASE = "http://127.0.0.1:8000"
REASON = (
    "UPBIT_5000_LIVE_ARMED_OPERATOR_APPROVED_SCHEDULER_START_NO_ORDER"
)
CORRELATION_ID = f"step9-5-sched-{uuid.uuid4().hex[:12]}"
REPORT = Path(r"E:\StockTrading\reports\step9_5_trading_scheduler_start.json")
OBSERVE_SECONDS = 25
MIN_ARM_REMAINING = 120
ESTIMATED_STEP_SECONDS = 90


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


def _conflicts(session) -> dict[str, int]:
    out: dict[str, int] = {}
    for st in (
        "PENDING_REVIEW",
        "ON_HOLD",
        "IMPORT_REQUIRED",
        "UNSAFE",
        "ACTIVE_REVIEW",
    ):
        if st == "ACTIVE_REVIEW":
            out[st] = int(
                session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == UBA,
                        BrokerRecoveryConflictEntity.review_status.in_(
                            list(ACTIVE_REVIEW_STATUSES)
                        ),
                    )
                )
                or 0
            )
        else:
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
    out["unresolved_active"] = out["ACTIVE_REVIEW"]
    return out


def _kill(session, user_id: int) -> dict[str, str]:
    def _st(scope: str) -> str:
        row = session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == scope
            )
        )
        if row is None:
            return "INACTIVE"
        return "ACTIVE" if row.active else "INACTIVE"

    return {
        "global": _st(KillSwitchService.GLOBAL_SCOPE),
        "user": _st(f"USER:{user_id}"),
        "uba": _st(uba_kill_switch_scope(UBA)),
    }


def _strategy_counts(session) -> dict[str, int]:
    active_links = 0
    try:
        from stock_platform.strategy_deployment.definition_entities import (
            AccountStrategyLinkEntity,
        )

        active_links = int(
            session.scalar(
                select(func.count())
                .select_from(AccountStrategyLinkEntity)
                .where(
                    AccountStrategyLinkEntity.user_broker_account_id == UBA,
                    AccountStrategyLinkEntity.is_active.is_(True),
                )
            )
            or 0
        )
    except Exception:  # noqa: BLE001
        active_links = -1
    return {
        "active_deployment": 0,
        "active_links": active_links,
        "pending_signal": 0,
        "pending_trade_intent": 0,
        "pending_order_command": 0,
    }


def _db_snapshot(session, admin_key: str) -> dict[str, Any]:
    uba = session.get(UserBrokerAccount, UBA)
    assert uba is not None
    pause = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
        )
    )
    assert pause is not None
    now = datetime.now(timezone.utc)
    expires = uba.arm_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    remaining = (
        int((expires - now).total_seconds()) if expires is not None else -1
    )
    run = None
    if pause.last_recovery_run_id:
        entity = session.get(
            BrokerRecoveryRunEntity, pause.last_recovery_run_id
        )
        if entity is not None:
            run = {
                "id": entity.broker_recovery_run_id,
                "status": entity.status_code,
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
    blocking = BrokerRecoveryConflictService(
        session
    ).count_blocking_orders_for_uba(UBA)
    pf_pending = int(
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
    pf_failed = int(
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

    with httpx.Client(timeout=20.0) as http:
        rec = http.get(
            f"{BASE}/api/v1/admin/recovery/scheduler/status",
            headers={"X-Admin-API-Key": admin_key},
        )
        rec.raise_for_status()
        recovery = rec.json()
        ts = http.get(
            f"{BASE}/api/v1/admin/trading-scheduler/status",
            headers={"X-Admin-API-Key": admin_key},
        )
        ts.raise_for_status()
        trading = ts.json()

    health = evaluate_live_order_health(session)
    return {
        "account": {
            "uba_id": UBA,
            "user_id": int(uba.user_id),
            "broker_code": str(uba.broker_code).upper(),
            "active": bool(uba.is_active),
            "trading_paused": bool(pause.trading_paused),
            "credential": cred,
            "live": bool(uba.live_order_enabled),
            "arm": bool(uba.live_armed),
            "arm_armed_at": (
                uba.arm_armed_at.isoformat() if uba.arm_armed_at else None
            ),
            "arm_expires_at": expires.isoformat() if expires else None,
            "arm_remaining_seconds": remaining,
            "current_time": now.isoformat(),
        },
        "recovery": {
            "desired": recovery.get("desired_state"),
            "actual": recovery.get("actual_state"),
            "running": recovery.get("running"),
            "stale": recovery.get("stale"),
            "current_active_error": recovery.get("last_error_code"),
            "latest_run": run,
            "failed_accounts": recovery.get("failed_accounts") or 0,
            "last_success_at": recovery.get("last_success_at"),
        },
        "conflicts": _conflicts(session),
        "blocking": blocking,
        "broker_open": broker_open_n,
        "post_fill": {"pending": pf_pending, "failed": pf_failed},
        "kill_switch": _kill(session, int(uba.user_id)),
        "health": {
            "status": health.get("status"),
            "live_orders_allowed": health.get("live_orders_allowed"),
        },
        "trading_scheduler": trading,
        "strategy": _strategy_counts(session),
        "orders_count": _count_orders(session),
        "exec_count": _count_exec(session),
    }


def _recovery_ok(rec: dict[str, Any]) -> tuple[bool, str]:
    if rec.get("desired") != "RUNNING":
        return False, f"desired={rec.get('desired')}"
    actual = rec.get("actual")
    if actual == "RUNNING":
        return True, "RUNNING"
    if actual == "COOLDOWN":
        if rec.get("stale") is True:
            return False, "cooldown_stale"
        if rec.get("running") is not True:
            return False, "cooldown_not_running"
        if rec.get("current_active_error"):
            return False, f"cooldown_error={rec.get('current_active_error')}"
        if (rec.get("latest_run") or {}).get("status") != "SUCCESS":
            return False, "cooldown_run_not_success"
        if int(rec.get("failed_accounts") or 0) != 0:
            return False, "cooldown_failed_accounts"
        return True, "COOLDOWN_HEALTHY"
    return False, f"actual={actual}"


def _abort(pre: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    acc = pre["account"]
    if not acc["active"]:
        reasons.append("inactive")
    if acc["trading_paused"]:
        reasons.append("paused")
    if not acc["live"]:
        reasons.append("live_off")
    if not acc["arm"]:
        reasons.append("arm_off")
    if acc["credential"] != "VERIFIED":
        reasons.append(f"cred={acc['credential']}")
    rem = int(acc.get("arm_remaining_seconds") or -1)
    if rem < MIN_ARM_REMAINING:
        reasons.append(f"arm_ttl_insufficient={rem}")
    if rem < ESTIMATED_STEP_SECONDS:
        reasons.append(f"arm_ttl_lt_step_estimate={rem}")
    ok, note = _recovery_ok(pre["recovery"])
    if not ok:
        reasons.append(f"recovery={note}")
    for k, v in (pre["conflicts"] or {}).items():
        if k in {
            "PENDING_REVIEW",
            "ON_HOLD",
            "ACTIVE_REVIEW",
            "IMPORT_REQUIRED",
            "UNSAFE",
            "unresolved_active",
        } and int(v or 0) != 0:
            reasons.append(f"{k}={v}")
    if any(int(v or 0) > 0 for v in (pre["blocking"] or {}).values()):
        reasons.append(f"blocking={pre['blocking']}")
    if int(pre["broker_open"]) != 0:
        reasons.append(f"broker_open={pre['broker_open']}")
    if int((pre.get("post_fill") or {}).get("pending") or 0) != 0:
        reasons.append("post_fill_pending")
    if int((pre.get("post_fill") or {}).get("failed") or 0) != 0:
        reasons.append("post_fill_failed")
    for s, st in (pre["kill_switch"] or {}).items():
        if st != "INACTIVE":
            reasons.append(f"kill_{s}")
    if (pre["health"] or {}).get("status") != "HEALTHY":
        reasons.append("unhealthy")
    strat = pre.get("strategy") or {}
    if int(strat.get("active_links") or 0) > 0:
        reasons.append(f"active_links={strat.get('active_links')}")
    ts = pre.get("trading_scheduler") or {}
    if ts.get("running") is True:
        reasons.append("already_running")
    if int(ts.get("strategy_active_scopes") or 0) > 0:
        reasons.append(
            f"strategy_scopes={ts.get('strategy_active_scopes')}"
        )
    if ts.get("execution_runner_running"):
        reasons.append("execution_runner_running")
    if ts.get("order_path_idle") is False:
        reasons.append("order_path_not_idle")
    return reasons


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--postcheck-only", action="store_true")
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument(
        "--observe-seconds", type=int, default=OBSERVE_SECONDS
    )
    args = parser.parse_args()

    settings = get_settings()
    admin_key = settings.admin_api_key
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY missing")
    headers = {"X-Admin-API-Key": admin_key}
    correlation_id = args.correlation_id or CORRELATION_ID
    factory = get_session_factory()

    out: dict[str, Any] = {
        "step": "9-5",
        "mode": "TRADING_SCHEDULER_START_NO_ORDER",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "reason": REASON,
        "api_calls": 1 if args.postcheck_only else 0,
        "mutations": {
            "scheduler_start": 0,
            "live_change": 0,
            "arm_change": 0,
            "arm_ttl_refresh": 0,
            "runtime_resume": 0,
            "strategy_start": 0,
            "create_order": 0,
            "broker_submit": 0,
            "db_order_insert": 0,
            "execution_insert": 0,
        },
    }

    with factory() as session:
        pre = _db_snapshot(session, admin_key)
        out["before"] = pre
        abort = _abort(pre)
        if args.postcheck_only:
            abort = [a for a in abort if a != "already_running"]
        out["abort_reasons"] = abort
        out["arm_ttl"] = {
            "armed_at": pre["account"]["arm_armed_at"],
            "expires_at": pre["account"]["arm_expires_at"],
            "current_time": pre["account"]["current_time"],
            "remaining_ttl_seconds": pre["account"][
                "arm_remaining_seconds"
            ],
            "estimated_step_seconds": ESTIMATED_STEP_SECONDS,
            "observe_seconds": args.observe_seconds,
            "expire_before_step9_6_risk": (
                int(pre["account"]["arm_remaining_seconds"])
                < ESTIMATED_STEP_SECONDS + 300
            ),
        }
        ok_rec, rec_note = _recovery_ok(pre["recovery"])
        out["recovery_cooldown_verdict"] = rec_note
        if abort and not args.postcheck_only:
            out["verdict"] = "BLOCKED_PRECHECK"
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(to_jsonable(out), ensure_ascii=False, indent=2))
            return 3

        orders_before = pre["orders_count"]
        exec_before = pre["exec_count"]
        live_before = pre["account"]["live"]
        arm_before = pre["account"]["arm"]
        arm_exp_before = pre["account"]["arm_expires_at"]
        tick_before = int(
            ((pre.get("trading_scheduler") or {}).get("control") or {}).get(
                "tick_count"
            )
            or 0
        )

    if not args.postcheck_only:
        payload = {
            "reason": REASON,
            "correlation_id": correlation_id,
            "user_broker_account_id": UBA,
            "min_arm_remaining_seconds": MIN_ARM_REMAINING,
        }
        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{BASE}/api/v1/admin/trading-scheduler/start",
                headers={**headers, "Content-Type": "application/json"},
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
            print(json.dumps(to_jsonable(out), ensure_ascii=False, indent=2))
            return 4
        body = resp.json()
        if body.get("scheduler_changed") or (
            body.get("actual_state") == "RUNNING"
            and not pre["trading_scheduler"].get("running")
        ):
            out["mutations"]["scheduler_start"] = 1

    # PHASE 6 — 관찰 (heartbeat 10초 → 최소 2 tick 목표)
    observe_s = max(15, int(args.observe_seconds))
    samples: list[dict[str, Any]] = []
    t0 = time.time()
    while time.time() - t0 < observe_s:
        with httpx.Client(timeout=15.0) as http:
            st = http.get(
                f"{BASE}/api/v1/admin/trading-scheduler/status",
                headers=headers,
            )
            st.raise_for_status()
            samples.append(st.json())
        time.sleep(5)
    out["observation"] = {
        "seconds": observe_s,
        "samples": len(samples),
        "tick_before": tick_before,
        "tick_after": int(
            ((samples[-1].get("control") or {}).get("tick_count") or 0)
            if samples
            else 0
        ),
        "last_tick_at": (
            (samples[-1].get("control") or {}).get("last_tick_at")
            if samples
            else None
        ),
        "strategy_active_scopes_any": any(
            int(s.get("strategy_active_scopes") or 0) > 0 for s in samples
        ),
        "execution_runner_running_any": any(
            s.get("execution_runner_running") for s in samples
        ),
        "order_path_idle_all": all(
            s.get("order_path_idle") is not False for s in samples
        )
        if samples
        else False,
        "running_all": all(s.get("running") for s in samples)
        if samples
        else False,
    }

    with factory() as session:
        post = _db_snapshot(session, admin_key)
        out["after"] = post
        audit_row = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.event_type == "TRADING_SCHEDULER_STARTED")
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
            "arm_ttl_refreshed": (
                post["account"]["arm_expires_at"] != arm_exp_before
            ),
        }

    tick_delta = (
        out["observation"]["tick_after"] - out["observation"]["tick_before"]
    )
    fail: list[str] = []
    if not post["account"]["live"]:
        fail.append("live_off")
    if not post["account"]["arm"]:
        fail.append("arm_off")
    if out["deltas"]["live_changed"]:
        fail.append("live_changed")
    if out["deltas"]["arm_changed"]:
        fail.append("arm_changed")
    if out["deltas"]["arm_ttl_refreshed"]:
        fail.append("arm_ttl_refreshed")
    ts_after = post.get("trading_scheduler") or {}
    if ts_after.get("desired_state") != "RUN":
        fail.append(f"desired={ts_after.get('desired_state')}")
    if ts_after.get("actual_state") != "RUNNING":
        fail.append(f"actual={ts_after.get('actual_state')}")
    if int(ts_after.get("strategy_active_scopes") or 0) > 0:
        fail.append("strategy_scopes_active")
    if ts_after.get("execution_runner_running"):
        fail.append("execution_runner_running")
    if out["observation"].get("strategy_active_scopes_any"):
        fail.append("strategy_scopes_during_observe")
    if out["observation"]["execution_runner_running_any"]:
        fail.append("execution_runner_during_observe")
    if tick_delta < 2:
        fail.append(f"ticks<{2}:{tick_delta}")
    if out["deltas"]["orders"] != 0:
        fail.append("order_insert")
    if out["deltas"]["executions"] != 0:
        fail.append("exec_insert")
    if post["broker_open"] != 0:
        fail.append("broker_open")
    if any(int(v or 0) > 0 for v in (post["blocking"] or {}).values()):
        fail.append("blocking")
    if out["api_calls"] != 1:
        fail.append("api_calls!=1")

    out["fail_reasons"] = fail
    out["verdict"] = (
        "PASS_SCHEDULER_STARTED_NO_ORDER" if not fail else "FAIL_POSTCHECK"
    )
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
    return 0 if out["verdict"] == "PASS_SCHEDULER_STARTED_NO_ORDER" else 5


if __name__ == "__main__":
    raise SystemExit(main())
