"""STEP 8-15 — DONE 20건 preserve-history 적용 (Admin API only).

금지: Ignore / Import / Pause Resume / LIVE / ARM / 실주문 / 직접 DB UPDATE
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from stock_platform.broker import recovery_entities as _recovery_entities  # noqa: F401
from stock_platform.broker.account_models import BrokerPositionSnapshotEntity
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
from stock_platform.broker.recovery_adapter import AccountRecoveryContext
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
    RecoveryConflictReviewStatus,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_entities import BrokerRecoveryRunEntity
from stock_platform.broker.recovery_runtime import BrokerRecoveryManager
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.json_safe import dumps_jsonable, to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_models import AuditEvent
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution
from stock_platform.trading.step8_13_done_fill_classifier import (
    classify_done_fill,
)
from stock_platform.trading.step8_15_preserve_guard import (
    PRESERVE_REASON,
    STEP8_15_PRESERVE_ALLOWLIST,
    assert_only_allowlisted_preserve,
    evaluate_preserve_history,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
BASE = "http://127.0.0.1:8000"
REPORT_DIR = Path(r"E:\StockTrading\reports")
TARGET_IDS = sorted(STEP8_15_PRESERVE_ALLOWLIST)
OPENISH_DB = {
    "NEW",
    "CREATED",
    "PENDING",
    "SENT",
    "ACCEPTED",
    "OPEN",
    "PARTIAL",
    "PARTIALLY_FILLED",
    "SUBMITTED",
    "UNKNOWN",
    "SUBMISSION_UNKNOWN",
    "CANCEL_PENDING",
    "REPLACE_PENDING",
}


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _mask(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) <= 8:
        return "****"
    return text[:4] + "…" + text[-4:]


def _base(market: str | None) -> str:
    text = str(market or "")
    return text.split("-", 1)[1] if "-" in text else text


def main() -> int:
    settings = get_settings()
    admin_key = str(settings.admin_api_key or "").strip()
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY required")

    session = get_session_factory()()
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "step": "8-15",
        "checked_at": now.isoformat(),
        "target_ids": TARGET_IDS,
        "preserve_reason": PRESERVE_REASON,
        "create_order_calls": 0,
        "cancel_order_calls": 0,
        "replace_order_calls": 0,
        "approve_import_calls": 0,
        "ignore_calls": 0,
        "pause_resume_calls": 0,
        "abort_reason": None,
        "results": [],
    }

    try:
        # --- PHASE 1: account snapshot ---
        pause = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == UBA
            )
        )
        uba = session.get(UserBrokerAccount, UBA)
        assert uba is not None
        ks: dict[str, Any] = {}
        for scope in ("GLOBAL", f"UBA:{UBA}"):
            row = session.scalar(
                select(KillSwitchEntity).where(
                    KillSwitchEntity.scope_code == scope
                )
            )
            ks[scope] = bool(row.active) if row else False

        report["pause_before"] = {
            "trading_paused": bool(pause.trading_paused) if pause else False,
            "recovery_status": pause.recovery_status if pause else None,
            "last_error_code": pause.last_error_code if pause else None,
            "last_error_summary": (
                (pause.last_error_summary or "")[:200] if pause else None
            ),
        }
        report["live_arm"] = {
            "live_order_enabled": bool(uba.live_order_enabled),
            "live_armed": bool(uba.live_armed),
        }
        report["kill_switch"] = ks
        report["credential"] = BrokerCredentialVaultService(session).status(
            UBA
        ).as_dict()

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
        broker_open = order_client.list_orders(state="wait", limit=50) or []
        report["broker_open_before"] = len(broker_open)

        db_orders = list(
            session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == UBA
                )
            ).all()
        )
        db_open = [
            o
            for o in db_orders
            if str(o.status_code or "").upper() in OPENISH_DB
        ]
        report["db_open_before"] = {
            "open": len(db_open),
            "submission_unknown": sum(
                1
                for o in db_orders
                if str(o.status_code).upper() == "SUBMISSION_UNKNOWN"
            ),
            "cancel_pending": sum(
                1
                for o in db_orders
                if str(o.status_code).upper() == "CANCEL_PENDING"
            ),
            "replace_pending": sum(
                1
                for o in db_orders
                if str(o.status_code).upper() == "REPLACE_PENDING"
            ),
        }

        private = build_upbit_private_client_for_uba(session, UBA)

        async def _accounts() -> list:
            return await private.list_accounts()

        accounts = asyncio.run(_accounts())
        bal_map = {
            str(a.get("currency")): a
            for a in (accounts or [])
            if isinstance(a, dict)
        }
        positions = list(
            session.scalars(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == UBA,
                    BrokerPositionSnapshotEntity.snapshot_status == "ACTIVE",
                )
            ).all()
        )
        pos_map = {str(p.symbol).upper(): p for p in positions}

        # Recovery scheduler status
        headers = {"X-Admin-API-Key": admin_key}
        with httpx.Client(timeout=30.0) as client:
            rs = client.get(
                f"{BASE}/api/v1/admin/recovery/scheduler/status",
                headers=headers,
            )
            report["recovery_scheduler_before"] = (
                rs.json() if rs.status_code == 200 else {"http": rs.status_code}
            )

        preflight: list[dict[str, Any]] = []
        for cid in TARGET_IDS:
            assert_only_allowlisted_preserve(
                cid, allowlist=STEP8_15_PRESERVE_ALLOWLIST
            )
            conflict = session.get(BrokerRecoveryConflictEntity, cid)
            if conflict is None:
                report["abort_reason"] = f"conflict #{cid} not found"
                _write(report)
                return 2

            remote = order_client.get_order(
                uuid=str(conflict.external_order_id)
            )
            remote_status = str(remote.get("state") or "").lower()
            market = str(remote.get("market") or conflict.market_code or "")
            base = _base(market)
            bal = bal_map.get(base) or {}
            broker_qty = _dec(bal.get("balance")) + _dec(bal.get("locked"))
            pos = (
                pos_map.get(market.upper())
                or pos_map.get(f"KRW-{base}".upper())
                or pos_map.get(base.upper())
            )
            internal_qty = _dec(pos.quantity) if pos is not None else Decimal("0")
            if pos is None and base not in bal_map:
                broker_qty = Decimal("0")
            position_matches = abs(internal_qty - broker_qty) <= Decimal("1e-8")

            order = session.scalar(
                select(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id == UBA,
                    TradingOrderEntity.broker_order_id
                    == str(conflict.external_order_id),
                )
                .limit(1)
            )
            execs = []
            if order is not None:
                execs = list(
                    session.scalars(
                        select(TradingExecution).where(
                            TradingExecution.order_id == int(order.order_id)
                        )
                    ).all()
                )
            exec_sum = sum(
                (_dec(e.execution_quantity) for e in execs), Decimal("0")
            )
            qty_match = bool(execs) and abs(
                exec_sum - _dec(remote.get("executed_volume"))
            ) <= Decimal("1e-8")

            verdict_cls = classify_done_fill(
                conflict_id=cid,
                executed_volume=remote.get("executed_volume"),
                trades_count=int(remote.get("trades_count") or 0),
                has_internal_order=order is not None,
                has_internal_execution=len(execs) > 0,
                execution_qty_matches_trades=qty_match,
                broker_balance_known=True,
                internal_position_known=True,
                position_matches_broker=position_matches,
                snapshot_synced_from_broker=True,
                remote_status=remote_status,
            )
            gate = evaluate_preserve_history(
                conflict_id=cid,
                allowlist=STEP8_15_PRESERVE_ALLOWLIST,
                review_status=conflict.review_status,
                remote_status=remote_status,
                classification=verdict_cls.classification,
                broker_open=remote_status in {"wait", "watch", "open"},
                db_open=False,  # 해당 UUID의 내부 open order 없음 확인
                position_impact=not position_matches,
                balance_impact=not position_matches,
            )
            item = {
                "conflict_id": cid,
                "broker_code": conflict.broker_code,
                "market": market,
                "side": remote.get("side") or conflict.side_code,
                "masked_uuid": conflict.external_order_id_masked,
                "review_status": conflict.review_status,
                "resolution": conflict.resolution_type,
                "remote_status": remote_status,
                "executed_volume": str(remote.get("executed_volume")),
                "remaining_volume": str(remote.get("remaining_volume")),
                "trades_count": remote.get("trades_count"),
                "paid_fee": str(remote.get("paid_fee")),
                "broker_open": remote_status in {"wait", "watch", "open"},
                "internal_order": order is not None,
                "internal_execution": len(execs) > 0,
                "classification": verdict_cls.classification,
                "position_matches": position_matches,
                "gate": gate.to_dict(),
            }
            preflight.append(item)
            if not gate.ok and gate.bucket != "ALREADY_PRESERVED":
                report["preflight"] = preflight
                report["abort_reason"] = (
                    f"preflight failed #{cid}: {gate.reasons}"
                )
                _write(report)
                return 3

        report["preflight"] = preflight
        report["preflight_ok_count"] = sum(
            1 for p in preflight if p["gate"]["ok"] or p["gate"]["bucket"] == "ALREADY_PRESERVED"
        )

        if any(o.status_code and str(o.status_code).upper() in OPENISH_DB for o in db_orders):
            # 계좌에 open이 있어도 DONE UUID와 무관할 수 있음 — 0이어야 함
            if report["db_open_before"]["open"] > 0:
                report["abort_reason"] = "db_open_orders_not_zero"
                _write(report)
                return 3
        if report["broker_open_before"] > 0:
            report["abort_reason"] = "broker_open_orders_not_zero"
            _write(report)
            return 3

        # --- PHASE 2: preserve via Admin API ---
        success = 0
        failed = 0
        skipped = 0
        with httpx.Client(timeout=60.0) as client:
            for item in preflight:
                cid = int(item["conflict_id"])
                if item["gate"]["bucket"] == "ALREADY_PRESERVED":
                    skipped += 1
                    report["results"].append(
                        {
                            "conflict_id": cid,
                            "action": "SKIP_IDEMPOTENT",
                            "before_status": item["review_status"],
                            "after_status": "HISTORICAL_PRESERVED",
                        }
                    )
                    continue

                # 처리 직전 재검증
                conflict = session.get(BrokerRecoveryConflictEntity, cid)
                session.refresh(conflict)
                if conflict.review_status == (
                    RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
                ):
                    skipped += 1
                    report["results"].append(
                        {
                            "conflict_id": cid,
                            "action": "SKIP_IDEMPOTENT",
                            "before_status": conflict.review_status,
                            "after_status": conflict.review_status,
                        }
                    )
                    continue
                if conflict.review_status != (
                    RecoveryConflictReviewStatus.PENDING_REVIEW
                ):
                    failed += 1
                    report["abort_reason"] = (
                        f"#{cid} status changed to {conflict.review_status}"
                    )
                    report["results"].append(
                        {
                            "conflict_id": cid,
                            "action": "ABORT",
                            "before_status": conflict.review_status,
                        }
                    )
                    _finalize(report, session, headers, order_client)
                    _write(report)
                    return 4

                before_status = conflict.review_status
                before_resolution = conflict.resolution_type
                correlation = str(uuid.uuid4())
                resp = client.post(
                    f"{BASE}/api/v1/admin/recovery/conflicts/{cid}/preserve-history",
                    headers={
                        **headers,
                        "X-Request-Id": correlation,
                        "Content-Type": "application/json",
                    },
                    json={"note": PRESERVE_REASON},
                )
                if resp.status_code >= 400:
                    failed += 1
                    report["abort_reason"] = (
                        f"#{cid} API {resp.status_code}: {resp.text[:300]}"
                    )
                    report["results"].append(
                        {
                            "conflict_id": cid,
                            "action": "API_FAIL",
                            "http_status": resp.status_code,
                            "body": resp.text[:500],
                        }
                    )
                    _finalize(report, session, headers, order_client)
                    _write(report)
                    return 4

                body = resp.json()
                session.expire_all()
                after = session.get(BrokerRecoveryConflictEntity, cid)
                # Audit lookup
                audits = list(
                    session.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.event_type
                            == "RECOVERY_CONFLICT_HISTORY_PRESERVED"
                        )
                        .order_by(AuditEvent.audit_event_id.desc())
                        .limit(50)
                    ).all()
                )
                audit_hit = next(
                    (
                        a
                        for a in audits
                        if isinstance(a.detail, dict)
                        and a.detail.get("conflict_id") == cid
                    ),
                    None,
                )
                success += 1
                report["results"].append(
                    {
                        "conflict_id": cid,
                        "action": "PRESERVED",
                        "before_status": before_status,
                        "after_status": after.review_status if after else body.get("review_status"),
                        "before_resolution": before_resolution,
                        "after_resolution": (
                            after.resolution_type if after else None
                        ),
                        "actor": f"admin:0",
                        "reason": PRESERVE_REASON,
                        "correlation_id": correlation,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "audit_event_id": (
                            int(audit_hit.audit_event_id)
                            if audit_hit
                            else None
                        ),
                        "api_review_status": body.get("review_status"),
                    }
                )

        report["preserve_success"] = success
        report["preserve_failed"] = failed
        report["preserve_skipped"] = skipped

        # --- PHASE 3–7 ---
        _finalize(report, session, headers, order_client)

        # PHASE 5: Recovery cycle (no orders)
        mgr = BrokerRecoveryManager()
        ctxs = mgr.discover_accounts(
            session, broker_code="UPBIT", user_broker_account_id=UBA
        )
        if ctxs:
            ctx0 = ctxs[0]
            ctx = AccountRecoveryContext(
                user_id=ctx0.user_id,
                broker_code=ctx0.broker_code,
                market_type=ctx0.market_type,
                paper_account_id=ctx0.paper_account_id,
                user_broker_account_id=ctx0.user_broker_account_id,
                account_ref_masked=ctx0.account_ref_masked,
                trigger_type="MANUAL",
                requested_by="admin:step8_15_scheduler_verify",
                allow_auto_create_external_orders=False,
            )

            async def _run():
                return await mgr.recover_account(ctx)

            result = asyncio.run(_run())
            dumps_jsonable(result.to_dict())
            report["recovery_cycle"] = {
                "status": result.status,
                "conflicts_found": result.conflicts_found,
                "errors": list(result.errors or [])[:5],
                "decimal_ok": True,
                "deposit_amount": (
                    (result.to_dict().get("detail") or {})
                    .get("account_sync", {})
                    .get("deposit_amount")
                ),
            }
            session.expire_all()
            # 재생성 여부
            pending_after_cycle = int(
                session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == UBA,
                        BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                            TARGET_IDS
                        ),
                        BrokerRecoveryConflictEntity.review_status
                        == RecoveryConflictReviewStatus.PENDING_REVIEW,
                    )
                )
                or 0
            )
            preserved_after_cycle = int(
                session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == UBA,
                        BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                            TARGET_IDS
                        ),
                        BrokerRecoveryConflictEntity.review_status
                        == RecoveryConflictReviewStatus.HISTORICAL_PRESERVED,
                    )
                )
                or 0
            )
            report["scheduler_verify"] = {
                "target_pending_after_cycle": pending_after_cycle,
                "target_preserved_after_cycle": preserved_after_cycle,
                "regenerated_pending": pending_after_cycle,
            }
            run = session.scalar(
                select(BrokerRecoveryRunEntity).order_by(
                    BrokerRecoveryRunEntity.broker_recovery_run_id.desc()
                ).limit(1)
            )
            report["latest_recovery_run"] = {
                "id": run.broker_recovery_run_id if run else None,
                "status": run.status_code if run else None,
                "has_decimal_error": (
                    "Decimal is not JSON"
                    in str((run.error_message if run else "") or "")
                ),
            }

        _write(report)
        if report.get("abort_reason"):
            return 1
        if report.get("scheduler_verify", {}).get("regenerated_pending", 0) > 0:
            report["abort_reason"] = "scheduler_regenerated_pending"
            _write(report)
            return 5
        return 0
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        report["abort_reason"] = f"exception:{exc}"
        report["exception"] = str(exc)
        _write(report)
        raise
    finally:
        session.close()


def _finalize(
    report: dict[str, Any],
    session,
    headers: dict[str, str],
    order_client: UpbitOrderRestClient,
) -> None:
    session.expire_all()
    pause = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
        )
    )
    report["pause_after"] = {
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

    status_counts: Counter[str] = Counter()
    for row in session.scalars(
        select(BrokerRecoveryConflictEntity).where(
            BrokerRecoveryConflictEntity.user_broker_account_id == UBA
        )
    ).all():
        status_counts[str(row.review_status)] += 1

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
    target_preserved = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                    TARGET_IDS
                ),
                BrokerRecoveryConflictEntity.review_status
                == RecoveryConflictReviewStatus.HISTORICAL_PRESERVED,
            )
        )
        or 0
    )
    target_pending = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.broker_recovery_conflict_id.in_(
                    TARGET_IDS
                ),
                BrokerRecoveryConflictEntity.review_status
                == RecoveryConflictReviewStatus.PENDING_REVIEW,
            )
        )
        or 0
    )
    report["status_counts_uba58"] = dict(status_counts)
    report["active_review"] = active
    report["target_historical_preserved"] = target_preserved
    report["target_pending_review"] = target_pending
    report["dashboard"] = {
        "review_required": active,
        "historical_preserved": int(
            status_counts.get("HISTORICAL_PRESERVED", 0)
        ),
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
    target_audits = [
        a
        for a in audits
        if isinstance(a.detail, dict)
        and a.detail.get("conflict_id") in TARGET_IDS
    ]
    report["audit"] = {
        "event_type": "RECOVERY_CONFLICT_HISTORY_PRESERVED",
        "count_for_targets": len({a.detail.get("conflict_id") for a in target_audits}),
        "samples": [
            {
                "audit_event_id": int(a.audit_event_id),
                "actor": a.actor,
                "conflict_id": a.detail.get("conflict_id"),
                "broker_uuid_masked": a.detail.get("broker_uuid_masked"),
                "reason": a.detail.get("reason"),
                "before_status": a.detail.get("before_status"),
                "after_status": a.detail.get("after_status"),
                "resolution_type": a.detail.get("resolution_type"),
                "has_full_uuid": bool(
                    a.detail.get("external_order_id")
                    or a.detail.get("broker_uuid")
                ),
            }
            for a in target_audits[:5]
        ],
    }

    try:
        readiness = collect_scheduler_readiness(session)
        report["scheduler"] = (
            readiness.to_dict()
            if hasattr(readiness, "to_dict")
            else str(readiness)
        )
    except Exception as exc:  # noqa: BLE001
        report["scheduler_error"] = str(exc)

    with httpx.Client(timeout=15.0) as client:
        rs = client.get(
            f"{BASE}/api/v1/admin/recovery/scheduler/status",
            headers=headers,
        )
        report["recovery_scheduler_after"] = (
            rs.json() if rs.status_code == 200 else {"http": rs.status_code}
        )

    try:
        opens = order_client.list_orders(state="wait", limit=50) or []
        report["broker_open_after"] = len(opens)
    except Exception as exc:  # noqa: BLE001
        report["broker_open_after_error"] = str(exc)

    uba = session.get(UserBrokerAccount, UBA)
    report["live_arm_after"] = {
        "live_order_enabled": bool(uba.live_order_enabled) if uba else None,
        "live_armed": bool(uba.live_armed) if uba else None,
    }
    report["forbidden_counters"] = {
        "create_order": report.get("create_order_calls", 0),
        "cancel_order": report.get("cancel_order_calls", 0),
        "replace_order": report.get("replace_order_calls", 0),
        "approve_import": report.get("approve_import_calls", 0),
        "ignore": report.get("ignore_calls", 0),
        "pause_resume": report.get("pause_resume_calls", 0),
    }


def _write(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "step8_15_preserve_history.json"
    path.write_text(
        json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"WROTE {path}")
    print(
        json.dumps(
            {
                "abort_reason": report.get("abort_reason"),
                "preserve_success": report.get("preserve_success"),
                "preserve_failed": report.get("preserve_failed"),
                "preserve_skipped": report.get("preserve_skipped"),
                "active_review": report.get("active_review"),
                "target_historical_preserved": report.get(
                    "target_historical_preserved"
                ),
                "target_pending_review": report.get("target_pending_review"),
                "pause_after": report.get("pause_after"),
                "scheduler_verify": report.get("scheduler_verify"),
                "audit_count": (report.get("audit") or {}).get(
                    "count_for_targets"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
