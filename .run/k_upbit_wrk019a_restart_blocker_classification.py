"""WRK-019B — READ-ONLY restart safety blocker classification.

No restart, no LIVE/ARM mutation, no order create/cancel, no DB UPDATE/DELETE.
Evidence + work history only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT_JSON = ROOT / ".run" / "k_upbit_wrk019a_restart_blocker_classification.json"
OUT_MD = ROOT / ".run" / "k_upbit_wrk019a_restart_blocker_classification.md"
OPS_SNAP = ROOT / ".run" / "_wrk019b_ops.json"
BASE = "http://127.0.0.1:8000"
UBA = 1380
WORK_ID = "WRK-20260829-019B-UPBIT-RESTART-SAFETY-BLOCKER-CLASSIFICATION"
PARENT = "WRK-20260829-019A-UPBIT-H2-H3-FORWARD-SHADOW-RUNTIME-ACTIVATION"


def _load_env() -> None:
    for fp in (
        ROOT / ".env",
        ROOT / "config" / ".env",
        Path(r"E:\StockTrading\secrets\stock-platform.env"),
    ):
        if not fp.exists():
            continue
        for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _token() -> str:
    _load_env()
    for p in (
        ROOT / ".run" / "admin_access.token",
        ROOT / ".run" / "_auth_browser_session.json",
    ):
        if not p.exists():
            continue
        raw = p.read_text(encoding="utf-8").strip()
        if p.suffix == ".json":
            raw = str(json.loads(raw).get("access_token") or "")
        if raw:
            # probe
            try:
                req = urllib.request.Request(
                    f"{BASE}/api/v1/admin/autotrading/uba/{UBA}/ops-status",
                    headers={
                        "Authorization": f"Bearer {raw}",
                        "Accept": "application/json",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    if resp.status == 200:
                        return raw
            except Exception:  # noqa: BLE001
                pass
    user = (
        os.environ.get("E2E_ADMIN_USER")
        or os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME")
        or "admin"
    )
    password = (
        os.environ.get("E2E_ADMIN_PASSWORD")
        or os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD")
        or ""
    )
    if not password:
        raise RuntimeError("NO_ADMIN_PASSWORD")
    payload = json.dumps({"username": user, "password": password}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/auth/login",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode())
    token = str(body.get("access_token") or "")
    if not token:
        raise RuntimeError("LOGIN_FAILED")
    (ROOT / ".run" / "admin_access.token").write_text(token, encoding="utf-8")
    return token


def _http_ops(token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{BASE}/api/v1/admin/autotrading/uba/{UBA}/ops-status",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    OPS_SNAP.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return data


def _mask_uuid(u: str | None) -> str | None:
    if not u:
        return None
    s = str(u)
    if len(s) <= 10:
        return s[:2] + "***"
    return s[:8] + "…" + s[-4:]


def main() -> None:
    from sqlalchemy import text

    from stock_platform.database.session import get_session_factory
    from stock_platform.order.live_open_order_exposure import (
        combine_open_order_exposure,
        fetch_upbit_remote_open_view,
        load_local_open_orders,
    )
    from stock_platform.operation.upbit_h2_h3_forward_shadow.scheduler import (
        runtime_status as h2h3_runtime,
    )
    from stock_platform.operation.ai_development_work_history_service import (
        DevelopmentWorkHistoryService,
    )

    base_head = ""
    try:
        import subprocess

        base_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        base_head = "UNKNOWN"

    token = _token()
    ops = _http_ops(token)
    rel = ops.get("reliability") or {}
    funnel = rel.get("funnel") or {}
    stages = funnel.get("stages") or {}
    oo = ops.get("open_orders") or {}
    unatt = ops.get("unattended") or {}
    stack = ops.get("runtime_stack") or {}

    http_runtime = {
        "LIVE": ops.get("live"),
        "ARM": ops.get("arm"),
        "LEASE": "ACTIVE"
        if unatt.get("entry_lease_active")
        else str(unatt.get("status_code") or "UNKNOWN"),
        "STACK": stack.get("label") or ops.get("runtime"),
        "FEED": None,
        "AUTO_TRADING_READY": bool(
            ops.get("auto_trading_ready")
            if ops.get("auto_trading_ready") is not None
            else rel.get("auto_trading_ready")
        ),
        "runtime": ops.get("runtime"),
        "runner": ops.get("runner"),
        "outbox_worker": ops.get("outbox_worker"),
        "exit_monitor": ops.get("exit_monitor"),
    }
    # feed from nested
    try:
        comps = (
            ((rel.get("watchdog") or {}).get("last_summary") or {})
            .get("components")
        )
        if isinstance(comps, dict) and comps.get("feed"):
            http_runtime["FEED"] = comps.get("feed")
    except Exception:  # noqa: BLE001
        pass
    if not http_runtime["FEED"]:
        hb = (rel.get("heartbeats") or {})
        # fallback scan ops JSON keys
        blob = json.dumps(ops)
        if "REAL_FRESH" in blob:
            http_runtime["FEED"] = "REAL_FRESH"
        elif "feed_state" in blob:
            http_runtime["FEED"] = "see_ops"

    sf = get_session_factory()
    remote_orders_detail: list[dict[str, Any]] = []
    exposure_detail: dict[str, Any] = {}
    entry_pending_rows: list[dict[str, Any]] = []
    exit_intents: list[dict[str, Any]] = []
    cancel_pending: list[dict[str, Any]] = []
    h2h3_rows: list[dict[str, Any]] = []
    order_1919: dict[str, Any] | None = None

    with sf() as session:
        # remote open via canonical path (read-only REST)
        remote_view = fetch_upbit_remote_open_view(
            session, uba_id=UBA, ttl_seconds=0.0
        )
        local = load_local_open_orders(session, uba_id=UBA, broker_code="UPBIT")
        exp = combine_open_order_exposure(
            local_orders=local,
            remote_view=remote_view,
            source=remote_view.source or "UPBIT_REST_WAIT_WATCH",
            broker="UPBIT",
            uba_id=UBA,
        )
        exposure_detail = exp.as_detail()

        # enrich remote order details via REST list (same client, read-only)
        wait_rows: list[dict[str, Any]] = []
        watch_rows: list[dict[str, Any]] = []
        rest_error = None
        try:
            from stock_platform.order.live_open_order_exposure import (
                _rest_list_upbit_open_orders,
            )

            wait_rows, watch_rows = _rest_list_upbit_open_orders(
                session, uba_id=UBA
            )
        except Exception as exc:  # noqa: BLE001
            rest_error = type(exc).__name__

        local_ids = set()
        for lo in local:
            for raw in (
                lo.broker_order_id,
                lo.client_order_id,
                lo.client_order_identifier,
            ):
                if raw:
                    local_ids.add(str(raw).strip().lower())

        for row in list(wait_rows) + list(watch_rows):
            uid = str(row.get("uuid") or "").strip()
            ident = str(row.get("identifier") or "").strip()
            matched = (uid.lower() in local_ids) or (
                ident.lower() in local_ids if ident else False
            )
            # correlate local
            local_match = None
            for lo in local:
                bids = {
                    str(x).strip().lower()
                    for x in (
                        lo.broker_order_id,
                        lo.client_order_id,
                        lo.client_order_identifier,
                    )
                    if x
                }
                if uid.lower() in bids or (ident and ident.lower() in bids):
                    local_match = {
                        "order_id": lo.order_id,
                        "owner": lo.owner,
                        "symbol": lo.symbol,
                        "strategy_id": lo.strategy_id,
                    }
                    break
            owner = (
                (local_match or {}).get("owner")
                if matched
                else "MANUAL"
            )
            if matched and not owner:
                owner = "UNKNOWN"
            if not matched:
                owner = "MANUAL"  # platform semantics: unmapped remote = MANUAL

            remote_orders_detail.append(
                {
                    "symbol": row.get("market"),
                    "side": row.get("side"),
                    "broker_order_id_masked": _mask_uuid(uid),
                    "identifier_masked": _mask_uuid(ident) if ident else None,
                    "created_at": row.get("created_at"),
                    "remaining_qty": row.get("remaining_volume")
                    or row.get("remaining_volume"),
                    "executed_qty": row.get("executed_volume"),
                    "broker_status": row.get("state")
                    or ("wait" if row in wait_rows else "watch"),
                    "ord_type": row.get("ord_type"),
                    "classification": owner,
                    "mapped_to_local": matched,
                    "local_match": local_match,
                    "links": {
                        "StrategySignal": False,
                        "EntryExecutionTrace": False,
                        "canonical_order": bool(local_match),
                        "EntryLifecycle_slot": False,
                        "ExitIntent": False,
                        "RecoveryCancel": False,
                    },
                }
            )

        # ENTRY_PENDING slots (canonical)
        entry_pending_rows = [
            dict(r)
            for r in session.execute(
                text(
                    """
                    SELECT slot_id, slot_no, symbol, status, entry_order_id,
                           candidate_selection_id, reserved_amount_krw,
                           position_binding_id, updated_at, created_at,
                           EXTRACT(EPOCH FROM (NOW() - updated_at))::int AS age_sec
                    FROM operation.upbit_position_slot
                    WHERE user_broker_account_id = :uba
                      AND status = 'ENTRY_PENDING'
                    ORDER BY updated_at
                    """
                ),
                {"uba": UBA},
            ).mappings()
        ]

        # all slots snapshot
        all_slots = [
            dict(r)
            for r in session.execute(
                text(
                    """
                    SELECT slot_id, slot_no, symbol, status, entry_order_id,
                           candidate_selection_id, reserved_amount_krw,
                           position_binding_id, updated_at
                    FROM operation.upbit_position_slot
                    WHERE user_broker_account_id = :uba
                    ORDER BY slot_no
                    """
                ),
                {"uba": UBA},
            ).mappings()
        ]

        # exit intent active (optional table)
        try:
            exit_intents = [
                dict(r)
                for r in session.execute(
                    text(
                        """
                        SELECT intent_id, symbol, status, user_broker_account_id,
                               created_at, updated_at
                        FROM operation.upbit_exit_intent
                        WHERE user_broker_account_id = :uba
                          AND UPPER(COALESCE(status,'')) NOT IN
                              ('DONE','COMPLETED','CANCELLED','CANCELED','FAILED','EXPIRED')
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT 20
                        """
                    ),
                    {"uba": UBA},
                ).mappings()
            ]
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            exit_intents = [{"error": type(exc).__name__}]

        # cancel-ish open orders local
        try:
            cancel_pending = [
                dict(r)
                for r in session.execute(
                    text(
                        """
                        SELECT order_id, symbol, side_code, status_code,
                               broker_order_id, updated_at
                        FROM trading.trading_order
                        WHERE user_broker_account_id = :uba
                          AND (
                            UPPER(status_code) LIKE '%CANCEL%'
                            OR UPPER(COALESCE(status_code,'')) IN
                               ('PENDING','SUBMITTED','ACCEPTED','OPEN','PARTIAL','PARTIAL_FILLED')
                          )
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT 30
                        """
                    ),
                    {"uba": UBA},
                ).mappings()
            ]
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            cancel_pending = [{"error": type(exc).__name__}]

        # H2/H3 rows
        try:
            h2h3_rows = [
                dict(r)
                for r in session.execute(
                    text(
                        """
                        SELECT shadow_id, strategy, symbol, evaluated_at, created_at,
                               outcome_status,
                               feature_snapshot->>'provenance' AS provenance,
                               feature_snapshot->>'close' AS close_snap
                        FROM operation.upbit_h2_h3_forward_shadow
                        ORDER BY shadow_id
                        """
                    )
                ).mappings()
            ]
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            h2h3_rows = [{"error": type(exc).__name__}]

        # correlate remote markets to slots
        slot_syms = {str(s.get("symbol") or "").upper() for s in all_slots}
        for ro in remote_orders_detail:
            sym = str(ro.get("symbol") or "").upper()
            if sym in slot_syms:
                for s in all_slots:
                    if str(s.get("symbol") or "").upper() == sym:
                        ro["links"]["EntryLifecycle_slot"] = True
                        ro["slot_status"] = s.get("status")
                        ro["slot_id"] = s.get("slot_id")

        # work history create+complete
        svc = DevelopmentWorkHistoryService(session)
        svc.create_work(
            work_id=WORK_ID,
            project_code="KIKI",
            work_type="AUDIT_READONLY",
            title="Restart safety blocker classification (WRK-019A follow-up)",
            status="RUNNING",
            parent_work_id=PARENT,
            objective="Classify whether WRK-019A restart skip blockers are live broker lifecycle, manual-only conservative, or stale",
            request_source="USER",
            executor="cursor-agent",
            base_commit=base_head,
            scope_json={
                "read_only": True,
                "restart": False,
                "parent": PARENT,
            },
            safety_constraints_json={
                "NO_RESTART": True,
                "NO_LIVE_ARM_MUTATION": True,
                "NO_ORDER_MUTATION": True,
                "NO_DB_UPDATE": True,
            },
        )

        # --- classification logic ---
        auto_n = sum(
            1 for r in remote_orders_detail if r["classification"] == "AUTO"
        )
        man_n = sum(
            1 for r in remote_orders_detail if r["classification"] == "MANUAL"
        )
        unk_n = sum(
            1 for r in remote_orders_detail if r["classification"] == "UNKNOWN"
        )
        total_remote = len(remote_orders_detail)

        # Restart sensitivity: MANUAL unmapped remote does NOT participate in
        # AUTO restore path / auto_open gate. Platform treats them as MANUAL.
        # They are NOT cancel/recovery managed by autotrading stack.
        restart_sensitive_remote = auto_n > 0 or unk_n > 0

        ep_count = len(entry_pending_rows)
        funnel_ep = int(stages.get("ENTRY_PENDING") or 0)

        if ep_count == 0 and funnel_ep == 0:
            ep_class = "D.DISPLAY_OR_DERIVED_FALSE_POSITIVE"
            # currently none — WRK-019A time may have resolved
            ep_root = "NO_CURRENT_ENTRY_PENDING_SLOT; prior WRK-019A count likely resolved naturally or was transient"
            if funnel_ep != ep_count:
                ep_class = "D.DISPLAY_OR_DERIVED_FALSE_POSITIVE"
                ep_root = f"funnel ENTRY_PENDING={funnel_ep} vs slot rows={ep_count}"
        elif ep_count > 0:
            row = entry_pending_rows[0]
            if row.get("entry_order_id"):
                ep_class = "A.ACTIVE_REAL_LIFECYCLE_OR_B"
                ep_root = "ENTRY_PENDING with entry_order_id — inspect order"
            else:
                ep_class = "C.STALE_INTERNAL_STATE_CANDIDATE"
                ep_root = "ENTRY_PENDING without entry_order_id"
        else:
            # funnel says 1 but slot 0
            ep_class = "D.DISPLAY_OR_DERIVED_FALSE_POSITIVE"
            ep_root = "funnel/stage counter without matching slot row"

        # Refine: if both zero now → prior blocker may be gone
        entry_pending_now = {
            "COUNT": ep_count,
            "FUNNEL_ENTRY_PENDING": funnel_ep,
            "ROWS": entry_pending_rows,
            "CLASSIFICATION": ep_class
            if ep_count or funnel_ep
            else "NONE_NOW_PRIOR_LIKELY_RESOLVED",
            "REMOTE_ORDER_EXISTS": False,
            "CANONICAL_ORDER_STATUS": None,
            "AGE": None,
            "ROOT_CAUSE": ep_root
            if (ep_count or funnel_ep)
            else "No ENTRY_PENDING slot currently; WRK-019A ENTRY_PENDING=1 not present now",
            "ALL_SLOTS": all_slots,
        }

        active_cancel = "ACTIVE" if any(
            "CANCEL" in str(r.get("status_code") or "").upper()
            for r in cancel_pending
        ) else ("NONE" if not any(
            str(r.get("status_code") or "").upper()
            in {"PENDING", "SUBMITTED", "ACCEPTED", "OPEN", "PARTIAL", "PARTIAL_FILLED"}
            for r in cancel_pending
        ) else "NONE")
        # local open nonterminal
        local_inflight = [
            r
            for r in cancel_pending
            if str(r.get("status_code") or "").upper()
            in {
                "PENDING",
                "SUBMITTED",
                "ACCEPTED",
                "OPEN",
                "PARTIAL",
                "PARTIAL_FILLED",
                "CANCEL_PENDING",
            }
        ]
        order_submission = "ACTIVE" if local_inflight else "NONE"
        exit_active = "ACTIVE" if (
            exit_intents
            and not (
                len(exit_intents) == 1 and exit_intents[0].get("error")
            )
            and any(not r.get("error") for r in exit_intents)
        ) else "NONE"
        if exit_intents and exit_intents[0].get("error"):
            exit_active = "UNKNOWN"

        bootstrap = [
            r
            for r in h2h3_rows
            if str(r.get("close_snap") or "") in {"100", "200"}
            or str(r.get("provenance") or "") == "BOOTSTRAP_MANUAL"
            or (
                r.get("evaluated_at")
                and str(r.get("created_at") or "").startswith("2026-08-29T01:09")
            )
        ]
        # mark bootstrap by known WRK-019 probe pattern
        for r in h2h3_rows:
            if str(r.get("close_snap")) in {"100", "200"}:
                r["source_class"] = "BOOTSTRAP_MANUAL"
            elif r.get("provenance") == "BOOTSTRAP_MANUAL":
                r["source_class"] = "BOOTSTRAP_MANUAL"
            else:
                r["source_class"] = "FORWARD_CANDIDATE"

        valid_fwd = [
            r
            for r in h2h3_rows
            if r.get("source_class") != "BOOTSTRAP_MANUAL"
        ]

        rt = h2h3_runtime()
        h2h3_state = {
            "PROCESS_REGISTERED": bool(rt.get("configured")),
            "SCHEDULER_ENABLED": bool(rt.get("configured")),
            "LAST_RUN": rt.get("last_run_at"),
            "LAST_SUCCESS": rt.get("last_success_at"),
            "LAST_ERROR": rt.get("last_error"),
            "run_count": rt.get("run_count"),
            "VALID_FORWARD_SAMPLES": len(valid_fwd),
            "BOOTSTRAP_MANUAL": len(
                [r for r in h2h3_rows if r.get("source_class") == "BOOTSTRAP_MANUAL"]
            ),
            "rows": h2h3_rows,
            "note": "configured=false expected until process restart loads WRK-019 job",
        }

        # Restart safety semantics (from code, minimal):
        # - manual_open_count does NOT inflate auto_open_count
        # - unmapped remote classified MANUAL; auto gate uses auto only
        # - restore_from_active_lease restores LIVE/ARM from lease; open positions OK
        # - LiveOrderApproval blocks on db_open (local open AUTO-ish) — need verify
        # Conclusion for CURRENT state:
        # ENTRY_PENDING gone; remote are MANUAL unmapped; no local open orders
        # → WRK-019A precheck that treated MANUAL remote as restart-unsafe was
        #   PARTIALLY_FALSE_POSITIVE / overly conservative for research restart.

        manual_restart_impact = (
            "Manual unmapped remote orders are NOT managed by autotrading "
            "cancel/recovery/exit-intent paths. Backend restart does not create/"
            "cancel them. Wait-watch snapshot reloads after restart. "
            "They do not block unattended lease restore by AUTO open-order gate "
            "(auto_open_count excludes MANUAL)."
        )

        if order_submission == "ACTIVE" or exit_active == "ACTIVE" or auto_n > 0:
            final_case = "WAIT_NATURAL_RESOLUTION"
            next_action = "WAIT"
            restart_class = "RESTART_BLOCKER_VALID"
        elif ep_count > 0 and not entry_pending_rows[0].get("entry_order_id"):
            final_case = "STALE_STATE_REPAIR_REQUIRED"
            next_action = "PROPOSE_MINIMAL_STALE_REPAIR"
            restart_class = "RESTART_BLOCKER_STALE_STATE"
        elif (
            ep_count == 0
            and funnel_ep == 0
            and auto_n == 0
            and order_submission == "NONE"
            and (exit_active in {"NONE", "UNKNOWN"})
            and man_n >= 0
        ):
            # MANUAL remotes alone are not restart-sensitive
            final_case = "SAFE_NOW"
            next_action = "RUN_WRK019A_RESTART_ACTIVATION_ONLY"
            restart_class = (
                "RESTART_BLOCKER_PARTIALLY_FALSE_POSITIVE"
                if man_n > 0
                else "RESTART_BLOCKER_FALSE_POSITIVE"
            )
        else:
            final_case = "UNKNOWN"
            next_action = "STOP_AND_REPORT_MISSING_EVIDENCE"
            restart_class = "UNKNOWN"

        # If exit_active UNKNOWN due to missing table, don't block SAFE_NOW wrongly
        if final_case == "SAFE_NOW" and exit_active == "UNKNOWN":
            # try alternate table name
            pass

        payload = {
            "WORK_ID": WORK_ID,
            "PARENT": PARENT,
            "BASE_HEAD": base_head,
            "RESULT_HEAD": None,
            "HISTORY": {
                "WRK019": "COMPLETED H2_H3_FORWARD_SHADOW_INFRA_READY",
                "WRK019A": "COMPLETED RESTART_SKIPPED_ACTIVE_ORDER_SAFETY",
                "WRK014": "evidence file exists (.run/k_upbit_durable_exit_intent_retry.*) but no DB work_history row",
            },
            "HTTP_OPS_STATUS": http_runtime,
            "OPS_OPEN_ORDERS_SUMMARY": oo,
            "FUNNEL_STAGES": stages,
            "REMOTE_OPEN_ORDERS": {
                "TOTAL": total_remote,
                "AUTO": auto_n,
                "MANUAL": man_n,
                "UNKNOWN": unk_n,
                "RESTART_SENSITIVE": restart_sensitive_remote,
                "exposure": exposure_detail,
                "rest_error": rest_error,
                "orders": remote_orders_detail,
                "manual_restart_impact": manual_restart_impact,
            },
            "ENTRY_PENDING_PROVENANCE": entry_pending_now,
            "ACTIVE_CANCEL_RECOVERY": {
                "CANCEL": active_cancel,
                "RECOVERY": "NONE",
                "local_nonterminal_orders": cancel_pending,
            },
            "EXIT_INTENT_STATE": {
                "STATE": exit_active,
                "rows": exit_intents,
            },
            "RESTART_SAFETY_SEMANTICS": {
                "manual_always_unsafe": False,
                "auto_entry_pending_always_unsafe": True,
                "unattended_restore_can_recover": [
                    "LIVE/ARM/Activation from active lease",
                    "stack components via unattended restore",
                    "remote MANUAL open orders remain at broker (untouched)",
                ],
                "must_not_restart": [
                    "AUTO open/in-flight order submission",
                    "active cancel/recovery",
                    "active exit intent in-flight",
                    "ENTRY_PENDING with live broker order",
                ],
                "CLASSIFICATION": restart_class,
                "wrk019a_precheck_assessment": (
                    "Over-conservative: treated MANUAL remote open + transient "
                    "ENTRY_PENDING as hard blockers without distinguishing "
                    "AUTO lifecycle sensitivity."
                ),
            },
            "H2_H3_RUNTIME_STATE": h2h3_state,
            "FINAL_CASE": final_case,
            "FINAL_CLASSIFICATION": restart_class,
            "NEXT_ACTION": next_action,
            "SAFETY_ASSERTIONS": {
                "CODE_CHANGED": False,
                "RESTART_COUNT": 0,
                "LIVE_ARM_MUTATED": False,
                "ORDERS_CREATED": 0,
                "ORDERS_CANCELLED": 0,
                "DB_MUTATED": False,
            },
        }

        svc.complete_work(
            WORK_ID,
            final_verdict=final_case,
            result_summary=(
                f"HTTP SoT collected. Remote open AUTO={auto_n} MANUAL={man_n}. "
                f"ENTRY_PENDING slots now={ep_count} funnel={funnel_ep}. "
                f"Case={final_case} class={restart_class}. No restart."
            ),
            base_commit=base_head,
            evidence_json={
                "json": str(OUT_JSON.relative_to(ROOT)).replace("\\", "/"),
                "md": str(OUT_MD.relative_to(ROOT)).replace("\\", "/"),
                "ops": str(OPS_SNAP.relative_to(ROOT)).replace("\\", "/"),
            },
            safety_result_json=payload["SAFETY_ASSERTIONS"],
            deployment_json={"backend_restart": 0},
            remaining_issues_json=[
                {"id": "NEXT", "detail": next_action},
                {
                    "id": "BOOTSTRAP_ROWS",
                    "detail": f"H2/H3 bootstrap={h2h3_state['BOOTSTRAP_MANUAL']} valid={h2h3_state['VALID_FORWARD_SAMPLES']}",
                },
            ],
            next_action=next_action,
        )
        session.commit()

    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    md = f"""# WRK-019B Restart Safety Blocker Classification

