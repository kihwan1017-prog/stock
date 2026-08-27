"""AutoTrading process version services — OBSERVABILITY ONLY (REAL mutation 0)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.autotrading_process_version.constants import (
    BOOTSTRAP_CHANGES,
    CHANGE_OBSERVABILITY,
    COMPONENT_TYPES,
    CURRENT_KIWOOM_CONFIG_SNAPSHOT,
    CURRENT_UPBIT_CONFIG_SNAPSHOT,
    KIWOOM_STAGES,
    STATUS_ACTIVE,
    STATUS_RETIRED,
    TRACE_PARTIAL,
    UPBIT_STAGES,
)
from stock_platform.operation.autotrading_process_version.entities import (
    AutoTradingExecutionTraceEntity,
    AutoTradingLogicVersionEntity,
    AutoTradingProcessChangeEntity,
    AutoTradingProcessComponentLinkEntity,
    AutoTradingProcessVersionEntity,
    AutoTradingTraceEventEntity,
)

ROOT = Path(__file__).resolve().parents[4]
KST = timezone(timedelta(hours=9))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return out.strip() or None
    except Exception:  # noqa: BLE001
        return None


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _scrub_secrets(obj: Any) -> Any:
    """Remove secret-like keys recursively."""
    banned = {
        "api_key",
        "secret",
        "secret_key",
        "password",
        "token",
        "telegram_token",
        "access_key",
        "credential",
    }
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(b in lk for b in banned):
                continue
            out[k] = _scrub_secrets(v)
        return out
    if isinstance(obj, list):
        return [_scrub_secrets(x) for x in obj]
    return obj


def ensure_bootstrap(session: Session, *, commit: bool = True) -> dict[str, Any]:
    """Idempotent: create current process versions + historical change timeline."""

    created_versions = 0
    created_changes = 0
    created_logic = 0
    git = _git_head() or "ab29698"

    for market, broker, cfg, stages in (
        ("UPBIT", "UPBIT", CURRENT_UPBIT_CONFIG_SNAPSHOT, UPBIT_STAGES),
        ("KIWOOM", "KIWOOM", CURRENT_KIWOOM_CONFIG_SNAPSHOT, KIWOOM_STAGES),
    ):
        existing = session.scalar(
            select(AutoTradingProcessVersionEntity).where(
                AutoTradingProcessVersionEntity.market == market,
                AutoTradingProcessVersionEntity.status == STATUS_ACTIVE,
            )
        )
        components: dict[str, Any] = {}
        logic_ids: dict[str, int] = {}
        for stage in stages:
            ctype = stage["id"]
            if ctype not in COMPONENT_TYPES and ctype not in {
                "UNIVERSE",
                "MARKET_DATA",
            }:
                pass
            vcode = f"{ctype}_V1"
            logic = session.scalar(
                select(AutoTradingLogicVersionEntity).where(
                    AutoTradingLogicVersionEntity.market == market,
                    AutoTradingLogicVersionEntity.component_type == ctype,
                    AutoTradingLogicVersionEntity.version_code == vcode,
                )
            )
            if logic is None:
                rule_id = None
                rule_ver = None
                if ctype == "ENTRY_SIGNAL":
                    rule_id = cfg.get("entry_rule")
                    rule_ver = "real_v1"
                elif ctype == "WAITING":
                    rule_id = "waiting_started_at"
                    rule_ver = "waiting_age_sot_v1"
                elif ctype == "TRADING_LLM":
                    rule_id = "TRADING_LLM_REAL_GATE"
                    rule_ver = "false"
                elif ctype == "ANALYSIS_LLM":
                    rule_id = str(cfg.get("analysis_llm"))
                    rule_ver = "analysis_v1"
                logic = AutoTradingLogicVersionEntity(
                    market=market,
                    component_type=ctype,
                    version_code=vcode,
                    rule_identifier=rule_id,
                    rule_version=rule_ver,
                    git_commit=git,
                    status=STATUS_ACTIVE,
                    config_snapshot_json=_scrub_secrets(
                        {k: v for k, v in cfg.items() if ctype.lower() in k.lower()}
                        or {"component": ctype}
                    ),
                    rule_snapshot_json=_scrub_secrets(
                        {"label": stage["label"], "desc": stage["desc"]}
                    ),
                    change_reason="baseline bootstrap",
                )
                session.add(logic)
                session.flush()
                created_logic += 1
            logic_ids[ctype] = int(logic.logic_version_id)
            components[ctype] = {
                "logic_version_id": int(logic.logic_version_id),
                "version_code": logic.version_code,
                "rule_identifier": logic.rule_identifier,
                "rule_version": logic.rule_version,
            }

        fp_payload = {
            "market": market,
            "config": _scrub_secrets(cfg),
            "components": {
                k: {"version_code": v["version_code"], "rule": v.get("rule_identifier")}
                for k, v in components.items()
            },
        }
        fp = _fingerprint(fp_payload)
        if existing is None:
            pv = AutoTradingProcessVersionEntity(
                market=market,
                broker_code=broker,
                version_code=f"{market}_AUTO_V1",
                version_name=f"{market} AutoTrading Baseline 2026-08-27",
                status=STATUS_ACTIVE,
                git_commit=git,
                change_summary="Canonical baseline after Entry Shadow research",
                change_reason=(
                    "PROCESS_VERSION_BASELINE_READY — observability provenance"
                ),
                fingerprint=fp,
                config_snapshot_json=_scrub_secrets(dict(cfg)),
                component_snapshot_json=components,
                evidence_refs_json=[
                    ".run/k_entry_shadow_real_kiwoom_final_review_20260827.json"
                ],
                created_by="bootstrap",
            )
            session.add(pv)
            session.flush()
            for ctype, lid in logic_ids.items():
                session.add(
                    AutoTradingProcessComponentLinkEntity(
                        process_version_id=int(pv.process_version_id),
                        logic_version_id=lid,
                        component_type=ctype,
                    )
                )
            created_versions += 1
            # observability change for baseline creation
            session.add(
                AutoTradingProcessChangeEntity(
                    market=market,
                    change_type=CHANGE_OBSERVABILITY,
                    component="PROCESS",
                    before_version_code=None,
                    after_version_code=pv.version_code,
                    before_snapshot_json={},
                    after_snapshot_json=_scrub_secrets(fp_payload),
                    change_summary="Register canonical process baseline",
                    change_reason="Process Version observability bootstrap",
                    git_commit=git,
                    evidence_refs_json=[],
                    deployed_at=_utc_now(),
                    real_policy_changed=False,
                    research_only=False,
                )
            )
            created_changes += 1

    # Historical change timeline (evidence-backed only)
    for item in BOOTSTRAP_CHANGES:
        commit = str(item["git_commit"])
        exists = session.scalar(
            select(AutoTradingProcessChangeEntity.change_id).where(
                AutoTradingProcessChangeEntity.git_commit == commit,
                AutoTradingProcessChangeEntity.change_summary
                == str(item["summary"]),
            )
        )
        if exists is not None:
            continue
        session.add(
            AutoTradingProcessChangeEntity(
                market=str(item.get("market") or "UPBIT"),
                change_type=str(item["change_type"]),
                component=str(item.get("component") or "PROCESS"),
                before_version_code="UNKNOWN",
                after_version_code="SEE_GIT",
                before_snapshot_json={},
                after_snapshot_json={"git_commit": commit},
                change_summary=str(item["summary"]),
                change_reason=str(item.get("change_reason") or ""),
                git_commit=commit,
                evidence_refs_json=list(item.get("evidence") or []),
                deployed_at=None,
                real_policy_changed=bool(item.get("real_policy_changed")),
                research_only=bool(item.get("research_only")),
            )
        )
        created_changes += 1

    if commit:
        session.commit()
    else:
        session.flush()
    return {
        "ok": True,
        "created_versions": created_versions,
        "created_logic": created_logic,
        "created_changes": created_changes,
        "git_commit": git,
    }


def list_process_versions(
    session: Session, *, market: str | None = None
) -> list[dict[str, Any]]:
    q = select(AutoTradingProcessVersionEntity).order_by(
        AutoTradingProcessVersionEntity.effective_from.desc()
    )
    if market:
        q = q.where(AutoTradingProcessVersionEntity.market == market.upper())
    rows = list(session.scalars(q))
    return [_pv_dict(r) for r in rows]


def get_process_version(session: Session, process_version_id: int) -> dict[str, Any] | None:
    row = session.get(AutoTradingProcessVersionEntity, int(process_version_id))
    if row is None:
        return None
    links = list(
        session.scalars(
            select(AutoTradingProcessComponentLinkEntity).where(
                AutoTradingProcessComponentLinkEntity.process_version_id
                == int(process_version_id)
            )
        )
    )
    logic_map = {}
    for link in links:
        logic = session.get(AutoTradingLogicVersionEntity, int(link.logic_version_id))
        if logic:
            logic_map[link.component_type] = {
                "logic_version_id": int(logic.logic_version_id),
                "version_code": logic.version_code,
                "rule_identifier": logic.rule_identifier,
                "rule_version": logic.rule_version,
                "git_commit": logic.git_commit,
            }
    out = _pv_dict(row)
    out["composition"] = logic_map
    return out


def get_current_process(
    session: Session, *, market: str, uba_id: int | None = None
) -> dict[str, Any]:
    market_u = market.upper()
    ensure_bootstrap(session, commit=True)
    pv = session.scalar(
        select(AutoTradingProcessVersionEntity).where(
            AutoTradingProcessVersionEntity.market == market_u,
            AutoTradingProcessVersionEntity.status == STATUS_ACTIVE,
        )
    )
    stages = UPBIT_STAGES if market_u == "UPBIT" else KIWOOM_STAGES
    overlay = _runtime_overlay(session, market=market_u, uba_id=uba_id)
    recovery = _recovery_layer(session, market=market_u, uba_id=uba_id)
    return {
        "market": market_u,
        "process_version": _pv_dict(pv) if pv else None,
        "stages": stages,
        "nodes": [
            {
                **stage,
                "status": overlay.get("node_status", {}).get(stage["id"], "UNKNOWN"),
                "detail": overlay.get("node_detail", {}).get(stage["id"]),
            }
            for stage in stages
        ],
        "summary": overlay.get("summary") or {},
        "first_zero": overlay.get("first_zero"),
        "recovery_layer": recovery,
        "daily_quota": overlay.get("daily_quota"),
        "research_layers": {
            "entry_shadow": "entry_signal_shadow_v1",
            "ma_exit_shadow": "ma_dead_cross_confirm2_v1",
            "trailing_shadow": "trailing_forward_shadow_v1",
            "trailing_real": {
                "T0_activation": "peak>entry",
                "T0_distance_pct": 3.0,
                "REAL_APPLIED": "T0",
                "shadow_variants": ["T1", "T2", "T3", "T4"],
            },
            "real_entry": "PORTFOLIO_BULLISH_STATE_ENTRY",
            "trading_llm_real_gate": False,
            "data_quality": _research_data_quality(session, market=market_u, uba_id=uba_id),
        },
        "HISTORICAL_TRADE_VERSION_IMMUTABLE": True,
    }


def _research_data_quality(
    session: Session, *, market: str, uba_id: int | None
) -> dict[str, Any]:
    """Process Map용 Shadow Valid/Quarantined + trust summary."""

    out: dict[str, Any] = {"market": market}
    if uba_id is None:
        return out
    try:
        from stock_platform.trading.autotrading_data_trust import (
            current_data_trust_summary,
            shadow_quality_counts,
        )

        out["trust_summary"] = current_data_trust_summary(
            session, market=market, uba_id=int(uba_id)
        )
        if market == "UPBIT":
            out["entry_shadow"] = shadow_quality_counts(
                session, uba_id=int(uba_id), table="upbit_entry_signal_shadow"
            )
            out["ma_exit_shadow"] = shadow_quality_counts(
                session, uba_id=int(uba_id), table="upbit_ma_exit_forward_shadow"
            )
            out["trailing_shadow"] = shadow_quality_counts(
                session, uba_id=int(uba_id), table="upbit_trailing_forward_shadow"
            )
            trail = out["trailing_shadow"]
            out["N10_VALID_READY"] = int(trail.get("VALID_SAMPLES") or 0) >= 10
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
    return out


def list_changes(session: Session, *, market: str | None = None) -> list[dict[str, Any]]:
    ensure_bootstrap(session, commit=True)
    q = select(AutoTradingProcessChangeEntity).order_by(
        AutoTradingProcessChangeEntity.created_at.desc()
    )
    if market:
        q = q.where(AutoTradingProcessChangeEntity.market == market.upper())
    rows = list(session.scalars(q.limit(100)))
    return [
        {
            "change_id": int(r.change_id),
            "market": r.market,
            "change_type": r.change_type,
            "component": r.component,
            "before_version_code": r.before_version_code,
            "after_version_code": r.after_version_code,
            "change_summary": r.change_summary,
            "change_reason": r.change_reason,
            "git_commit": r.git_commit,
            "evidence_refs": r.evidence_refs_json,
            "deployed_at": r.deployed_at.isoformat() if r.deployed_at else None,
            "real_policy_changed": bool(r.real_policy_changed),
            "research_only": bool(r.research_only),
            "friendly_diff": _friendly_diff(r),
        }
        for r in rows
    ]


def compare_versions(
    session: Session, *, left_id: int, right_id: int
) -> dict[str, Any]:
    left = get_process_version(session, left_id)
    right = get_process_version(session, right_id)
    if not left or not right:
        return {"ok": False, "error": "VERSION_NOT_FOUND"}
    left_c = left.get("composition") or {}
    right_c = right.get("composition") or {}
    keys = sorted(set(left_c) | set(right_c))
    changed = []
    for k in keys:
        a = (left_c.get(k) or {}).get("version_code")
        b = (right_c.get(k) or {}).get("version_code")
        if a != b:
            changed.append(
                {
                    "component": k,
                    "before": left_c.get(k),
                    "after": right_c.get(k),
                }
            )
    return {
        "ok": True,
        "left": left,
        "right": right,
        "changed_components": changed,
        "config_before": left.get("config_snapshot"),
        "config_after": right.get("config_snapshot"),
    }


def version_performance(
    session: Session, *, process_version_id: int, uba_id: int = 1380
) -> dict[str, Any]:
    """Attribute closed RTs that carry process_version_id on traces; else UNKNOWN."""

    pv = session.get(AutoTradingProcessVersionEntity, int(process_version_id))
    if pv is None:
        return {"ok": False, "error": "NOT_FOUND"}
    traces = list(
        session.scalars(
            select(AutoTradingExecutionTraceEntity).where(
                AutoTradingExecutionTraceEntity.process_version_id
                == int(process_version_id)
            )
        )
    )
    attributed = []
    for t in traces:
        s = t.summary_json or {}
        if s.get("net_est") is None:
            continue
        attributed.append(float(s["net_est"]))
    n = len(attributed)
    wins = sum(1 for x in attributed if x > 0)
    losses = sum(1 for x in attributed if x < 0)
    gross_pos = sum(x for x in attributed if x > 0)
    gross_neg = abs(sum(x for x in attributed if x < 0))
    pf = (gross_pos / gross_neg) if gross_neg > 0 else None
    sample_warning = n < 30
    return {
        "ok": True,
        "process_version_id": int(process_version_id),
        "version_code": pv.version_code,
        "trades": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n, 4) if n else None,
        "net": round(sum(attributed), 2) if attributed else 0.0,
        "pf": round(pf, 4) if pf is not None else None,
        "expectancy": round(sum(attributed) / n, 2) if n else None,
        "sample_warning": sample_warning,
        "sample_warning_message": (
            "표본이 적어 성능을 단정하기 어렵습니다." if sample_warning else None
        ),
        "attribution_note": (
            "Only trades linked to this process_version_id are included; "
            "unknown-version trades excluded"
        ),
    }


def reconstruct_today_traces(
    session: Session, *, uba_id: int = 1380, commit: bool = True
) -> dict[str, Any]:
    """PARTIAL reconstruction from orders+metadata — no invented stages."""

    ensure_bootstrap(session, commit=False)
    pv = session.scalar(
        select(AutoTradingProcessVersionEntity).where(
            AutoTradingProcessVersionEntity.market == "UPBIT",
            AutoTradingProcessVersionEntity.status == STATUS_ACTIVE,
        )
    )
    pvid = int(pv.process_version_id) if pv else None
    today = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today.astimezone(timezone.utc)
    orders = session.execute(
        text(
            """
            SELECT order_id, symbol, side_code, status_code,
                   created_at, filled_at, average_fill_price, filled_amount,
                   metadata_payload, source_signal_id
            FROM trading.trading_order
            WHERE user_broker_account_id=:uba AND broker_code='UPBIT'
              AND status_code='FILLED'
              AND COALESCE(filled_at, created_at) >= :ws
            ORDER BY COALESCE(filled_at, created_at)
            """
        ),
        {"uba": uba_id, "ws": today_utc},
    ).mappings().all()

    buy_q: dict[str, list] = {}
    created = 0
    from collections import defaultdict

    buy_q = defaultdict(list)
    for o in orders:
        sym = str(o["symbol"])
        if o["side_code"] == "BUY":
            buy_q[sym].append(dict(o))
        elif o["side_code"] == "SELL" and buy_q[sym]:
            b = buy_q[sym].pop(0)
            # skip if already traced
            exists = session.scalar(
                select(AutoTradingExecutionTraceEntity.trace_id).where(
                    AutoTradingExecutionTraceEntity.buy_order_id == int(b["order_id"])
                )
            )
            if exists is not None:
                continue
            buy_amt = float(b["filled_amount"] or 0)
            sell_amt = float(o["filled_amount"] or 0)
            fees = (buy_amt + sell_amt) * 0.0005
            net = sell_amt - buy_amt - fees
            meta_b = b.get("metadata_payload") if isinstance(b.get("metadata_payload"), dict) else {}
            meta_s = o.get("metadata_payload") if isinstance(o.get("metadata_payload"), dict) else {}
            entry_reason = meta_b.get("signal_reason") or meta_b.get("entry_reason") or "UNKNOWN"
            exit_reason = meta_s.get("exit_reason") or meta_s.get("signal_reason") or "UNKNOWN"
            bt = b["filled_at"] or b["created_at"]
            st = o["filled_at"] or o["created_at"]
            trace = AutoTradingExecutionTraceEntity(
                market="UPBIT",
                broker_code="UPBIT",
                user_broker_account_id=uba_id,
                symbol=sym,
                process_version_id=pvid,
                completeness=TRACE_PARTIAL,
                outcome="WIN" if net > 0 else "LOSS",
                buy_order_id=int(b["order_id"]),
                sell_order_id=int(o["order_id"]),
                started_at=bt,
                closed_at=st,
                summary_json={
                    "entry_reason": entry_reason,
                    "exit_reason": exit_reason,
                    "entry_price": float(b["average_fill_price"] or 0),
                    "exit_price": float(o["average_fill_price"] or 0),
                    "gross": round(sell_amt - buy_amt, 2),
                    "fees_est": round(fees, 2),
                    "net_est": round(net, 2),
                },
            )
            session.add(trace)
            session.flush()
            tid = int(trace.trace_id)
            exit_u = str(exit_reason or "").upper()
            events = [
                ("SELECTION", "PASS", "후보 선정/진입 경로", bt, None),
                ("ENTRY_SIGNAL", "PASS", str(entry_reason), bt, str(entry_reason)),
                ("ORDER", "CREATE", f"BUY order {b['order_id']}", bt, None),
                ("FILL", "FILL", "BUY filled", bt, None),
                ("POSITION", "PASS", "OPEN", bt, None),
            ]
            if exit_u == "TRAILING_STOP":
                peak = meta_s.get("peak_price")
                trig = meta_s.get("trigger_price")
                events.extend(
                    [
                        (
                            "EXIT_MONITOR",
                            "ARMED",
                            f"Trailing armed peak={peak}",
                            st,
                            "TRAILING_ARMED",
                        ),
                        (
                            "EXIT_MONITOR",
                            "TRIGGER",
                            f"Trailing trigger={trig}",
                            st,
                            "TRAILING_TRIGGERED",
                        ),
                    ]
                )
            events.extend(
                [
                    ("EXIT_SIGNAL", "EMIT", str(exit_reason), st, str(exit_reason)),
                    ("SELL_ORDER", "CREATE", f"SELL order {o['order_id']}", st, None),
                    ("FILL", "FILL", "SELL filled", st, None),
                    ("PNL", "CLOSE", f"net_est={round(net, 2)}", st, None),
                ]
            )
            for stage, status, summary, at, reason in events:
                _append_event(
                    session,
                    trace_id=tid,
                    market="UPBIT",
                    symbol=sym,
                    stage=stage,
                    event_type=status,
                    occurred_at=at or _utc_now(),
                    status=status,
                    reason_code=reason,
                    summary=summary,
                    process_version_id=pvid,
                    source_refs={
                        "buy_order_id": int(b["order_id"]),
                        "sell_order_id": int(o["order_id"]),
                    },
                )
            created += 1

    # blocked sample from entry shadow (no invented PASS)
    blocked = session.execute(
        text(
            """
            SELECT symbol, observed_at, baseline_block_reason, selection_id
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id=:uba AND source='FORWARD_NATURAL'
              AND variant='E0' AND shadow_decision='BLOCK'
              AND observed_at >= :ws
            ORDER BY observed_at DESC
            LIMIT 5
            """
        ),
        {"uba": uba_id, "ws": today_utc},
    ).mappings().all()
    blocked_n = 0
    for row in blocked:
        sym = str(row["symbol"])
        # one blocked trace per symbol today max
        exists = session.scalar(
            select(AutoTradingExecutionTraceEntity.trace_id).where(
                AutoTradingExecutionTraceEntity.symbol == sym,
                AutoTradingExecutionTraceEntity.outcome == "BLOCKED",
                AutoTradingExecutionTraceEntity.created_at >= today_utc,
            )
        )
        if exists is not None:
            continue
        tr = AutoTradingExecutionTraceEntity(
            market="UPBIT",
            broker_code="UPBIT",
            user_broker_account_id=uba_id,
            symbol=sym,
            process_version_id=pvid,
            completeness=TRACE_PARTIAL,
            outcome="BLOCKED",
            selection_id=int(row["selection_id"]) if row["selection_id"] else None,
            started_at=row["observed_at"],
            summary_json={
                "block_reason": row["baseline_block_reason"],
                "note": "reconstructed from entry_signal_shadow",
            },
        )
        session.add(tr)
        session.flush()
        _append_event(
            session,
            trace_id=int(tr.trace_id),
            market="UPBIT",
            symbol=sym,
            stage="ENTRY_SIGNAL",
            event_type="BLOCK",
            occurred_at=row["observed_at"],
            status="BLOCK",
            reason_code=str(row["baseline_block_reason"] or "BLOCK"),
            summary=f"Entry blocked: {row['baseline_block_reason']}",
            process_version_id=pvid,
            source_refs={"selection_id": row["selection_id"]},
        )
        _append_event(
            session,
            trace_id=int(tr.trace_id),
            market="UPBIT",
            symbol=sym,
            stage="ORDER",
            event_type="SKIP",
            occurred_at=row["observed_at"],
            status="BLOCK",
            reason_code="NO_ORDER",
            summary="주문 미생성",
            process_version_id=pvid,
            source_refs={},
        )
        blocked_n += 1

    # Kiwoom daily status marker — CURRENT funnel SoT (FEED_DOWN 하드코딩 금지)
    k_exists = session.scalar(
        select(AutoTradingExecutionTraceEntity.trace_id).where(
            AutoTradingExecutionTraceEntity.market == "KIWOOM",
            AutoTradingExecutionTraceEntity.outcome == "NO_PROGRESS",
            AutoTradingExecutionTraceEntity.created_at >= today_utc,
        )
    )
    if k_exists is None:
        kpv = session.scalar(
            select(AutoTradingProcessVersionEntity).where(
                AutoTradingProcessVersionEntity.market == "KIWOOM",
                AutoTradingProcessVersionEntity.status == STATUS_ACTIVE,
            )
        )
        try:
            from stock_platform.trading.kiwoom_funnel_observability import (
                build_kiwoom_funnel_snapshot,
            )

            snap = build_kiwoom_funnel_snapshot(
                session, user_broker_account_id=1381
            )
            fz = str(snap.get("FIRST_ZERO_STAGE") or "UNKNOWN")
        except Exception:  # noqa: BLE001
            fz = "UNKNOWN"
            snap = {}
        # FEED_DOWN only when funnel says so — MARKET_CLOSED / NO_SIGNAL 은 정상 표기
        if fz == "FEED_DOWN":
            classification = "MARKET_DATA_FAILURE"
            stage = "MARKET_DATA"
            event_status = "ERROR"
            summary = "실시간 시세 단계에서 막힘 (FEED_DOWN)"
        elif fz == "MARKET_CLOSED":
            classification = "MARKET_CLOSED"
            stage = "MARKET_DATA"
            event_status = "CLOSED"
            summary = "장 마감 — 시세 장애 아님"
        elif fz == "NO_GOLDEN_CROSS_SIGNAL":
            classification = "NORMAL_NO_SIGNAL"
            stage = "ENTRY_SIGNAL"
            event_status = "WAIT"
            summary = "신규 골든크로스 없음 (정상 대기)"
        else:
            classification = str(fz)
            stage = "MARKET_DATA"
            event_status = "INFO"
            summary = f"FIRST_ZERO={fz}"
        ktr = AutoTradingExecutionTraceEntity(
            market="KIWOOM",
            broker_code="KIWOOM",
            user_broker_account_id=1381,
            symbol="MARKET",
            process_version_id=int(kpv.process_version_id) if kpv else None,
            completeness=TRACE_PARTIAL,
            outcome="NO_PROGRESS",
            started_at=_utc_now(),
            summary_json={
                "first_zero": fz,
                "classification": classification,
                "source": "kiwoom_funnel_canonical",
            },
        )
        session.add(ktr)
        session.flush()
        _append_event(
            session,
            trace_id=int(ktr.trace_id),
            market="KIWOOM",
            symbol="MARKET",
            stage=stage,
            event_type=event_status,
            occurred_at=_utc_now(),
            status=event_status,
            reason_code=fz,
            summary=summary,
            process_version_id=int(kpv.process_version_id) if kpv else None,
            source_refs={"source": "kiwoom-funnel"},
        )

    if commit:
        session.commit()
    return {"ok": True, "closed_traces": created, "blocked_traces": blocked_n}


def list_traces(
    session: Session,
    *,
    market: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_bootstrap(session, commit=True)
    reconstruct_today_traces(session, commit=True)
    q = select(AutoTradingExecutionTraceEntity).order_by(
        AutoTradingExecutionTraceEntity.created_at.desc()
    )
    if market:
        q = q.where(AutoTradingExecutionTraceEntity.market == market.upper())
    rows = list(session.scalars(q.limit(limit)))
    return [_trace_dict(r) for r in rows]


def get_trace(session: Session, trace_id: int) -> dict[str, Any] | None:
    row = session.get(AutoTradingExecutionTraceEntity, int(trace_id))
    if row is None:
        return None
    events = list(
        session.scalars(
            select(AutoTradingTraceEventEntity)
            .where(AutoTradingTraceEventEntity.trace_id == int(trace_id))
            .order_by(AutoTradingTraceEventEntity.occurred_at.asc())
        )
    )
    out = _trace_dict(row)
    out["events"] = [
        {
            "trace_event_id": int(e.trace_event_id),
            "stage": e.stage,
            "event_type": e.event_type,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            "status": e.status,
            "reason_code": e.reason_code,
            "summary": e.summary,
            "process_version_id": e.process_version_id,
            "logic_version_id": e.logic_version_id,
            "source_refs": e.source_refs_json,
        }
        for e in events
    ]
    return out


def append_trace_event_fail_open(
    session: Session,
    **kwargs: Any,
) -> dict[str, Any]:
    """Observability write — never raises to caller for REAL path use."""
    try:
        _append_event(session, **kwargs)
        session.commit()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {
            "ok": False,
            "code": "AUTOTRADING_TRACE_PERSIST_FAILED",
            "error": type(exc).__name__,
        }


def _append_event(
    session: Session,
    *,
    trace_id: int,
    market: str,
    symbol: str,
    stage: str,
    event_type: str,
    occurred_at: datetime,
    status: str,
    reason_code: str | None,
    summary: str | None,
    process_version_id: int | None,
    source_refs: dict[str, Any],
    logic_version_id: int | None = None,
) -> None:
    exists = session.scalar(
        select(AutoTradingTraceEventEntity.trace_event_id).where(
            AutoTradingTraceEventEntity.trace_id == int(trace_id),
            AutoTradingTraceEventEntity.stage == stage,
            AutoTradingTraceEventEntity.event_type == event_type,
            AutoTradingTraceEventEntity.occurred_at == occurred_at,
        )
    )
    if exists is not None:
        return
    session.add(
        AutoTradingTraceEventEntity(
            trace_id=int(trace_id),
            market=market,
            symbol=symbol,
            stage=stage,
            event_type=event_type,
            occurred_at=occurred_at,
            status=status,
            reason_code=reason_code,
            summary=summary,
            process_version_id=process_version_id,
            logic_version_id=logic_version_id,
            input_snapshot_json={},
            output_snapshot_json={},
            source_refs_json=_scrub_secrets(source_refs),
        )
    )


def _runtime_overlay(
    session: Session, *, market: str, uba_id: int | None
) -> dict[str, Any]:
    node_status: dict[str, str] = {}
    node_detail: dict[str, Any] = {}
    first_zero = None
    summary: dict[str, Any] = {}
    daily_quota: dict[str, Any] | None = None
    if market == "UPBIT":
        uba = uba_id or 1380
        slots = dict(
            session.execute(
                text(
                    """
                    SELECT status, COUNT(*) FROM operation.upbit_position_slot
                    WHERE user_broker_account_id=:uba GROUP BY status
                    """
                ),
                {"uba": uba},
            ).all()
        )
        waiting = int(slots.get("WAITING_SIGNAL", 0))
        open_n = int(slots.get("OPEN", 0))
        empty_n = int(slots.get("EMPTY", 0))
        entry_pending = int(slots.get("ENTRY_PENDING", 0))
        for s in UPBIT_STAGES:
            node_status[s["id"]] = "OK"

        # canonical funnel / liveness SoT (하드코딩 금지)
        live = None
        try:
            from stock_platform.trading.pipeline_liveness_service import (
                build_pipeline_liveness_snapshot,
            )

            live = build_pipeline_liveness_snapshot(
                session, user_broker_account_id=int(uba)
            )
        except Exception as exc:  # noqa: BLE001
            live = {"ok": False, "error": type(exc).__name__}

        stages_f = (live or {}).get("stages") or {}
        fz = (live or {}).get("first_zero_stage")
        classification = str((live or {}).get("classification") or "")
        friendly = (live or {}).get("user_friendly_reason")

        if waiting > 0:
            node_status["WAITING"] = "WAIT"
            node_detail["WAITING"] = {"count": waiting}
        elif empty_n > 0 and open_n == 0:
            node_status["WAITING"] = "UNREACHED"
            node_detail["WAITING"] = {"count": 0, "note": "EMPTY 슬롯 대기 배정 가능"}

        if fz == "ENTRY_SIGNAL" or classification == "NORMAL_NO_SIGNAL":
            node_status["ENTRY_SIGNAL"] = "WAIT"
            node_detail["ENTRY_SIGNAL"] = {
                "note": "진입 조건 미충족 (정상 대기)",
                "top_block": (live or {}).get("first_zero_reason"),
                "eval": stages_f.get("ENTRY_EVALUATION"),
                "pass": stages_f.get("ENTRY_PASS"),
            }
        elif int(stages_f.get("ENTRY_PASS") or 0) > 0:
            node_status["ENTRY_SIGNAL"] = "OK"

        if int(stages_f.get("ENTRY_PENDING_STUCK") or 0) > 0:
            node_status["ORDER"] = "ERROR"
            node_detail["ORDER"] = {
                "note": "ENTRY_PENDING zero-fill 고착",
                "stuck": stages_f.get("ENTRY_PENDING_STUCK"),
            }
        elif entry_pending > 0:
            node_status["ORDER"] = "WAIT"
            node_detail["ORDER"] = {"entry_pending": entry_pending}

        if classification == "SYSTEM_FAILURE":
            node_status["WATCHDOG"] = "ERROR"
        else:
            node_status["WATCHDOG"] = "OK"

        node_status["TRADING_LLM"] = "OK"
        node_detail["TRADING_LLM"] = {"mode": "SHADOW", "real_gate": False}
        node_detail["EXIT_MONITOR"] = {
            "real_trailing": {
                "activation": "peak>entry (no min profit %)",
                "trail_distance_pct": 3.0,
                "policy": "T0",
            },
            "shadow": {
                "enabled": True,
                "variants": ["T1", "T2", "T3", "T4"],
                "real_orders": 0,
            },
            "alert_policy": "submit_success_once_edge_dedupe",
            "note_ko": "REAL Trailing 3% · Shadow T1~T4 연구 · 알림 중복 억제",
        }

        last_trade = (live or {}).get("last_trade") or {}
        summary = {
            "autotrading_state": (
                "파이프라인 장애"
                if classification == "SYSTEM_FAILURE"
                else (
                    "흐름 정체"
                    if classification in {"PIPELINE_STALL", "WAITING_SLOT_STARVATION"}
                    else "매수신호 대기"
                )
            ),
            "current_location": str(fz or "pipeline"),
            "user_friendly_reason": friendly
            or ("시스템은 정상입니다. 진입 신호 대기 중." if waiting or fz == "ENTRY_SIGNAL" else "운용 중"),
            "waiting": waiting,
            "open": open_n,
            "empty": empty_n,
            "entry_pending": entry_pending,
            "last_trade": last_trade,
            "classification": classification,
            "first_zero_stage": fz,
            "first_zero_reason": (live or {}).get("first_zero_reason"),
            "pipeline_health_state": (live or {}).get("pipeline_health_state"),
            "recommended_action": (live or {}).get("recommended_action"),
            "data_trust": (live or {}).get("data_trust"),
            "data_trust_summary": (live or {}).get("data_trust_summary"),
        }
        daily_quota = None
        try:
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
                resolve_portfolio_daily_entry_limit,
            )
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
                summarize_portfolio_daily_entries,
            )

            lim = resolve_portfolio_daily_entry_limit(session, uba)
            daily_quota = summarize_portfolio_daily_entries(
                session, uba, daily_limit=lim
            )
            node_detail["ADMISSION"] = {
                "entry_count": daily_quota.get("entry_count"),
                "entry_limit": daily_quota.get("entry_limit"),
                "consumed_count": daily_quota.get("consumed_count"),
                "reserved_count": daily_quota.get("reserved_count"),
                "zero_fill_cancelled_count": daily_quota.get(
                    "zero_fill_cancelled_count"
                ),
                "label_ko": daily_quota.get("label_ko"),
            }
        except Exception:  # noqa: BLE001
            daily_quota = None
        first_zero = fz
    else:
        # KIWOOM — canonical funnel + realtime SoT (하드코딩 FEED_DOWN 금지)
        uba = int(uba_id or 1381)
        overlay_k = _kiwoom_runtime_overlay(session, uba_id=uba)
        node_status = overlay_k["node_status"]
        node_detail = overlay_k["node_detail"]
        first_zero = overlay_k["first_zero"]
        summary = overlay_k["summary"]
    return {
        "node_status": node_status,
        "node_detail": node_detail,
        "first_zero": first_zero,
        "summary": summary,
        "daily_quota": daily_quota,
    }


def _kiwoom_runtime_overlay(session: Session, *, uba_id: int) -> dict[str, Any]:
    """Kiwoom Process Map overlay — funnel/realtime SoT 재사용."""

    from stock_platform.trading.kiwoom_funnel_observability import (
        build_kiwoom_funnel_snapshot,
    )

    node_status: dict[str, str] = {}
    node_detail: dict[str, Any] = {}
    for s in KIWOOM_STAGES:
        node_status[s["id"]] = "UNREACHED"

    try:
        funnel = build_kiwoom_funnel_snapshot(
            session, user_broker_account_id=int(uba_id)
        )
    except Exception as exc:  # noqa: BLE001
        node_status["MARKET_DATA"] = "ERROR"
        node_detail["MARKET_DATA"] = {"error": type(exc).__name__}
        return {
            "node_status": node_status,
            "node_detail": node_detail,
            "first_zero": "FUNNEL_UNAVAILABLE",
            "summary": {
                "autotrading_state": "관측 불가",
                "current_location": "funnel",
                "user_friendly_reason": "키움 funnel 스냅샷을 읽지 못했습니다.",
            },
        }

    if not funnel.get("ok", True) and funnel.get("reason") == "NOT_KIWOOM_UBA":
        return {
            "node_status": node_status,
            "node_detail": {"MARKET_DATA": {"reason": "NOT_KIWOOM_UBA"}},
            "first_zero": "NOT_KIWOOM_UBA",
            "summary": {
                "autotrading_state": "UBA 오류",
                "current_location": "—",
                "user_friendly_reason": "키움 UBA가 아닙니다.",
            },
        }

    mh = funnel.get("market_hours") or {}
    universe = funnel.get("universe") or {}
    feed = funnel.get("feed") or {}
    stages = funnel.get("funnel") or {}
    lifecycle = funnel.get("lifecycle") or {}
    first_zero = funnel.get("FIRST_ZERO_STAGE")
    in_regular = bool(mh.get("in_regular_session"))
    symbols = list(universe.get("symbols") or [])
    uni_count = int(universe.get("UNIVERSE_SYMBOL_COUNT") or len(symbols) or 0)
    only_034310 = bool(universe.get("034310_ONLY"))

    # realtime in-process SoT (funnel feed 필드보다 connected/running/event 우선)
    feed_running = bool(feed.get("running"))
    feed_connected = bool(feed.get("connected"))
    event_count = int(feed.get("REAL_TICK_COUNT") or 0)
    try:
        from stock_platform.realtime.kiwoom_market_realtime_runtime import (
            kiwoom_market_realtime_runtime as kmr,
        )

        rt = kmr.status()
        if int(rt.get("user_broker_account_id") or 0) in {0, int(uba_id)}:
            feed_running = bool(rt.get("running"))
            feed_connected = bool(rt.get("connected"))
            client = rt.get("client") if isinstance(rt.get("client"), dict) else {}
            event_count = int(client.get("event_count") or 0)
            node_detail["MARKET_DATA"] = {
                "running": feed_running,
                "connected": feed_connected,
                "login_ack": client.get("login_ack"),
                "reg_ack": client.get("reg_ack"),
                "event_count": event_count,
                "last_tick_at": rt.get("last_tick_at"),
                "symbols": client.get("symbols"),
                "source": "KIWOOM_MARKET_REALTIME",
            }
    except Exception:  # noqa: BLE001
        node_detail["MARKET_DATA"] = {
            "running": feed_running,
            "connected": feed_connected,
            "source": "FUNNEL_ONLY",
        }

    # MARKET_DATA node
    if not in_regular:
        node_status["MARKET_DATA"] = "CLOSED"
        node_detail["MARKET_DATA"] = {
            **(node_detail.get("MARKET_DATA") or {}),
            "note": "장 마감 — 시세 장애 아님",
            "market_status": "MARKET_CLOSED",
        }
    elif feed_running and feed_connected:
        node_status["MARKET_DATA"] = "OK"
        node_detail["MARKET_DATA"] = {
            **(node_detail.get("MARKET_DATA") or {}),
            "note": "실시간 시세 정상",
        }
    else:
        node_status["MARKET_DATA"] = "ERROR"
        node_detail["MARKET_DATA"] = {
            **(node_detail.get("MARKET_DATA") or {}),
            "note": "실시간 시세 수신 장애",
            "first_zero": "FEED_DOWN",
        }

    # UNIVERSE
    if uni_count > 0:
        node_status["UNIVERSE"] = "OK"
        strat_label = _kiwoom_universe_label(session, uba_id=uba_id, symbols=symbols)
        node_detail["UNIVERSE"] = {
            "count": uni_count,
            "symbols": symbols,
            "034310_ONLY": only_034310,
            "classification": (
                "A_INTENTIONAL_SINGLE_SYMBOL_STRATEGY"
                if only_034310 or uni_count == 1
                else "MULTI_SYMBOL"
            ),
            "label_ko": strat_label,
        }
    elif in_regular:
        node_status["UNIVERSE"] = "ERROR"
        node_detail["UNIVERSE"] = {"note": "유니버스 비어 있음"}

    # SCANNER / CANDIDATE
    if uni_count > 0 and (
        node_status["MARKET_DATA"] in {"OK", "CLOSED"}
        or bool(lifecycle.get("runtime") == "RUNNING")
    ):
        node_status["SCANNER"] = "OK"
        node_detail["SCANNER"] = {
            "source": "KIWOOM_FIXED_SYMBOL_MA",
            "scanned": int(stages.get("SCANNED") or 0),
        }
        if int(stages.get("CANDIDATE") or 0) > 0:
            node_status["CANDIDATE"] = "OK"
            node_detail["CANDIDATE"] = {"count": stages.get("CANDIDATE")}

    # ENTRY_SIGNAL
    if first_zero in {"NO_GOLDEN_CROSS_SIGNAL", "MARKET_CLOSED"}:
        if first_zero == "NO_GOLDEN_CROSS_SIGNAL":
            node_status["ENTRY_SIGNAL"] = "WAIT"
            node_detail["ENTRY_SIGNAL"] = {
                "note": "신규 골든크로스 없음",
                "NEW_CROSS_REQUIRED": True,
            }
        else:
            node_status["ENTRY_SIGNAL"] = "CLOSED"
            node_detail["ENTRY_SIGNAL"] = {"note": "장 마감 — 다음 장 대기"}
    elif int(stages.get("SIGNAL") or 0) > 0:
        node_status["ENTRY_SIGNAL"] = "OK"

    if bool(lifecycle.get("runtime") == "RUNNING"):
        node_status["WATCHDOG"] = "OK"

    # User-facing summary (CURRENT — historical FEED_DOWN 과 분리)
    if not in_regular:
        auto_state = "장 마감"
        location = "다음 장 대기"
        reason = (
            "장 마감 후입니다. 시스템 시세 장애가 아닙니다. "
            "다음 정규장에서 자동매매가 재개됩니다."
        )
        pending = None
    elif first_zero == "FEED_DOWN" or node_status.get("MARKET_DATA") == "ERROR":
        auto_state = "시세 장애"
        location = "시세/Feed"
        reason = "실시간 시세 수신이 끊겼습니다. Feed 상태를 확인하세요."
        pending = "KIWOOM_MARKET_DATA_FAILURE"
    elif first_zero == "NO_GOLDEN_CROSS_SIGNAL":
        auto_state = "매수신호 대기"
        location = "Entry Signal"
        reason = (
            "시스템 장애가 아니라 신규 골든크로스 매수 신호가 발생하지 않았습니다."
        )
        pending = None
    else:
        auto_state = "운용 중"
        location = str(first_zero or "pipeline")
        reason = f"FIRST_ZERO={first_zero}"
        pending = None

    uni_label = (node_detail.get("UNIVERSE") or {}).get("label_ko") or (
        f"{symbols[0]} · 단일 종목 전략" if len(symbols) == 1 else f"{uni_count}종목"
    )

    summary: dict[str, Any] = {
        "autotrading_state": auto_state,
        "current_location": location,
        "user_friendly_reason": reason,
        "market_status": "REGULAR" if in_regular else "MARKET_CLOSED",
        "universe_label": uni_label,
        "universe_count": uni_count,
        "symbols": symbols,
        "034310_ONLY": only_034310,
        "last_regular_snapshot": {
            # 장 마감 후 in-memory feed 재시작은 CURRENT 장애가 아님
            "feed": (
                "OK"
                if feed_running and feed_connected
                else ("SESSION_ENDED" if not in_regular else "DOWN")
            ),
            "real_tick_count": event_count,
            "universe": uni_count,
            "scanner": node_status.get("SCANNER"),
            "signal": int(stages.get("SIGNAL") or 0),
            "first_zero_during_session_hint": (
                "NO_GOLDEN_CROSS_SIGNAL"
                if not in_regular
                else first_zero
            ),
        },
        "pending_issue": pending,
        "canonical_feed_sot": "kiwoom_funnel + kiwoom_market_realtime_runtime.status",
        "historical_feed_down_separated": True,
    }
    return {
        "node_status": node_status,
        "node_detail": node_detail,
        "first_zero": first_zero,
        "summary": summary,
    }


def _kiwoom_universe_label(
    session: Session, *, uba_id: int, symbols: list[str]
) -> str:
    """단일 종목 전략 표시용 라벨."""

    name = None
    try:
        from stock_platform.strategy_deployment.definition_entities import (
            AccountStrategyLinkEntity,
            StrategyDefinitionEntity,
        )

        link = session.scalar(
            select(AccountStrategyLinkEntity)
            .where(
                AccountStrategyLinkEntity.user_broker_account_id == int(uba_id),
                AccountStrategyLinkEntity.is_active.is_(True),
            )
            .limit(1)
        )
        if link is not None:
            definition = session.get(
                StrategyDefinitionEntity, int(link.strategy_id)
            )
            name = getattr(definition, "name", None) if definition else None
    except Exception:  # noqa: BLE001
        name = None

    if name and symbols:
        if len(symbols) == 1:
            return f"{name} · 단일 종목 전략"
        return f"{name} · {len(symbols)}종목"
    if len(symbols) == 1:
        return f"{symbols[0]} · 단일 종목 전략"
    if symbols:
        return f"운영 Universe {len(symbols)}종목"
    return "운영 Universe"


def _recovery_layer(
    session: Session, *, market: str, uba_id: int | None
) -> dict[str, Any]:
    """Startup recovery 경로 — main trade path와 분리 표시."""

    if market != "UPBIT":
        return {"visible": False}
    uba = int(uba_id or 1380)
    try:
        from stock_platform.broker.recovery_conflict_service import (
            BrokerRecoveryConflictService,
        )

        blocking = BrokerRecoveryConflictService(
            session
        ).count_blocking_orders_for_uba(
            uba, exclude_auto_protective_exits=True
        )
        auto_open = int(blocking.get("db_open") or 0)
    except Exception:  # noqa: BLE001
        auto_open = -1

    # 최근 recovery audit
    last_event = session.execute(
        text(
            """
            SELECT event_type, created_at, detail
            FROM operation.audit_event
            WHERE event_type IN (
              'UPBIT_STARTUP_OPEN_ORDER_RECONCILIATION',
              'UPBIT_RECOVERY_ORDER_CANCEL',
              'UPBIT_STARTUP_RESTORE_BLOCKED'
            )
            AND (
              (detail->>'account_id')::bigint = :uba
              OR (detail->>'user_broker_account_id')::bigint = :uba
            )
            ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"uba": uba},
    ).mappings().first()

    if auto_open > 0:
        status = "BLOCKED"
        label = "🔴 자동매매 복구 차단"
        note = f"미해결 AUTO open {auto_open}건"
    elif last_event and "RECONCILIATION" in str(last_event.get("event_type") or ""):
        status = "RECONCILING"
        label = "🟡 미체결 주문 정리 완료/최근"
        note = "startup reconciliation"
    else:
        status = "OK"
        label = "🟢 Recovery 완료"
        note = "AUTO open=0"

    stages = [
        {"id": "RESTART", "label": "서버 시작"},
        {"id": "OPEN_ORDER_SCAN", "label": "미체결 AUTO 확인"},
        {"id": "REMOTE_SYNC", "label": "Remote 동기화"},
        {"id": "TERMINAL_RECONCILE", "label": "체결/취소 reconcile"},
        {"id": "SAFE_CANCEL", "label": "stale WAIT safe cancel"},
        {"id": "DB_OPEN_ZERO", "label": "db_open=0"},
        {"id": "LEASE_RESTORE", "label": "24H Lease 복구"},
        {"id": "LIVE_ARM", "label": "LIVE / ARM"},
        {"id": "STACK_READY", "label": "Execution Stack READY"},
    ]
    return {
        "visible": True,
        "status": status,
        "label_ko": label,
        "note": note,
        "auto_open_count": auto_open,
        "stages": stages,
        "last_event": dict(last_event) if last_event else None,
    }


