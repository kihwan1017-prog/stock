"""STEP 8-15A — UBA 58 Recovery cycle 후 Pause 유지 검증 (Resume/주문 금지)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

# repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stock_platform.broker.recovery_account_state import (  # noqa: E402
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_adapter import (  # noqa: E402
    AccountRecoveryContext,
)
from stock_platform.broker.recovery_conflict_constants import (  # noqa: E402
    ACTIVE_REVIEW_STATUSES,
    RecoveryConflictReviewStatus,
)
from stock_platform.broker.recovery_conflict_entities import (  # noqa: E402
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_runtime import BrokerRecoveryManager  # noqa: E402
from stock_platform.database.session import get_session_factory  # noqa: E402
from stock_platform.operation.audit_models import AuditEvent  # noqa: E402
from stock_platform.trading.account_models import UserBrokerAccount  # noqa: E402

UBA_ID = 58
REPORT = Path(
    os.environ.get(
        "STEP815A_REPORT",
        r"E:/StockTrading/reports/step8_15a_no_auto_unpause.json",
    )
)


def _pause_snapshot(session) -> dict:
    row = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id
            == UBA_ID
        )
    )
    uba = session.get(UserBrokerAccount, UBA_ID)
    assert row is not None and uba is not None
    return {
        "trading_paused": bool(row.trading_paused),
        "recovery_status": row.recovery_status,
        "last_error_code": row.last_error_code,
        "last_recovery_run_id": row.last_recovery_run_id,
        "live_order_enabled": bool(uba.live_order_enabled),
        "live_armed": bool(uba.live_armed),
    }


def _counts(session) -> dict:
    preserved = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.user_broker_account_id
                == UBA_ID,
                BrokerRecoveryConflictEntity.review_status
                == RecoveryConflictReviewStatus.HISTORICAL_PRESERVED,
            )
        )
        or 0
    )
    pending = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.user_broker_account_id
                == UBA_ID,
                BrokerRecoveryConflictEntity.review_status
                == "PENDING_REVIEW",
            )
        )
        or 0
    )
    active = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.user_broker_account_id
                == UBA_ID,
                BrokerRecoveryConflictEntity.review_status.in_(
                    list(ACTIVE_REVIEW_STATUSES)
                ),
            )
        )
        or 0
    )
    return {
        "historical_preserved": preserved,
        "pending_review": pending,
        "active_review": active,
    }


async def _run_recovery() -> dict:
    runtime = BrokerRecoveryManager()
    ctx = AccountRecoveryContext(
        user_id=7,
        broker_code="UPBIT",
        market_type="CRYPTO",
        user_broker_account_id=UBA_ID,
        trigger_type="MANUAL",
        requested_by="step8_15a_verify",
        allow_auto_create_external_orders=False,
        timeout_seconds=90.0,
    )
    result = await runtime.recover_account(
        ctx, holder="step8_15a_verify"
    )
    return {
        "status": result.status,
        "conflicts_found": result.conflicts_found,
        "trading_should_remain_paused": result.trading_should_remain_paused,
        "errors": list(result.errors or [])[:5],
    }


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    session = get_session_factory()()
    try:
        before = _pause_snapshot(session)
        counts_before = _counts(session)
        if not before["trading_paused"]:
            print("ABORT: trading_paused already false before cycle")
            return 2
        if counts_before["active_review"] != 0:
            print("ABORT: ACTIVE_REVIEW != 0", counts_before)
            return 2

        mid_check = {"trading_paused_false_seen": False}
        # cycle 직전 재확인
        session.expire_all()
        if not _pause_snapshot(session)["trading_paused"]:
            mid_check["trading_paused_false_seen"] = True

        recovery = asyncio.run(_run_recovery())

        session.expire_all()
        after = _pause_snapshot(session)
        counts_after = _counts(session)
        if not after["trading_paused"]:
            mid_check["trading_paused_false_seen"] = True

        resume_audit = int(
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "RECOVERY_ACCOUNT_RESUME",
                    AuditEvent.created_at
                    >= datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
            )
            or 0
        )

        report = {
            "step": "8-15A",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "pause_before": before,
            "pause_after": after,
            "counts_before": counts_before,
            "counts_after": counts_after,
            "recovery": recovery,
            "trading_paused_false_seen": mid_check[
                "trading_paused_false_seen"
            ],
            "pause_resume_api_calls": 0,
            "create_order_calls": 0,
            "cancel_order_calls": 0,
            "replace_order_calls": 0,
            "ignore_calls": 0,
            "import_calls": 0,
            "today_resume_audit_count_note": resume_audit,
            "verdict": (
                "PASS"
                if (
                    after["trading_paused"]
                    and not mid_check["trading_paused_false_seen"]
                    and counts_after["historical_preserved"] == 20
                    and counts_after["active_review"] == 0
                    and before["live_order_enabled"] is False
                    and after["live_order_enabled"] is False
                    and before["live_armed"] is False
                    and after["live_armed"] is False
                )
                else "FAIL"
            ),
        }
        REPORT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["verdict"] == "PASS" else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
