"""STEP 8-12A-2 — Decimal 수정 후 #3/#4·CANCEL Ignore + DONE 조회 대사.

승인 범위:
- #3/#4 Refresh → cancel·zero-fill 재확인 후 Ignore
- CANCEL allowlist 22건 개별 검증 후 Ignore
- DONE 20건 조회·분류만 (Ignore/Import 금지)
- Account Pause Resume / LIVE / ARM / 실주문 금지
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from stock_platform.api.deps_admin import AuditLogService
# FK 메타데이터 등록 (broker_recovery_run) — flush 전 필수
from stock_platform.broker import recovery_entities as _recovery_entities  # noqa: F401
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
    RecoveryConflictError,
)
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.json_safe import dumps_jsonable, to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.step8_12a2_cancel_guard import (
    IGNORE_NOTE,
    STEP8_12A2_CANCEL_ALLOWLIST,
    STEP8_12A2_DONE_ALLOWLIST,
    STEP8_12A2_MISMATCH_IDS,
    assert_only_allowlisted_mutation,
    evaluate_safe_cancel_ignore,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
ACTOR = "admin:step8_12a2"
REPORT_DIR = Path(r"E:\StockTrading\reports")
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


def _zero(value: Any) -> bool:
    try:
        return _dec(value) == 0
    except Exception:  # noqa: BLE001
        return False


def _mask(uuid_value: str | None) -> str:
    text = str(uuid_value or "").strip()
    if len(text) <= 8:
        return "****"
    return text[:4] + "…" + text[-4:]


def _order_client(session) -> UpbitOrderRestClient:
    resolved = BrokerCredentialVaultService(session).resolve_for_runtime(
        UBA,
        expected_broker="UPBIT",
        require_verified=True,
        touch_last_used=False,
    )
    return UpbitOrderRestClient(
        settings=build_upbit_settings_from_vault(resolved),
        user_broker_account_id=UBA,
    )


def _count_open_db(session) -> dict[str, int]:
    rows = session.scalars(
        select(TradingOrderEntity).where(
            TradingOrderEntity.user_broker_account_id == UBA
        )
    ).all()
    open_n = 0
    sub_unknown = 0
    cancel_pending = 0
    replace_pending = 0
    for row in rows:
        st = str(row.status_code or "").upper()
        if st in OPENISH_DB:
            open_n += 1
        if st == "SUBMISSION_UNKNOWN":
            sub_unknown += 1
        if st == "CANCEL_PENDING":
            cancel_pending += 1
        if st == "REPLACE_PENDING":
            replace_pending += 1
    return {
        "db_open": open_n,
        "submission_unknown": sub_unknown,
        "cancel_pending": cancel_pending,
        "replace_pending": replace_pending,
    }


def _has_internal_execution(
    session, linked_order_id: int | None, remote_uuid: str | None
) -> bool:
    if linked_order_id is not None:
        order = session.get(TradingOrderEntity, int(linked_order_id))
        if order is not None and _dec(order.filled_quantity) > 0:
            return True
    if remote_uuid:
        order = session.scalar(
            select(TradingOrderEntity).where(
                TradingOrderEntity.broker_order_id == str(remote_uuid),
                TradingOrderEntity.user_broker_account_id == UBA,
            ).limit(1)
        )
        if order is not None and _dec(order.filled_quantity) > 0:
            return True
    return False


def _find_internal_order(session, remote_uuid: str | None):
    if not remote_uuid:
        return None
    return session.scalar(
        select(TradingOrderEntity).where(
            TradingOrderEntity.broker_order_id == str(remote_uuid),
            TradingOrderEntity.user_broker_account_id == UBA,
        ).limit(1)
    )


def _audit_ignore(
    audit: AuditLogService,
    *,
    conflict_id: int,
    before_status: str,
    row: BrokerRecoveryConflictEntity,
    note: str,
    correlation_id: str,
) -> None:
    audit.record(
        event_type="RECOVERY_CONFLICT_IGNORE",
        actor=ACTOR,
        request_id=correlation_id,
        detail={
            "conflict_id": conflict_id,
            "before_status": before_status,
            "after_status": row.review_status,
            "remote_status": row.external_status,
            "executed_volume": (
                str(row.executed_quantity)
                if row.executed_quantity is not None
                else None
            ),
            "reason": note,
            "note": note,
            "correlation_id": correlation_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "user_broker_account_id": row.user_broker_account_id,
            "step": "8-12A-2",
        },
    )


def _classify_done(
    *,
    conflict: BrokerRecoveryConflictEntity,
    remote: dict[str, Any],
    internal_order: TradingOrderEntity | None,
    has_execution: bool,
) -> tuple[str, str]:
    """(class_code, recommendation)."""

    exec_v = _dec(remote.get("executed_volume"))
    trades = int(remote.get("trades_count") or 0)
    if exec_v == 0 and trades == 0:
        return (
            "ZERO_IMPACT_DONE",
            "HOLD_FOR_MANUAL_REVIEW",
        )
    if internal_order is not None and has_execution:
        # 체결량이 내부 filled와 대략 일치하면 이미 반영
        filled = _dec(internal_order.filled_quantity)
        if filled == exec_v or abs(filled - exec_v) <= Decimal("0"):
            return (
                "FULLY_REPRESENTED_IN_INTERNAL_DATA",
                "IGNORE_AS_ALREADY_REPRESENTED",
            )
        return (
            "BROKER_FILL_MISSING_EXECUTION",
            "RECONCILE_WITH_EXISTING_ORDER",
        )
    if internal_order is not None and not has_execution and exec_v > 0:
        return (
            "BROKER_FILL_MISSING_EXECUTION",
            "RECONCILE_WITH_EXISTING_ORDER",
        )
    if internal_order is None and exec_v > 0:
        return (
            "BROKER_FILL_MISSING_INTERNAL_ORDER",
            "IMPORT_AS_HISTORICAL_ORDER_REQUIRES_APPROVAL",
        )
    return (
        "CANNOT_SAFELY_RECONCILE",
        "HOLD_FOR_MANUAL_REVIEW",
    )


def main() -> int:
    session = get_session_factory()()
    settings = get_settings()
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "step": "8-12A-2",
        "checked_at": now.isoformat(),
        "create_order_calls": 0,
        "cancel_order_calls": 0,
        "replace_order_calls": 0,
        "approve_import_calls": 0,
        "pause_resume_calls": 0,
        "ignored_ids": [],
        "audit_events": [],
        "abort_reason": None,
    }
    svc = BrokerRecoveryConflictService(session)
    audit = AuditLogService(session)
    order_client: UpbitOrderRestClient | None = None

    try:
        pause = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == UBA
            )
        )
        report["pause_before"] = {
            "trading_paused": bool(pause.trading_paused) if pause else False,
            "last_error_code": pause.last_error_code if pause else None,
            "last_error_summary": (
                (pause.last_error_summary or "")[:300] if pause else None
            ),
            "recovery_status": pause.recovery_status if pause else None,
        }

        conflicts = list(
            session.scalars(
                select(BrokerRecoveryConflictEntity).where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == UBA
                )
            ).all()
        )
        unresolved_before = [
            c
            for c in conflicts
            if c.review_status in ACTIVE_REVIEW_STATUSES
        ]
        report["conflict_total_before"] = len(conflicts)
        report["unresolved_before"] = len(unresolved_before)
        report["cancel_target_ids"] = sorted(STEP8_12A2_CANCEL_ALLOWLIST)
        report["done_target_ids"] = sorted(STEP8_12A2_DONE_ALLOWLIST)
        report["mismatch_ids"] = sorted(STEP8_12A2_MISMATCH_IDS)

        order_client = _order_client(session)
        open_orders = order_client.list_orders(state="wait", limit=50) or []
        report["broker_open_before"] = len(open_orders)
        report["db_open_before"] = _count_open_db(session)

        # --- PHASE 2: #3/#4 ---
        mismatch_results: list[dict[str, Any]] = []
        for cid in sorted(STEP8_12A2_MISMATCH_IDS):
            item: dict[str, Any] = {"conflict_id": cid}
            row = svc.get(cid)
            before_status = row.review_status
            item["before"] = {
                "review_status": before_status,
                "external_status": row.external_status,
                "market": row.market_code,
                "side": row.side_code,
                "masked_uuid": row.external_order_id_masked,
                "executed_quantity": (
                    str(row.executed_quantity)
                    if row.executed_quantity is not None
                    else None
                ),
                "linked_internal_order_id": row.linked_internal_order_id,
            }
            if before_status not in ACTIVE_REVIEW_STATUSES:
                item["action"] = "SKIP_ALREADY_RESOLVED"
                mismatch_results.append(item)
                continue

            correlation = str(uuid.uuid4())
            refreshed = svc.refresh_from_remote(cid, actor=ACTOR)
            session.commit()
            audit.record(
                event_type="RECOVERY_CONFLICT_REFRESH",
                actor=ACTOR,
                request_id=correlation,
                detail={
                    "conflict_id": cid,
                    "before_status": before_status,
                    "after_status": refreshed.review_status,
                    "external_status": refreshed.external_status,
                    "step": "8-12A-2",
                },
            )
            report["audit_events"].append(
                {"type": "REFRESH", "conflict_id": cid}
            )

            remote = order_client.get_order(uuid=str(refreshed.external_order_id))
            remote_status = str(remote.get("state") or "").lower()
            exec_v = _dec(remote.get("executed_volume"))
            trades = int(remote.get("trades_count") or 0)
            rem_v = _dec(remote.get("remaining_volume"))
            fee = _dec(remote.get("paid_fee"))
            item["refresh"] = {
                "remote_status": remote_status,
                "executed_volume": str(exec_v),
                "remaining_volume": str(rem_v),
                "paid_fee": str(fee),
                "trades_count": trades,
                "broker_open": remote_status in {"wait", "watch", "open"},
                "internal_order": refreshed.linked_internal_order_id,
                "has_internal_execution": _has_internal_execution(
                    session,
                    refreshed.linked_internal_order_id,
                    refreshed.external_order_id,
                ),
            }
            ok = (
                remote_status == "cancel"
                and exec_v == 0
                and trades == 0
                and fee == 0
                and remote_status not in {"wait", "watch", "open"}
                and not item["refresh"]["has_internal_execution"]
                and refreshed.linked_internal_order_id is None
            )
            if not ok:
                item["action"] = "ABORT_NOT_SAFE"
                report["abort_reason"] = (
                    f"mismatch #{cid} failed cancel/zero-fill gate"
                )
                mismatch_results.append(item)
                report["mismatch_results"] = mismatch_results
                _finalize(report, session, order_client)
                return 2

            ignored = svc.ignore(cid, actor=ACTOR, note=IGNORE_NOTE)
            session.commit()
            _audit_ignore(
                audit,
                conflict_id=cid,
                before_status=before_status,
                row=ignored,
                note=IGNORE_NOTE,
                correlation_id=correlation,
            )
            report["ignored_ids"].append(cid)
            report["audit_events"].append(
                {"type": "IGNORE", "conflict_id": cid}
            )
            item["action"] = "IGNORED"
            item["after_status"] = ignored.review_status
            mismatch_results.append(item)
        report["mismatch_results"] = mismatch_results

        # --- PHASE 3: CANCEL 22 ---
        cancel_results: list[dict[str, Any]] = []
        cancel_ok = 0
        cancel_ignored = 0
        cancel_skipped = 0
        cancel_failed = 0
        for cid in sorted(STEP8_12A2_CANCEL_ALLOWLIST):
            assert_only_allowlisted_mutation(
                cid, allowlist=STEP8_12A2_CANCEL_ALLOWLIST
            )
            item: dict[str, Any] = {"conflict_id": cid}
            try:
                row = svc.get(cid)
            except RecoveryConflictError as exc:
                item["bucket"] = "NEEDS_REVIEW"
                item["reasons"] = [exc.code]
                cancel_failed += 1
                cancel_results.append(item)
                report["abort_reason"] = f"cancel #{cid} get failed"
                report["cancel_results"] = cancel_results
                _finalize(report, session, order_client)
                return 3

            before_status = row.review_status
            if before_status not in ACTIVE_REVIEW_STATUSES:
                item["bucket"] = "ALREADY_RESOLVED"
                item["action"] = "SKIP_IDEMPOTENT"
                cancel_skipped += 1
                cancel_results.append(item)
                continue

            correlation = str(uuid.uuid4())
            refreshed = svc.refresh_from_remote(cid, actor=ACTOR)
            session.commit()
            audit.record(
                event_type="RECOVERY_CONFLICT_REFRESH",
                actor=ACTOR,
                request_id=correlation,
                detail={
                    "conflict_id": cid,
                    "before_status": before_status,
                    "after_status": refreshed.review_status,
                    "external_status": refreshed.external_status,
                    "step": "8-12A-2",
                },
            )
            report["audit_events"].append(
                {"type": "REFRESH", "conflict_id": cid}
            )

            remote = order_client.get_order(
                uuid=str(refreshed.external_order_id)
            )
            remote_status = str(remote.get("state") or "").lower()
            broker_open = remote_status in {"wait", "watch", "open"}
            has_exe = _has_internal_execution(
                session,
                refreshed.linked_internal_order_id,
                refreshed.external_order_id,
            )
            verdict = evaluate_safe_cancel_ignore(
                conflict_id=cid,
                allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
                remote_status=remote_status,
                executed_volume=remote.get("executed_volume"),
                remaining_volume=remote.get("remaining_volume"),
                paid_fee=remote.get("paid_fee"),
                trades_count=remote.get("trades_count"),
                broker_open=broker_open,
                has_internal_execution=has_exe,
                has_position_impact=False,  # cancel+zero-fill이면 영향 없음
                last_remote_checked_at=refreshed.last_remote_checked_at,
                review_status=refreshed.review_status,
                linked_internal_order_id=refreshed.linked_internal_order_id,
            )
            item["verdict"] = verdict.to_dict()
            item["remote"] = {
                "status": remote_status,
                "executed_volume": str(remote.get("executed_volume")),
                "remaining_volume": str(remote.get("remaining_volume")),
                "paid_fee": str(remote.get("paid_fee")),
                "trades_count": remote.get("trades_count"),
            }
            if not verdict.ok:
                item["action"] = "STOP_NEEDS_REVIEW"
                cancel_failed += 1
                cancel_results.append(item)
                report["abort_reason"] = (
                    f"cancel #{cid} not SAFE: {verdict.reasons}"
                )
                report["cancel_results"] = cancel_results
                report["cancel_ok"] = cancel_ok
                report["cancel_ignored"] = cancel_ignored
                report["cancel_skipped"] = cancel_skipped
                report["cancel_failed"] = cancel_failed
                _finalize(report, session, order_client)
                return 3

            cancel_ok += 1
            ignored = svc.ignore(cid, actor=ACTOR, note=IGNORE_NOTE)
            session.commit()
            _audit_ignore(
                audit,
                conflict_id=cid,
                before_status=before_status,
                row=ignored,
                note=IGNORE_NOTE,
                correlation_id=correlation,
            )
            report["ignored_ids"].append(cid)
            report["audit_events"].append(
                {"type": "IGNORE", "conflict_id": cid}
            )
            cancel_ignored += 1
            item["action"] = "IGNORED"
            item["after_status"] = ignored.review_status
            cancel_results.append(item)

        report["cancel_results"] = cancel_results
        report["cancel_ok"] = cancel_ok
        report["cancel_ignored"] = cancel_ignored
        report["cancel_skipped"] = cancel_skipped
        report["cancel_failed"] = cancel_failed

        # --- PHASE 4: DONE 20 read-only ---
        # 현재 Broker 잔고 (조회만, 주문 API 아님)
        import asyncio

        private = build_upbit_private_client_for_uba(session, UBA)

        async def _accounts() -> list:
            return await private.list_accounts()

        balances = asyncio.run(_accounts()) if private else []
        balance_map = {
            str(b.get("currency")): b
            for b in (balances or [])
            if isinstance(b, dict)
        }
        done_rows: list[dict[str, Any]] = []
        class_counts: dict[str, int] = {}
        for cid in sorted(STEP8_12A2_DONE_ALLOWLIST):
            row = svc.get(cid)
            # DONE은 상태 변경 금지 — refresh도 DB 쓰므로 라이브 조회만
            remote = order_client.get_order(uuid=str(row.external_order_id))
            internal = _find_internal_order(session, row.external_order_id)
            if internal is None and row.linked_internal_order_id:
                internal = session.get(
                    TradingOrderEntity, int(row.linked_internal_order_id)
                )
            has_exe = _has_internal_execution(
                session,
                row.linked_internal_order_id
                or (internal.order_id if internal else None),
                row.external_order_id,
            )
            cls, rec = _classify_done(
                conflict=row,
                remote=remote,
                internal_order=internal,
                has_execution=has_exe,
            )
            class_counts[cls] = class_counts.get(cls, 0) + 1
            market = str(remote.get("market") or row.market_code or "")
            base = market.split("-")[-1] if "-" in market else market
            bal = balance_map.get(base) or {}
            snap = dict(row.remote_snapshot or {})
            trades = remote.get("trades") if isinstance(remote.get("trades"), list) else []
            trade0 = trades[0] if trades else {}
            done_rows.append(
                {
                    "conflict_id": cid,
                    "market": market,
                    "side": remote.get("side") or row.side_code,
                    "remote_uuid_masked": _mask(row.external_order_id),
                    "remote_created_at": remote.get("created_at"),
                    "remote_done_at": snap.get("done_at")
                    or remote.get("created_at"),
                    "order_type": remote.get("ord_type") or row.order_type_code,
                    "requested_price": str(remote.get("price")),
                    "requested_volume": str(remote.get("volume")),
                    "executed_volume": str(remote.get("executed_volume")),
                    "remaining_volume": str(remote.get("remaining_volume")),
                    "paid_fee": str(remote.get("paid_fee")),
                    "trades_count": remote.get("trades_count"),
                    "trade_price": str(trade0.get("price")) if trade0 else None,
                    "trade_volume": str(trade0.get("volume")) if trade0 else None,
                    "trade_funds": str(trade0.get("funds")) if trade0 else None,
                    "internal_order_exists": internal is not None,
                    "internal_order_id": (
                        int(internal.order_id) if internal else None
                    ),
                    "internal_execution_exists": has_exe,
                    "asset_snapshot_exists": bool(row.remote_snapshot),
                    "broker_balance_currency": base,
                    "broker_balance_available": bal.get("balance"),
                    "broker_balance_locked": bal.get("locked"),
                    "review_status_unchanged": row.review_status,
                    "classification": cls,
                    "recommendation": rec,
                    "position_qty_impact_possible": _dec(
                        remote.get("executed_volume")
                    )
                    > 0,
                    "avg_cost_impact_possible": _dec(
                        remote.get("executed_volume")
                    )
                    > 0,
                    "realized_pnl_impact_possible": _dec(
                        remote.get("executed_volume")
                    )
                    > 0,
                    "daily_loss_impact_possible": _dec(
                        remote.get("executed_volume")
                    )
                    > 0,
                    "sellable_qty_impact_possible": _dec(
                        remote.get("executed_volume")
                    )
                    > 0,
                    "tax_fee_report_impact_possible": _dec(
                        remote.get("paid_fee")
                    )
                    > 0
                    or _dec(remote.get("executed_volume")) > 0,
                    "safe_to_ignore_now": cls
                    == "FULLY_REPRESENTED_IN_INTERNAL_DATA",
                    "duplicate_import_risk": internal is not None,
                    "can_reconcile_with_current_balance_alone": False,
                    "post_trade_deposit_withdraw_possible": True,
                }
            )
        report["done_rows"] = done_rows
        report["done_class_counts"] = class_counts
        report["done_status_changes"] = 0
        report["done_imports"] = 0

        # Decimal 직렬화 smoke (Recovery Result 형태)
        smoke = AdapterRecoveryResult_smoke()
        report["decimal_serialization_ok"] = smoke

        _finalize(report, session, order_client)
        return 0 if report.get("abort_reason") is None else 1
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        report["abort_reason"] = f"exception:{exc}"
        report["exception"] = str(exc)
        _write_report(report)
        raise
    finally:
        session.close()


def AdapterRecoveryResult_smoke() -> bool:
    from stock_platform.broker.recovery_adapter import AdapterRecoveryResult

    result = AdapterRecoveryResult(status="SUCCESS", broker_code="UPBIT")
    result.detail["account_sync"] = {
        "deposit_amount": Decimal("5000.12345678")
    }
    dumps_jsonable(result.to_dict())
    return True


def _finalize(
    report: dict[str, Any],
    session,
    order_client: UpbitOrderRestClient | None,
) -> None:
    pause = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
        )
    )
    report["pause_after"] = {
        "trading_paused": bool(pause.trading_paused) if pause else False,
        "last_error_code": pause.last_error_code if pause else None,
        "last_error_summary": (
            (pause.last_error_summary or "")[:300] if pause else None
        ),
        "recovery_status": pause.recovery_status if pause else None,
        "last_recovery_run_id": (
            pause.last_recovery_run_id if pause else None
        ),
        "updated_at": (
            pause.updated_at.isoformat()
            if pause and pause.updated_at
            else None
        ),
    }
    conflicts = list(
        session.scalars(
            select(BrokerRecoveryConflictEntity).where(
                BrokerRecoveryConflictEntity.user_broker_account_id == UBA
            )
        ).all()
    )
    unresolved = [
        c
        for c in conflicts
        if c.review_status in ACTIVE_REVIEW_STATUSES
    ]
    report["unresolved_after"] = len(unresolved)
    report["unresolved_ids_after"] = [
        int(c.broker_recovery_conflict_id) for c in unresolved
    ]
    report["db_open_after"] = _count_open_db(session)
    if order_client is not None:
        try:
            opens = order_client.list_orders(state="wait", limit=50) or []
            report["broker_open_after"] = len(opens)
        except Exception as exc:  # noqa: BLE001
            report["broker_open_after_error"] = str(exc)

    # Dashboard overview (Recovery Desired/Actual)
    settings = get_settings()
    try:
        headers = {
            "X-Admin-API-Key": str(settings.admin_api_key or "").strip()
        }
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                "http://127.0.0.1:8000/api/v1/admin/ops/overview",
                headers=headers,
            )
            if r.status_code == 200:
                report["ops_overview"] = r.json()
    except Exception as exc:  # noqa: BLE001
        report["ops_overview_error"] = str(exc)

    try:
        readiness = collect_scheduler_readiness(session)
        if hasattr(readiness, "to_dict"):
            report["scheduler_readiness"] = readiness.to_dict()
        elif hasattr(readiness, "__dict__"):
            report["scheduler_readiness"] = {
                k: v
                for k, v in vars(readiness).items()
                if not k.startswith("_")
            }
        else:
            report["scheduler_readiness"] = str(readiness)
    except Exception as exc:  # noqa: BLE001
        report["scheduler_readiness_error"] = str(exc)

    uba = session.get(UserBrokerAccount, UBA)
    report["live_arm"] = {
        "live_order_enabled": bool(uba.live_order_enabled) if uba else None,
        "live_armed": bool(uba.live_armed) if uba else None,
    }
    report["forbidden_counters"] = {
        "create_order": report.get("create_order_calls", 0),
        "cancel_order": report.get("cancel_order_calls", 0),
        "replace_order": report.get("replace_order_calls", 0),
        "approve_import": report.get("approve_import_calls", 0),
        "pause_resume": report.get("pause_resume_calls", 0),
        "done_status_changes": report.get("done_status_changes", 0),
        "done_imports": report.get("done_imports", 0),
    }
    _write_report(report)


def _write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "step8_12a2_cleanup.json"
    # 보고용 — 알 수 없는 타입은 str로 (운영 스크립트; 금액 경로는 이미 to_jsonable)
    try:
        payload = to_jsonable(report)
    except TypeError:
        payload = json.loads(json.dumps(report, default=str))
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"WROTE {path}")
    print(
        json.dumps(
            {
                "abort_reason": report.get("abort_reason"),
                "ignored_ids": report.get("ignored_ids"),
                "unresolved_before": report.get("unresolved_before"),
                "unresolved_after": report.get("unresolved_after"),
                "cancel_ignored": report.get("cancel_ignored"),
                "done_class_counts": report.get("done_class_counts"),
                "pause_after": report.get("pause_after"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