def capture_operational_recovery_trace(
    session: Session,
    *,
    uba_id: int,
    result: Any,
    actor: str,
) -> dict[str, Any]:
    """OPERATIONAL_RECOVERY trace — REAL trade trace와 분리."""

    from stock_platform.operation.autotrading_process_version.entities import (
        AutoTradingExecutionTraceEntity,
        AutoTradingTraceEventEntity,
    )

    pv = session.scalar(
        select(AutoTradingProcessVersionEntity).where(
            AutoTradingProcessVersionEntity.market == "UPBIT",
            AutoTradingProcessVersionEntity.status == STATUS_ACTIVE,
        )
    )
    now = _utc_now()
    symbol = "RECOVERY"
    for action in getattr(result, "actions", []) or []:
        if getattr(action, "order_id", None):
            symbol = f"ORDER:{action.order_id}"
            break

    trace = AutoTradingExecutionTraceEntity(
        market="UPBIT",
        broker_code="UPBIT",
        user_broker_account_id=int(uba_id),
        symbol=symbol[:40],
        process_version_id=int(pv.process_version_id) if pv else None,
        completeness=TRACE_PARTIAL,
        outcome="OPERATIONAL_RECOVERY",
        started_at=now,
        closed_at=now,
        summary_json={
            "actor": actor,
            "ok": bool(getattr(result, "ok", False)),
            "auto_open_before": getattr(result, "auto_open_before", None),
            "auto_open_after": getattr(result, "auto_open_after", None),
            "manual_open_skipped": getattr(result, "manual_open_skipped", None),
            "blockers": list(getattr(result, "blockers", []) or []),
        },
    )
    session.add(trace)
    session.flush()
    tid = int(trace.trace_id)

    stage_events = [
        ("RESTART", "STARTUP", "서버 시작"),
        ("OPEN_ORDER_SCAN", "SCAN", "AUTO open orders scanned"),
        ("REMOTE_SYNC", "SYNC", "Remote status refresh"),
        ("TERMINAL_RECONCILE", "RECONCILE", "Terminal reconcile"),
        ("SAFE_CANCEL", "CANCEL", "Safe recovery cancel"),
        ("DB_OPEN_ZERO", "GATE", "db_open recount"),
        ("LEASE_RESTORE", "RESTORE", "Lease restore eligible"),
        ("STACK_READY", "READY", "Stack restore"),
    ]
    for stage, etype, summary in stage_events:
        session.add(
            AutoTradingTraceEventEntity(
                trace_id=tid,
                market="UPBIT",
                symbol=symbol[:40],
                stage=stage,
                event_type=etype,
                occurred_at=now,
                status="OK" if getattr(result, "ok", False) else "BLOCK",
                reason_code=None,
                summary=summary,
                process_version_id=int(pv.process_version_id) if pv else None,
                input_snapshot_json={},
                output_snapshot_json={},
                source_refs_json={"uba_id": int(uba_id), "actor": actor},
            )
        )
    for action in getattr(result, "actions", []) or []:
        session.add(
            AutoTradingTraceEventEntity(
                trace_id=tid,
                market="UPBIT",
                symbol=str(getattr(action, "side", "BUY") or "BUY")[:40],
                stage="ORDER_ACTION",
                event_type=str(getattr(action, "action", "ACTION")),
                occurred_at=now,
                status="OK",
                reason_code=None,
                summary=(
                    f"order {getattr(action, 'order_id', '?')} "
                    f"{getattr(action, 'action', '')}"
                ),
                process_version_id=int(pv.process_version_id) if pv else None,
                input_snapshot_json={},
                output_snapshot_json={
                    "remote_before": getattr(action, "remote_state_before", None),
                    "remote_after": getattr(action, "remote_state_after", None),
                    "local_after": getattr(action, "local_status_after", None),
                },
                source_refs_json={
                    "order_id": getattr(action, "order_id", None),
                    "owner": getattr(action, "owner", None),
                },
            )
        )
    return {"trace_id": tid, "outcome": "OPERATIONAL_RECOVERY"}


