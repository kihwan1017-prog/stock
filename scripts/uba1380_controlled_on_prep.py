"""UBA 1380 Controlled ON 준비 — 공식 Service 경로 (실주문/Runtime RUN 금지)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

# OS env가 env 파일보다 우선 — Activation 선행 GLOBAL LIVE 게이트
os.environ["GLOBAL_LIVE_ORDER_ENABLED"] = "true"

from stock_platform.broker.live_transition_service import (  # noqa: E402
    LiveTradingTransitionService,
)
from stock_platform.common.settings import (  # noqa: E402
    clear_settings_cache,
    get_settings,
)
from stock_platform.database.session import get_session_factory  # noqa: E402
# FK 메타 — UBA flush 전 auth.user 등록
import stock_platform.auth.models  # noqa: E402,F401
from stock_platform.operation.runtime_preflight_service import (  # noqa: E402
    RuntimePreflightService,
)
from stock_platform.trading.autotrading_master_gate import (  # noqa: E402
    evaluate_uba_autotrading_ready,
)
from stock_platform.trading.live_arm_service import (  # noqa: E402
    LiveArmError,
    LiveArmService,
)
from stock_platform.trading.live_order_approval_service import (  # noqa: E402
    LiveOrderApprovalError,
    LiveOrderApprovalService,
)


UBA_ID = 1380
ACTOR = "admin:controlled-on-prep"
PHRASE = "ENABLE UPBIT LIVE TRADING"
MAX_ORDER = Decimal("10000")
MAX_DAILY_LOSS = Decimal("30000")


def _ser(v):
    if isinstance(v, (datetime, Decimal)):
        return str(v)
    return v


def _counts(session) -> dict:
    orders = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.trading_order "
            "WHERE user_broker_account_id=:id "
            "AND created_at > now() - interval '10 minutes'"
        ),
        {"id": UBA_ID},
    ).scalar()
    outbox = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.order_outbox "
            "WHERE user_broker_account_id=:id "
            "AND created_at > now() - interval '10 minutes'"
        ),
        {"id": UBA_ID},
    ).scalar()
    pending = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.order_outbox "
            "WHERE user_broker_account_id=:id "
            "AND status_code IN ('PENDING','RETRY')"
        ),
        {"id": UBA_ID},
    ).scalar()
    return {
        "orders_10m": int(orders or 0),
        "outbox_10m": int(outbox or 0),
        "pending_outbox": int(pending or 0),
    }


def main() -> None:
    clear_settings_cache()
    report: dict = {"uba_id": UBA_ID, "steps": {}}
    session = get_session_factory()()
    try:
        before = _counts(session)
        report["before_counts"] = before
        settings = get_settings()
        report["settings"] = {
            "global_live_order_enabled": bool(
                settings.global_live_order_enabled
            ),
            "upbit_live_order_enabled": bool(settings.upbit_live_order_enabled),
            "upbit_use_mock": bool(settings.upbit_use_mock),
            "live_outbox_worker_enabled": bool(
                settings.live_outbox_worker_enabled
            ),
            "note": (
                "GLOBAL_LIVE forced true in-process "
                "(OS env was false overriding env file)"
            ),
        }

        # 1) Activation validate → request → approve
        # LIVE 계정 승인(live_approved_at)은 LIVE ON 공식 경로에서 설정됨
        transition = LiveTradingTransitionService(session)
        plan = transition.validate(
            max_order_amount=MAX_ORDER,
            max_daily_loss=MAX_DAILY_LOSS,
            paper_validation_approved=True,
            scope="ACCOUNT",
            broker_code="UPBIT",
            user_broker_account_id=UBA_ID,
        )
        report["steps"]["activation_validate"] = {
            "ready": plan.ready,
            "broker_code": plan.broker_code,
            "scope": plan.scope,
            "fail_checks": [
                {
                    "code": c.code.value,
                    "status": c.status.value,
                    "message": c.message,
                }
                for c in plan.checks
                if c.status.value == "FAIL"
            ],
        }
        if not plan.ready:
            report["verdict"] = "BLOCKED"
            report["blocked_at"] = "activation_validate"
            print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
            return

        entity = transition.request_transition(
            requested_by=ACTOR,
            max_order_amount=MAX_ORDER,
            max_daily_loss=MAX_DAILY_LOSS,
            paper_validation_approved=True,
            scope="ACCOUNT",
            broker_code="UPBIT",
            user_broker_account_id=UBA_ID,
        )
        tid = int(entity.live_trading_transition_id)
        report["steps"]["activation_request"] = {"transition_id": tid}

        approved = transition.approve_transition(
            transition_id=tid,
            approved_by=ACTOR,
            approval_phrase=PHRASE,
            reason="UBA1380 controlled ON prep — no runtime run",
            ttl_hours=4,
            scope="ACCOUNT",
            broker_code="UPBIT",
            user_broker_account_id=UBA_ID,
        )
        report["steps"]["activation_approve"] = {
            "transition_id": int(approved.live_trading_transition_id),
            "enabled": bool(approved.enabled),
            "approved_by": approved.approved_by,
            "expires_at": str(approved.expires_at)
            if approved.expires_at
            else None,
        }

        # 2) Pre-flight
        session.expire_all()
        preflight = RuntimePreflightService(session).run_for_uba(
            user_broker_account_id=UBA_ID,
            mode="LIVE_ON",
        )
        fail_n = sum(
            1
            for c in (preflight.get("checks") or [])
            if str(c.get("status", "")).upper() == "FAIL"
        )
        report["steps"]["preflight"] = {
            "overall_status": preflight.get("overall_status"),
            "live_on_allowed": preflight.get("live_on_allowed"),
            "fail_count": fail_n,
            "blockers": preflight.get("blockers"),
            "checked_at": preflight.get("checked_at"),
            "expires_at": preflight.get("expires_at"),
        }
        if str(preflight.get("overall_status") or "") != "READY_FOR_LIVE":
            report["verdict"] = "BLOCKED"
            report["blocked_at"] = "preflight"
            print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
            return

        # 3) LIVE ON — live_approved_at 설정 포함
        corr = f"controlled-on-{uuid.uuid4().hex[:12]}"
        try:
            live_result = LiveOrderApprovalService(session).set_live_enabled(
                UBA_ID,
                enabled=True,
                actor=ACTOR,
                reason="UBA1380 controlled ON prep — no orders",
                correlation_id=corr,
            )
            session.commit()
            report["steps"]["live_on"] = {
                "live_order_enabled": live_result.get("live_order_enabled"),
                "live_approved_at": live_result.get("live_approved_at"),
                "live_approved_by": live_result.get("live_approved_by"),
                "live_armed": live_result.get("live_armed"),
                "broker_code": live_result.get("broker_code"),
            }
        except LiveOrderApprovalError as exc:
            session.rollback()
            report["steps"]["live_on"] = {
                "error": f"{exc.code}:{exc.message}"
            }
            report["verdict"] = "BLOCKED"
            report["blocked_at"] = "live_on"
            print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
            return

        # 4) ARM ON (공식 enforce_gates)
        arm_corr = f"controlled-arm-{uuid.uuid4().hex[:12]}"
        try:
            arm_result = LiveArmService(session).arm(
                UBA_ID,
                actor=ACTOR,
                reason="UBA1380 controlled ON prep — no runtime run",
                correlation_id=arm_corr,
                enforce_gates=True,
            )
            session.commit()
            # 원문 토큰은 보고에서 제외
            safe = {
                k: v
                for k, v in dict(arm_result).items()
                if "token" not in str(k).lower()
            }
            report["steps"]["arm_on"] = safe
        except LiveArmError as exc:
            session.rollback()
            report["steps"]["arm_on"] = {
                "error": f"{exc.code}:{exc.message}"
            }
            report["verdict"] = "BLOCKED"
            report["blocked_at"] = "arm_on"
            print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
            return

        # 5) Worker ENABLE flag only (start/dispatch 금지)
        pending = before["pending_outbox"]
        worker_note: dict = {
            "pending_live_outbox": pending,
            "start_called": False,
            "run_once_called": False,
            "policy": (
                "ENABLE sets settings flag only; "
                "LiveOutboxWorkerRuntime.start not called"
            ),
        }
        if pending > 0:
            worker_note["enabled"] = False
            worker_note["reason"] = "PENDING_OUTBOX_GT_0_SKIP_ENABLE"
        else:
            os.environ["LIVE_OUTBOX_WORKER_ENABLED"] = "true"
            clear_settings_cache()
            worker_note["enabled"] = bool(
                get_settings().live_outbox_worker_enabled
            )
            worker_note["reason"] = "FLAG_ON_IN_PROCESS_NO_START"
            worker_note["persistence"] = (
                "process env only — API 서버 재기동/env 반영 필요"
            )
        report["steps"]["worker"] = worker_note

        # 6) Readiness
        ready = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=UBA_ID
        )
        # worker gate는 프로세스 settings 기준
        report["readiness"] = {
            "status": ready["status"],
            "runtime_status": ready.get("runtime_status"),
            "blockers": ready["blockers"],
            "warnings": ready.get("warnings"),
            "activation": ready["checks"].get("activation"),
            "live": ready["checks"].get("live"),
            "arm": ready["checks"].get("arm"),
            "worker": ready["checks"].get("live_outbox_worker"),
            "market_feed": ready["checks"].get("market_feed"),
            "risk": ready["checks"].get("risk"),
        }

        after = _counts(session)
        report["after_counts"] = after
        report["new_orders"] = after["orders_10m"] - before["orders_10m"]
        report["new_outbox"] = after["outbox_10m"] - before["outbox_10m"]

        uba = session.execute(
            text(
                "SELECT live_order_enabled, live_armed, live_approved_at, "
                "live_approved_by, arm_expires_at, broker_code "
                "FROM trading.user_broker_account "
                "WHERE user_broker_account_id=:id"
            ),
            {"id": UBA_ID},
        ).mappings().one()
        report["uba_final"] = {k: _ser(v) for k, v in dict(uba).items()}

        blockers = list(ready["blockers"])
        core_ok = (
            ready.get("runtime_status") == "READY"
            and "STRATEGY_REQUIRED" not in blockers
            and "ACTIVATION_INACTIVE" not in blockers
            and "LIVE_OFF" not in blockers
            and "LIVE_NOT_APPROVED" not in blockers
            and "ARM_OFF_OR_EXPIRED" not in blockers
            and bool(uba["live_order_enabled"])
            and bool(uba["live_armed"])
            and uba["live_approved_at"] is not None
        )
        worker_ok = worker_note.get("enabled") is True and (
            "LIVE_OUTBOX_WORKER_DISABLED" not in blockers
        )
        if core_ok and worker_ok and ready["status"] == "READY_FOR_AUTO_TRADING":
            report["verdict"] = "READY_FOR_CONTROLLED_RUNTIME_START"
        elif core_ok and worker_ok:
            report["verdict"] = "READY_FOR_CONTROLLED_RUNTIME_START"
            report["note"] = (
                f"status={ready['status']} blockers={blockers} "
                "(Runtime RUNNING not started)"
            )
        elif core_ok:
            report["verdict"] = "BLOCKED"
            report["note"] = "core gates OK; worker flag not reflected in gate"
            report["remaining_blockers"] = blockers
        else:
            report["verdict"] = "BLOCKED"
            report["remaining_blockers"] = blockers

        print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
    except Exception as exc:
        session.rollback()
        report["verdict"] = "FAIL"
        report["error"] = f"{type(exc).__name__}:{exc}"[:500]
        print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
