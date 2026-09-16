"""STEP 8-16 — UBA 58 Admin Account Trading Pause Resume (1회).

금지: LIVE/ARM/Trading Scheduler Resume/Runtime Resume/주문/Import/Ignore/DB UPDATE
"""

from __future__ import annotations

import asyncio
import json
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
from stock_platform.broker.recovery_adapter import AccountRecoveryContext
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
from stock_platform.broker.recovery_runtime import BrokerRecoveryManager
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.order.post_fill_verification_entities import (
    PostFillVerificationEntity,
)
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
BASE = "http://127.0.0.1:8000"
REASON = "RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED"
CORRELATION_ID = f"step8-16-resume-uba58-{uuid.uuid4().hex[:12]}"
REPORT = Path(r"E:\StockTrading\reports\step8_16_account_pause_resume.json")


def _pause_snap(session) -> dict[str, Any]:
    row = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
        )
    )
    uba = session.get(UserBrokerAccount, UBA)
    assert row is not None and uba is not None
    return {
        "trading_paused": bool(row.trading_paused),
        "recovery_status": row.recovery_status,
        "last_error_code": row.last_error_code,
        "last_error_summary": row.last_error_summary,
        "last_recovery_run_id": row.last_recovery_run_id,
        "updated_at": str(row.updated_at),
        "user_id": uba.user_id,
        "broker_code": uba.broker_code,
        "live_order_enabled": bool(uba.live_order_enabled),
        "live_armed": bool(uba.live_armed),
        "is_active": bool(uba.is_active),
    }


