"""STEP 8-12A-1 PHASE 1~4 — Read-only 검토 (상태 변경 금지)."""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import select

from stock_platform.broker.credential_adapter_factory import (
    build_upbit_private_client_for_uba,
    build_upbit_settings_from_vault,
    resolve_uba_credential,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

UBA = 58
OPENISH = {
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
}


def main() -> int:
    session = get_session_factory()()
    settings = get_settings()
    now = datetime.now(timezone.utc)
    out: dict = {
        "step": "8-12A-1",
        "phase": "1-4_pre_change",
        "checked_at": now.isoformat(),
        "mutation_executed": False,
        "create_order_calls": 0,
        "cancel_calls": 0,
        "replace_calls": 0,
        "conflict_mutations": 0,
    }
    order_client: UpbitOrderRestClient | None = None
    try:
        pause = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == UBA
            )
        )
        out["account_pause"] = {
            "trading_paused": bool(pause.trading_paused) if pause else False,
            "recovery_status": pause.recovery_status if pause else None,
            "last_error_code": pause.last_error_code if pause else None,
            "last_error_summary": (
                (pause.last_error_summary or "")[:240] if pause else None
            ),
            "updated_at": (
                pause.updated_at.isoformat()
                if pause and pause.updated_at
                else None
            ),
            "paused_at": None,
            "paused_by": getattr(pause, "lock_holder", None) if pause else None,
            "note": "paused_at/paused_by 컬럼 없음 — updated_at·lock_holder·error_code 참조",
            "last_recovery_run_id": (
                pause.last_recovery_run_id if pause else None
            ),
        }

        uba = session.get(UserBrokerAccount, UBA)
        assert uba is not None
        out["live"] = {
            "live_order_enabled": bool(uba.live_order_enabled),
            "live_armed": bool(uba.live_armed),
        }
        out["credential"] = BrokerCredentialVaultService(session).status(
            UBA
        ).as_dict()

        ks: dict = {}
        for scope in ("GLOBAL", f"UBA:{UBA}"):
            row = session.scalar(
                select(KillSwitchEntity).where(
                    KillSwitchEntity.scope_code == scope
                )
            )
            ks[scope] = {"active": bool(row.active) if row else False}
        out["kill_switch"] = ks

        orders = list(
            session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == UBA
                )
            )
        )

        def _st(o: object) -> str:
            return str(getattr(o, "status_code", "") or "").upper()

        out["db_orders"] = {
            "total": len(orders),
            "open": sum(1 for o in orders if _st(o) in OPENISH),
            "submission_unknown": sum(
                1 for o in orders if _st(o) == "SUBMISSION_UNKNOWN"
            ),
            "cancel_pending": sum(
                1 for o in orders if _st(o) == "CANCEL_PENDING"
            ),
            "replace_pending": sum(
                1
                for o in orders
                if "REPLACE" in _st(o) and "PEND" in _st(o)
            ),
        }
        out["scheduler"] = collect_scheduler_readiness(settings).to_dict()

        async def _accounts() -> list:
            client = build_upbit_private_client_for_uba(session, UBA)
            return await client.list_accounts()

        accounts = asyncio.run(_accounts())
        krw = None
        for row in accounts:
            if not isinstance(row, dict):
                continue
            if str(row.get("currency") or "").upper() != "KRW":
                continue
            bal = Decimal(str(row.get("balance") or 0))
            locked = Decimal(str(row.get("locked") or 0))
            krw = {
                "balance": str(bal),
                "locked": str(locked),
                "orderable": str(bal - locked),
            }
        out["broker_krw"] = krw
        out["broker_health"] = "HEALTHY"

        order_client = UpbitOrderRestClient(
            settings=build_upbit_settings_from_vault(
                resolve_uba_credential(
                    session, UBA, expected_broker="UPBIT"
                )
            ),
            user_broker_account_id=UBA,
        )
        waits = order_client.list_orders(state="wait", limit=100)
        out["broker_open_order_count"] = len(waits or [])

        conflicts = list(
            session.scalars(
                select(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == UBA,
                    BrokerRecoveryConflictEntity.resolved_at.is_(None),
                )
                .order_by(
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id
                )
            )
        )
        out["unresolved_conflict_count"] = len(conflicts)

        mismatch_details = []
        for cid in (3, 4):
            c = next(
                x
                for x in conflicts
                if int(x.broker_recovery_conflict_id) == cid
            )
            snap = dict(c.remote_snapshot or {})
            remote_payload = order_client.get_order(
                uuid=str(c.external_order_id)
            )
            remote_now = str(remote_payload.get("state") or "").lower()
            remote_safe = {
                k: remote_payload.get(k)
                for k in (
                    "state",
                    "market",
                    "side",
                    "ord_type",
                    "price",
                    "volume",
                    "executed_volume",
                    "remaining_volume",
                    "paid_fee",
                    "trades_count",
                    "created_at",
                )
            }
            remote_safe["uuid_masked"] = c.external_order_id_masked
            exec_v = Decimal(str(remote_payload.get("executed_volume") or 0))
            rem_v = Decimal(str(remote_payload.get("remaining_volume") or 0))
            trades = int(remote_payload.get("trades_count") or 0)
            if (
                remote_now == "cancel"
                and exec_v == 0
                and trades == 0
                and c.linked_internal_order_id is None
            ):
                recommended = "REFRESH_AND_RESOLVE_CANCELLED"
            elif remote_now in {"done", "cancel"} and exec_v > 0:
                recommended = "RECONCILE_PARTIAL_FILL_THEN_RESOLVE"
            elif remote_now in {"wait", "watch", "open"}:
                recommended = "HOLD_FOR_MANUAL_REVIEW"
            else:
                recommended = "HOLD_FOR_MANUAL_REVIEW"
            mismatch_details.append(
                {
                    "conflict_id": cid,
                    "market": c.market_code,
                    "side": c.side_code,
                    "masked_broker_uuid": c.external_order_id_masked,
                    "internal_order_id": c.linked_internal_order_id,
                    "identifier": None,
                    "detected_at": (
                        c.detected_at.isoformat() if c.detected_at else None
                    ),
                    "snapshot_status": c.external_status,
                    "snapshot": {
                        k: snap.get(k)
                        for k in (
                            "state",
                            "market",
                            "side",
                            "volume",
                            "executed_volume",
                            "remaining_volume",
                            "paid_fee",
                            "trades_count",
                            "created_at",
                            "price",
                        )
                    },
                    "broker_live_status": remote_now,
                    "broker_live_fields": remote_safe,
                    "requested_volume": str(c.requested_quantity),
                    "executed_volume": str(exec_v),
                    "remaining_volume": str(rem_v),
                    "paid_fee": str(remote_payload.get("paid_fee") or 0),
                    "trades_count": trades,
                    "internal_order_status": None,
                    "execution_sum": str(exec_v),
                    "position_or_balance_impact": "NONE_EXPECTED",
                    "post_fill_result": "N/A_NO_INTERNAL_ORDER",
                    "last_status_change_at": (
                        c.last_remote_checked_at.isoformat()
                        if c.last_remote_checked_at
                        else None
                    ),
                    "currently_open_order": remote_now
                    in {"wait", "watch", "open"},
                    "needs_resync": remote_now
                    != str(c.external_status or "").lower(),
                    "recommended_action": recommended,
                    "pause_reason_on_row": c.pause_reason,
                    "note": (
                        "Import 금지. remote cancel + 체결0 + 내부주문 없음 "
                        "→ Admin refresh 후 ignore 후보"
                    ),
                }
            )
        out["mismatch_details"] = mismatch_details

        hist_buckets: Counter[str] = Counter()
        samples: dict[str, list] = defaultdict(list)
        for c in conflicts:
            if int(c.broker_recovery_conflict_id) in {3, 4}:
                continue
            st_u = str(c.external_status or "").upper()
            rem = Decimal(str(c.remaining_quantity or 0))
            exe = Decimal(str(c.executed_quantity or 0))
            age_h = None
            if c.detected_at:
                dt = (
                    c.detected_at
                    if c.detected_at.tzinfo
                    else c.detected_at.replace(tzinfo=timezone.utc)
                )
                age_h = round((now - dt).total_seconds() / 3600, 2)
            if st_u == "DONE" and rem == 0:
                bucket = "DONE_CONFIRMED"
            elif st_u in {"CANCEL", "CANCELLED", "CANCELED"}:
                bucket = "CANCEL_CONFIRMED"
            elif exe > 0 and rem > 0:
                bucket = "PARTIAL_FILL_CONFIRMED"
            else:
                bucket = "NEEDS_REVIEW"
            hist_buckets[bucket] += 1
            if len(samples[bucket]) < 3:
                samples[bucket].append(
                    {
                        "conflict_id": int(c.broker_recovery_conflict_id),
                        "market": c.market_code,
                        "side": c.side_code,
                        "external_status": c.external_status,
                        "masked_uuid": c.external_order_id_masked,
                        "executed": str(c.executed_quantity),
                        "remaining": str(c.remaining_quantity),
                        "age_hours": age_h,
                        "review_status": c.review_status,
                        "contributes_to_uba_pause": True,
                    }
                )
        out["historical"] = {
            "total_excluding_mismatch_2": int(sum(hist_buckets.values())),
            "buckets": dict(hist_buckets),
            "samples": dict(samples),
        }

        rec: dict = {"source": "unavailable", "actual_state": "UNKNOWN"}
        try:
            resp = httpx.get(
                "http://127.0.0.1:8000/api/v1/admin/operations-dashboard/overview",
                headers={
                    "X-Admin-API-Key": str(settings.admin_api_key or "").strip()
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                ov = resp.json()
                rec = dict((ov.get("schedulers") or {}).get("recovery") or {})
                rec["source"] = "dashboard"
                out["dashboard_alerts"] = ov.get("alerts")
                out["overall_status"] = ov.get("overall_status")
            else:
                out["dashboard_http"] = resp.status_code
        except Exception as exc:  # noqa: BLE001
            out["dashboard_error"] = type(exc).__name__
        out["recovery_scheduler"] = rec

        needs_review = int(hist_buckets.get("NEEDS_REVIEW", 0))
        mismatch_ok = all(
            d["recommended_action"] == "REFRESH_AND_RESOLVE_CANCELLED"
            and not d["currently_open_order"]
            for d in mismatch_details
        )
        gates = {
            "CURRENT_ACTIVE_CONFLICT": 0,
            "broker_open_orders": out["broker_open_order_count"],
            "db_open_orders": out["db_orders"]["open"],
            "submission_unknown": out["db_orders"]["submission_unknown"],
            "cancel_pending": out["db_orders"]["cancel_pending"],
            "replace_pending": out["db_orders"]["replace_pending"],
            "NEEDS_REVIEW": needs_review,
            "mismatch_ready_refresh_resolve_cancel": mismatch_ok,
            "post_fill_errors_from_alerts": (
                (out.get("dashboard_alerts") or {}).get("critical")
            ),
            "recovery_running_or_cooldown": str(
                rec.get("actual_state") or ""
            ).upper()
            in {"RUNNING", "COOLDOWN"},
            "stale": bool(rec.get("stale")),
            "credential_verified": str(
                out["credential"].get("verification_status") or ""
            ).upper()
            == "VERIFIED",
            "broker_healthy": out["broker_health"] == "HEALTHY",
            "kill_off": (not ks["GLOBAL"]["active"])
            and (not ks[f"UBA:{UBA}"]["active"]),
            "live_off": not out["live"]["live_order_enabled"],
            "arm_off": not out["live"]["live_armed"],
            "unresolved_conflicts": len(conflicts),
            "account_paused": out["account_pause"]["trading_paused"],
        }
        out["gates"] = gates

        # 현재는 unresolved 44건이 있어 즉시 Unpause 불가.
        # 단, Open=0·Mismatch cancel 확정이면 '운영자 승인 후 resolve→unpause' 후보.
        if (
            needs_review == 0
            and mismatch_ok
            and out["broker_open_order_count"] == 0
            and out["db_orders"]["open"] == 0
            and gates["credential_verified"]
            and gates["broker_healthy"]
            and gates["kill_off"]
            and gates["live_off"]
            and gates["arm_off"]
            and gates["recovery_running_or_cooldown"]
            and not gates["stale"]
            and (out.get("dashboard_alerts") or {}).get("critical", 0) == 0
        ):
            verdict = "SAFE_TO_RESOLVE_AND_UNPAUSE"
        elif out["broker_open_order_count"] not in (0,) or needs_review > 0:
            verdict = "BLOCKED"
        else:
            verdict = "NEEDS_OPERATOR_DECISION"
        out["pre_change_verdict"] = verdict

        hist_ids_cancel = [
            int(c.broker_recovery_conflict_id)
            for c in conflicts
            if int(c.broker_recovery_conflict_id) not in {3, 4}
            and str(c.external_status or "").upper()
            in {"CANCEL", "CANCELLED", "CANCELED"}
        ]
        hist_ids_done = [
            int(c.broker_recovery_conflict_id)
            for c in conflicts
            if int(c.broker_recovery_conflict_id) not in {3, 4}
            and str(c.external_status or "").upper() == "DONE"
            and Decimal(str(c.remaining_quantity or 0)) == 0
        ]
        out["proposed_changes_if_operator_approves"] = [
            {
                "action": "POST /api/v1/admin/recovery/conflicts/{id}/refresh",
                "conflict_ids": [3, 4],
                "purpose": "snapshot wait → live cancel 동기화",
            },
            {
                "action": "POST /api/v1/admin/recovery/conflicts/{id}/ignore",
                "conflict_ids": [3, 4],
                "purpose": "cancel+체결0+내부주문없음 — Import 금지",
                "note_required": True,
            },
            {
                "action": "ignore (운영자 명시 ID만)",
                "conflict_ids_cancel_confirmed": hist_ids_cancel,
                "conflict_ids_done_confirmed": hist_ids_done,
                "purpose": "과거 종료 remote-only PENDING 정리",
                "batch_auto": False,
            },
            {
                "action": "POST /api/v1/admin/recovery/accounts/58/resume",
                "requires": "count_active_for_uba == 0",
                "reason": "RECOVERY_CONFLICTS_MANUALLY_REVIEWED_AND_RESOLVED",
                "keeps": [
                    "Trading Scheduler PAUSED",
                    "LIVE OFF",
                    "ARM OFF",
                    "Runtime not resumed",
                ],
            },
        ]
        out["operator_decisions_required"] = [
            "Mismatch #3/#4: refresh+ignore 승인 여부",
            "Historical CANCEL_CONFIRMED/DONE_CONFIRMED ignore 범위(전체 ID 명시 또는 단계적)",
            "Pause resume 승인 여부 (Conflict 0건 이후)",
            "Import 금지 확인 (approve-import 사용 안 함)",
        ]
        out["order_risk"] = {
            "real_order_risk": "LOW_WHILE_READ_ONLY",
            "note": "본 PHASE는 조회만. ignore/resume도 주문 API 미호출. approve-import는 사용 금지 권고.",
        }

        text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
        Path(r"E:\StockTrading\reports\step8_12a1_pre_change.json").write_text(
            text, encoding="utf-8"
        )
        print(text)
        return 0
    finally:
        if order_client is not None:
            order_client.close()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