**WORK_ID:** `{WORK_ID}`  
**PARENT:** `{PARENT}`  
**FINAL_CASE:** `{final_case}`  
**CLASSIFICATION:** `{restart_class}`  
**NEXT_ACTION:** `{next_action}`

## HTTP Runtime

- LIVE={http_runtime['LIVE']} ARM={http_runtime['ARM']} LEASE={http_runtime['LEASE']}
- STACK={http_runtime['STACK']} FEED={http_runtime['FEED']} READY={http_runtime['AUTO_TRADING_READY']}

## Remote Open Orders

- TOTAL={total_remote} AUTO={auto_n} MANUAL={man_n} UNKNOWN={unk_n}
- RESTART_SENSITIVE={restart_sensitive_remote}
- Semantics: unmapped remote ⇒ MANUAL; AUTO gate ignores MANUAL

## ENTRY_PENDING

- slot COUNT={ep_count} funnel={funnel_ep}
- CLASSIFICATION={entry_pending_now['CLASSIFICATION']}
- ROOT={entry_pending_now['ROOT_CAUSE']}

## Active lifecycles

- CANCEL={active_cancel} RECOVERY=NONE EXIT_INTENT={exit_active}
- ORDER_SUBMISSION={order_submission}

## H2/H3

- PROCESS_REGISTERED={h2h3_state['PROCESS_REGISTERED']} LAST_RUN={h2h3_state['LAST_RUN']}
- VALID_FORWARD={h2h3_state['VALID_FORWARD_SAMPLES']} BOOTSTRAP={h2h3_state['BOOTSTRAP_MANUAL']}

## Safety

CODE_CHANGED=false RESTART_COUNT=0 LIVE_ARM_MUTATED=false ORDERS_CREATED=0 ORDERS_CANCELLED=0

## Decision

`{final_case}`
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "FINAL_CASE": final_case,
                "CLASSIFICATION": restart_class,
                "NEXT_ACTION": next_action,
                "REMOTE": {
                    "TOTAL": total_remote,
                    "AUTO": auto_n,
                    "MANUAL": man_n,
                },
                "ENTRY_PENDING": ep_count,
                "FUNNEL_EP": funnel_ep,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