def _conflict_counts(session) -> dict[str, int]:
    out: dict[str, int] = {}
    for st in (
        "HISTORICAL_PRESERVED",
        "PENDING_REVIEW",
        "ON_HOLD",
        "IGNORED",
        "IMPORTED",
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
    return out


def _precheck(session, admin_key: str) -> dict[str, Any]:
    pause = _pause_snap(session)
    counts = _conflict_counts(session)
    blocking = BrokerRecoveryConflictService(
        session
    ).count_blocking_orders_for_uba(UBA)
    run = None
    if pause["last_recovery_run_id"]:
        entity = session.get(
            BrokerRecoveryRunEntity, pause["last_recovery_run_id"]
        )
        if entity is not None:
            run = {
                "id": entity.broker_recovery_run_id,
                "status": entity.status_code,
                "trigger": entity.trigger_type,
                "conflicts": entity.conflicts_found,
                "finished_at": str(entity.finished_at),
            }
    try:
        kill = bool(KillSwitchService(session).is_active())
    except Exception as exc:  # noqa: BLE001
        kill = True
        kill_err = str(exc)
    else:
        kill_err = None
    cred = "OK"
    try:
        BrokerCredentialVaultService(session).assert_live_order_allowed(
            UBA, broker_code="UPBIT"
        )
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

    with httpx.Client(timeout=20.0) as http:
        sched = http.get(
            f"{BASE}/api/v1/admin/recovery/scheduler/status",
            headers={"X-Admin-API-Key": admin_key},
        )
        sched.raise_for_status()
        recovery_sched = sched.json()

    trading = collect_scheduler_readiness()

    # last_error_code 의미 판정
    last_err = pause.get("last_error_code")
    if last_err == "manual_review_required":
        if (
            pause["recovery_status"] == "SUCCESS"
            and counts["ACTIVE_REVIEW"] == 0
            and (run or {}).get("status") == "SUCCESS"
        ):
            err_class = "STALE_METADATA_OR_PAST"
            err_note = (
                "과거 Pause 복구 잔존. 최근 run SUCCESS·ACTIVE_REVIEW=0 이므로 "
                "현재 활성 오류 아님 → Resume 사전조건 통과 가능"
            )
        else:
            err_class = "ACTIVE_ERROR"
            err_note = "활성 오류 가능 — Resume 중단"
    elif last_err:
        err_class = "OTHER"
        err_note = str(last_err)
    else:
        err_class = "NONE"
        err_note = None

    abort_reasons: list[str] = []
    if not pause["trading_paused"]:
        abort_reasons.append("already_not_paused")
    if counts["HISTORICAL_PRESERVED"] != 20:
        abort_reasons.append("historical_preserved!=20")
    if counts["PENDING_REVIEW"] != 0:
        abort_reasons.append("pending_review!=0")
    if counts["ON_HOLD"] != 0:
        abort_reasons.append("on_hold!=0")
    if counts["ACTIVE_REVIEW"] != 0:
        abort_reasons.append("active_review!=0")
    if any(blocking.values()):
        abort_reasons.append(f"blocking={blocking}")
    if broker_open_n != 0:
        abort_reasons.append(f"broker_open={broker_open_n}")
    if pf_pending != 0:
        abort_reasons.append(f"post_fill_pending={pf_pending}")
    if kill:
        abort_reasons.append("kill_switch_active")
    if cred != "OK":
        abort_reasons.append(f"credential={cred}")
    if pause["live_order_enabled"] or pause["live_armed"]:
        abort_reasons.append("live_or_arm_on")
    if trading.trading_scheduler_desired_state != "PAUSE":
        abort_reasons.append("trading_desired!=PAUSE")
    if trading.trading_scheduler_actual_state != "PAUSED":
        abort_reasons.append("trading_actual!=PAUSED")
    if recovery_sched.get("desired_state") != "RUNNING":
        abort_reasons.append("recovery_desired!=RUNNING")
    actual = recovery_sched.get("actual_state")
    # STARTUP_COOLDOWN 은 기동 직후 정상 전이 — stale=false·running=true면 Resume 허용
    if actual not in {"RUNNING", "COOLDOWN"}:
        abort_reasons.append(f"recovery_actual={actual}")
    if (
        actual == "COOLDOWN"
        and recovery_sched.get("reason_code") not in {
            "STARTUP_COOLDOWN",
            None,
        }
        and recovery_sched.get("stale") is True
    ):
        abort_reasons.append("recovery_cooldown_unhealthy")
    if recovery_sched.get("running") is not True:
        abort_reasons.append("recovery_not_running")
    if recovery_sched.get("stale") is True:
        abort_reasons.append("recovery_stale")
    if (run or {}).get("status") != "SUCCESS":
        abort_reasons.append("last_run!=SUCCESS")
    if err_class == "ACTIVE_ERROR":
        abort_reasons.append("active_last_error")

    return {
        "pause": pause,
        "counts": counts,
        "blocking": blocking,
        "broker_open": broker_open_n,
        "post_fill_pending": pf_pending,
        "kill_switch": kill,
        "kill_err": kill_err,
        "credential": cred,
        "last_run": run,
        "last_error_class": err_class,
        "last_error_note": err_note,
        "recovery_scheduler": {
            "desired_state": recovery_sched.get("desired_state"),
            "actual_state": recovery_sched.get("actual_state"),
            "running": recovery_sched.get("running"),
            "stale": recovery_sched.get("stale"),
            "last_error_code": recovery_sched.get("last_error_code"),
            "last_success_at": recovery_sched.get("last_success_at"),
            "consecutive_failures": recovery_sched.get(
                "consecutive_failures"
            ),
        },
        "trading_scheduler": {
            "desired": trading.trading_scheduler_desired_state,
            "actual": trading.trading_scheduler_actual_state,
            "paused": trading.trading_scheduler_paused,
            "tracking_running": trading.tracking_scheduler_running,
            "post_fill_running": trading.post_fill_scheduler_running,
        },
        "abort_reasons": abort_reasons,
        "payload": {
            "uba_id": UBA,
            "reason": REASON,
            "correlation_id": CORRELATION_ID,
        },
    }


def main() -> int:
    settings = get_settings()
    admin_key = (settings.admin_api_key or "").strip()
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY required")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    session = get_session_factory()()
    report: dict[str, Any] = {
        "step": "8-16",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "resume_api_calls": 0,
        "create_order_calls": 0,
        "cancel_order_calls": 0,
        "replace_order_calls": 0,
        "import_calls": 0,
        "ignore_calls": 0,
        "runtime_resume_calls": 0,
        "trading_scheduler_resume_calls": 0,
        "live_changed": False,
        "arm_changed": False,
    }
    try:
        pre = _precheck(session, admin_key)
        report["precheck"] = to_jsonable(pre)
        print("PRECHECK_PAYLOAD", json.dumps(pre["payload"], ensure_ascii=False))
        print(
            "PRECHECK_ABORT",
            pre["abort_reasons"],
            "err_class",
            pre["last_error_class"],
        )
        if pre["abort_reasons"]:
            report["verdict"] = "ABORT"
            report["abort_reasons"] = pre["abort_reasons"]
            REPORT.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return 2

        body = {
            "reason": REASON,
            "correlation_id": CORRELATION_ID,
        }
        with httpx.Client(timeout=30.0) as http:
            resp = http.post(
                f"{BASE}/api/v1/admin/recovery/accounts/{UBA}/resume",
                headers={
                    "X-Admin-API-Key": admin_key,
                    "Content-Type": "application/json",
                },
                json=body,
            )
        report["resume_api_calls"] = 1
        report["resume_http_status"] = resp.status_code
        try:
            report["resume_response"] = resp.json()
        except Exception:  # noqa: BLE001
            report["resume_response"] = {"text": resp.text[:500]}
        if resp.status_code >= 400:
            report["verdict"] = "FAIL"
            report["resume_ok"] = False
            REPORT.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("RESUME_FAIL", resp.status_code, resp.text[:500])
            return 1

        session.expire_all()
        after = _pause_snap(session)
        counts_after = _conflict_counts(session)
        trading_after = collect_scheduler_readiness()
        aud = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.event_type == "RECOVERY_ACCOUNT_RESUME",
            )
            .order_by(AuditEvent.audit_event_id.desc())
            .limit(1)
        )
        audit_detail = None
        if aud is not None:
            audit_detail = {
                "audit_event_id": aud.audit_event_id,
                "actor": aud.actor,
                "event_type": aud.event_type,
                "detail": getattr(aud, "detail", None),
                "created_at": str(getattr(aud, "created_at", None)),
            }

        # PHASE 5 — Resume 후 Recovery 1회 (주문/스케줄러 비활성 확인 후)
        recovery_after: dict[str, Any] | None = None
        if (
            not after["live_order_enabled"]
            and not after["live_armed"]
            and trading_after.trading_scheduler_actual_state == "PAUSED"
            and not after["trading_paused"]
        ):
            mgr = BrokerRecoveryManager()
            ctx = AccountRecoveryContext(
                user_id=int(after["user_id"]),
                broker_code="UPBIT",
                market_type="CRYPTO",
                user_broker_account_id=UBA,
                trigger_type="MANUAL",
                requested_by="admin:step8_16_post_resume_safety",
                allow_auto_create_external_orders=False,
                timeout_seconds=60.0,
            )

            async def _run():
                return await mgr.recover_account(
                    ctx, holder="step8_16_post_resume"
                )

            result = asyncio.run(_run())
            session.expire_all()
            pause_after_recovery = _pause_snap(session)
            recovery_after = {
                "status": result.status,
                "conflicts_found": result.conflicts_found,
                "trading_paused_after": pause_after_recovery[
                    "trading_paused"
                ],
                "live_after": pause_after_recovery["live_order_enabled"],
                "arm_after": pause_after_recovery["live_armed"],
            }
            after = pause_after_recovery

        report["after"] = after
        report["counts_after"] = counts_after
        report["trading_after"] = {
            "desired": trading_after.trading_scheduler_desired_state,
            "actual": trading_after.trading_scheduler_actual_state,
            "paused": trading_after.trading_scheduler_paused,
            "tracking_running": trading_after.tracking_scheduler_running,
            "post_fill_running": trading_after.post_fill_scheduler_running,
        }
        report["audit"] = audit_detail
        report["correlation_id"] = CORRELATION_ID
        report["reason"] = REASON
        report["recovery_post_resume"] = recovery_after
        report["resume_ok"] = True
        ok = (
            after["trading_paused"] is False
            and counts_after["HISTORICAL_PRESERVED"] == 20
            and counts_after["ACTIVE_REVIEW"] == 0
            and after["live_order_enabled"] is False
            and after["live_armed"] is False
            and trading_after.trading_scheduler_actual_state == "PAUSED"
            and (
                recovery_after is None
                or (
                    recovery_after.get("trading_paused_after") is False
                    and recovery_after.get("status") == "SUCCESS"
                )
            )
        )
        report["verdict"] = "PASS" if ok else "FAIL"
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
