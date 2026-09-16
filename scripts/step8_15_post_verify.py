"""STEP 8-15 사후 검증 — Preserve 후 Scheduler/Dashboard/Pause (상태 변경 최소화)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from stock_platform.broker import recovery_entities as _recovery_entities  # noqa: F401
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_settings_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_adapter import AccountRecoveryContext
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
    RecoveryConflictReviewStatus,
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
from stock_platform.common.json_safe import dumps_jsonable, to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.step8_15_preserve_guard import (
    PRESERVE_REASON,
    STEP8_15_PRESERVE_ALLOWLIST,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
TARGET = sorted(STEP8_15_PRESERVE_ALLOWLIST)
REPORT = Path(r"E:\StockTrading\reports\step8_15_preserve_history.json")
BASE = "http://127.0.0.1:8000"


def main() -> int:
    session = get_session_factory()()
    settings = get_settings()
    headers = {"X-Admin-API-Key": settings.admin_api_key.strip()}
    out: dict[str, Any] = {
        "step": "8-15",
        "phase": "post_verify",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "preserve_reason": PRESERVE_REASON,
        "target_ids": TARGET,
        "create_order_calls": 0,
        "cancel_order_calls": 0,
        "replace_order_calls": 0,
        "approve_import_calls": 0,
        "ignore_calls": 0,
        "pause_resume_calls": 0,
    }
    try:
        rows = list(
            session.scalars(
                select(BrokerRecoveryConflictEntity).where(
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                        TARGET
                    )
                )
            ).all()
        )
        out["preserve_success"] = sum(
            1
            for r in rows
            if r.review_status
            == RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
        )
        out["preserve_failed"] = 0
        out["preserve_skipped"] = 0
        out["target_historical_preserved"] = out["preserve_success"]
        out["target_pending_review"] = sum(
            1
            for r in rows
            if r.review_status == RecoveryConflictReviewStatus.PENDING_REVIEW
        )
        out["results"] = [
            {
                "conflict_id": int(r.broker_recovery_conflict_id),
                "after_status": r.review_status,
                "after_resolution": r.resolution_type,
                "resolved_by": r.resolved_by,
                "note": r.resolution_note,
                "masked_uuid": r.external_order_id_masked,
                "remote_snapshot_kept": bool(r.remote_snapshot),
            }
            for r in sorted(rows, key=lambda x: int(x.broker_recovery_conflict_id))
        ]

        active = BrokerRecoveryConflictService(session).count_active_for_uba(UBA)
        out["active_review"] = active
        pending = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id == UBA,
                    BrokerRecoveryConflictEntity.review_status
                    == RecoveryConflictReviewStatus.PENDING_REVIEW,
                )
            )
            or 0
        )
        on_hold = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id == UBA,
                    BrokerRecoveryConflictEntity.review_status
                    == RecoveryConflictReviewStatus.ON_HOLD,
                )
            )
            or 0
        )
        out["pending_review_uba"] = pending
        out["on_hold_uba"] = on_hold
        out["dashboard"] = {
            "review_required": active,
            "historical_preserved": out["preserve_success"],
            "critical_conflict_alert_expected": active > 0,
        }

        audits = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.event_type
                    == "RECOVERY_CONFLICT_HISTORY_PRESERVED"
                )
                .order_by(AuditEvent.audit_event_id.desc())
                .limit(100)
            ).all()
        )
        by_id = {
            int(a.detail["conflict_id"]): a
            for a in audits
            if isinstance(a.detail, dict) and a.detail.get("conflict_id") in TARGET
        }
        out["audit"] = {
            "count_for_targets": len(by_id),
            "missing_ids": [i for i in TARGET if i not in by_id],
            "samples": [
                {
                    "audit_event_id": int(by_id[i].audit_event_id),
                    "conflict_id": i,
                    "actor": by_id[i].actor,
                    "reason": by_id[i].detail.get("reason"),
                    "broker_uuid_masked": by_id[i].detail.get(
                        "broker_uuid_masked"
                    ),
                    "before_status": by_id[i].detail.get("before_status"),
                    "after_status": by_id[i].detail.get("after_status"),
                    "resolution_type": by_id[i].detail.get("resolution_type"),
                }
                for i in TARGET[:3]
                if i in by_id
            ],
        }

        pause = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
            )
        )
        uba = session.get(UserBrokerAccount, UBA)
        out["pause_after"] = {
            "trading_paused": bool(pause.trading_paused) if pause else False,
            "recovery_status": pause.recovery_status if pause else None,
            "last_error_code": pause.last_error_code if pause else None,
            "last_error_summary": (
                (pause.last_error_summary or "")[:200] if pause else None
            ),
            "last_recovery_run_id": (
                pause.last_recovery_run_id if pause else None
            ),
        }
        out["live_arm"] = {
            "live_order_enabled": bool(uba.live_order_enabled) if uba else None,
            "live_armed": bool(uba.live_armed) if uba else None,
        }

        order_client = UpbitOrderRestClient(
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
        out["broker_open"] = len(
            order_client.list_orders(state="wait", limit=50) or []
        )
        db_open = 0
        for o in session.scalars(
            select(TradingOrderEntity).where(
                TradingOrderEntity.user_broker_account_id == UBA
            )
        ):
            if str(o.status_code or "").upper() in {
                "NEW",
                "OPEN",
                "PARTIAL",
                "SUBMITTED",
                "PENDING",
                "ACCEPTED",
                "SUBMISSION_UNKNOWN",
                "CANCEL_PENDING",
                "REPLACE_PENDING",
            }:
                db_open += 1
        out["db_open"] = db_open

        readiness = collect_scheduler_readiness(session)
        out["scheduler"] = readiness.to_dict()

        with httpx.Client(timeout=15.0) as client:
            rs = client.get(
                f"{BASE}/api/v1/admin/recovery/scheduler/status",
                headers=headers,
            )
            out["recovery_scheduler"] = (
                rs.json() if rs.status_code == 200 else {"http": rs.status_code}
            )

        # Scheduler regenerate check (timeout 90s)
        mgr = BrokerRecoveryManager()
        ctxs = mgr.discover_accounts(
            session, broker_code="UPBIT", user_broker_account_id=UBA
        )
        if ctxs:
            c0 = ctxs[0]
            ctx = AccountRecoveryContext(
                user_id=c0.user_id,
                broker_code=c0.broker_code,
                market_type=c0.market_type,
                paper_account_id=c0.paper_account_id,
                user_broker_account_id=c0.user_broker_account_id,
                account_ref_masked=c0.account_ref_masked,
                trigger_type="MANUAL",
                requested_by="admin:step8_15_verify",
                allow_auto_create_external_orders=False,
                timeout_seconds=45.0,
            )

            async def _run():
                return await asyncio.wait_for(
                    mgr.recover_account(ctx), timeout=90.0
                )

            try:
                result = asyncio.run(_run())
                dumps_jsonable(result.to_dict())
                out["recovery_cycle"] = {
                    "status": result.status,
                    "conflicts_found": result.conflicts_found,
                    "decimal_ok": True,
                    "deposit": (
                        (result.to_dict().get("detail") or {})
                        .get("account_sync", {})
                        .get("deposit_amount")
                    ),
                }
            except Exception as exc:  # noqa: BLE001
                out["recovery_cycle"] = {
                    "error": str(exc)[:300],
                    "decimal_ok": None,
                }

        session.expire_all()
        pending_targets = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                        TARGET
                    ),
                    BrokerRecoveryConflictEntity.review_status
                    == RecoveryConflictReviewStatus.PENDING_REVIEW,
                )
            )
            or 0
        )
        preserved_targets = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                        TARGET
                    ),
                    BrokerRecoveryConflictEntity.review_status
                    == RecoveryConflictReviewStatus.HISTORICAL_PRESERVED,
                )
            )
            or 0
        )
        out["scheduler_verify"] = {
            "regenerated_pending": pending_targets,
            "target_preserved_after_cycle": preserved_targets,
        }
        run = session.scalar(
            select(BrokerRecoveryRunEntity)
            .order_by(BrokerRecoveryRunEntity.broker_recovery_run_id.desc())
            .limit(1)
        )
        out["latest_run"] = {
            "id": run.broker_recovery_run_id if run else None,
            "status": run.status_code if run else None,
        }
        pause2 = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
            )
        )
        out["pause_final"] = {
            "trading_paused": bool(pause2.trading_paused) if pause2 else False,
            "last_error_code": pause2.last_error_code if pause2 else None,
            "last_error_summary": (
                (pause2.last_error_summary or "")[:200] if pause2 else None
            ),
        }
        out["abort_reason"] = None
        if out["preserve_success"] != 20:
            out["abort_reason"] = "preserve_count_not_20"
        if pending_targets > 0:
            out["abort_reason"] = "scheduler_regenerated_pending"
        if active != 0:
            out["abort_reason"] = f"active_review={active}"

        REPORT.write_text(
            json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"WROTE {REPORT}")
        print(
            json.dumps(
                {
                    "preserve_success": out["preserve_success"],
                    "active_review": active,
                    "audit": out["audit"]["count_for_targets"],
                    "scheduler_verify": out["scheduler_verify"],
                    "pause": out["pause_final"],
                    "recovery_cycle": out.get("recovery_cycle"),
                    "abort_reason": out["abort_reason"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if out["abort_reason"] is None else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