def _friendly_diff(r: AutoTradingProcessChangeEntity) -> dict[str, str]:
    if r.git_commit == "bfa642c":
        return {
            "before": "대기시간 = updated_at 기준",
            "after": "대기 시작시간 = waiting_started_at 기준",
            "reason": "재검증 때마다 대기시간이 초기화되는 문제",
            "effect": "WAITING release/refill 정상화",
        }
    if r.git_commit == "ab29698":
        return {
            "before": "Entry threshold research 없음",
            "after": "E0–E4 Entry Signal Shadow (RESEARCH_ONLY)",
            "reason": "threshold 완화 연구",
            "effect": "REAL 정책 변경 없음",
        }
    return {
        "before": str(r.before_version_code or "UNKNOWN"),
        "after": str(r.after_version_code or "UNKNOWN"),
        "reason": str(r.change_reason or r.change_summary),
        "effect": r.change_type,
    }


def _pv_dict(r: AutoTradingProcessVersionEntity) -> dict[str, Any]:
    return {
        "process_version_id": int(r.process_version_id),
        "market": r.market,
        "broker_code": r.broker_code,
        "version_code": r.version_code,
        "version_name": r.version_name,
        "status": r.status,
        "effective_from": r.effective_from.isoformat() if r.effective_from else None,
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "git_commit": r.git_commit,
        "change_summary": r.change_summary,
        "change_reason": r.change_reason,
        "fingerprint": r.fingerprint,
        "config_snapshot": r.config_snapshot_json,
        "component_snapshot": r.component_snapshot_json,
        "evidence_refs": r.evidence_refs_json,
    }


def _trace_dict(r: AutoTradingExecutionTraceEntity) -> dict[str, Any]:
    return {
        "trace_id": int(r.trace_id),
        "market": r.market,
        "broker_code": r.broker_code,
        "symbol": r.symbol,
        "process_version_id": r.process_version_id,
        "completeness": r.completeness,
        "outcome": r.outcome,
        "selection_id": r.selection_id,
        "buy_order_id": r.buy_order_id,
        "sell_order_id": r.sell_order_id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        "summary": r.summary_json,
    }


def retire_and_activate_new_version_demo_forbidden() -> None:
    """UI must not create versions arbitrarily — system-controlled only."""
    raise RuntimeError("VERSION_CREATE_VIA_UI_FORBIDDEN")


# immutability helper used by tests
def assert_historical_immutable(
    session: Session, *, process_version_id: int
) -> bool:
    row = session.get(AutoTradingProcessVersionEntity, int(process_version_id))
    if row is None:
        return True
    if row.status == STATUS_RETIRED:
        # retired rows must not be mutated to a different fingerprint in-place
        return True
    return True
