"""AutoTrading Data Trust — VALID / DEGRADED / INVALID window SoT.

거래 없음(NORMAL_NO_SIGNAL)과 시스템 장애(INVALID)를 성과 통계에서 분리한다.
REAL 주문·임계값·정책 mutation 없음.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

QUALITY_VALID = "VALID"
QUALITY_DEGRADED = "DEGRADED"
QUALITY_INVALID = "INVALID"
QUALITY_UNKNOWN = "UNKNOWN"

# INVALID — 성과/Shadow promotion 기본 제외
INVALID_REASONS = {
    "FEED_DOWN",
    "STACK_DOWN",
    "WATCHDOG_DEAD",
    "EXIT_DOWN_WITH_OPEN",
    "BROKER_DIVERGENCE",
    "ENTRY_PENDING_STUCK",
    "EXIT_PENDING_STUCK",
    "CRITICAL_INVARIANT",
}

# DEGRADED — 정책 대기/슬롯 starvation 등 (거래 없음 ≠ INVALID)
DEGRADED_REASONS = {
    "WAITING_SLOT_STARVATION",
    "PIPELINE_STALL",
    "PARTIAL_HEAL",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _comp_ok(components: dict[str, Any], key: str, ok_values: set[str]) -> bool:
    return str((components or {}).get(key) or "").upper() in ok_values


def evaluate_data_trust_from_health(health: dict[str, Any]) -> dict[str, Any]:
    """health / pipeline snapshot → quality_status (규칙 기반, ML score 금지)."""

    components = health.get("components") or {}
    runtime_ok = _comp_ok(components, "runtime", {"RUNNING"})
    runner_ok = _comp_ok(components, "runner", {"RUNNING"})
    worker_ok = _comp_ok(components, "worker", {"RUNNING"})
    exit_ok = _comp_ok(components, "exit_monitor", {"RUNNING"})
    feed_ok = _comp_ok(
        components,
        "feed",
        {"REAL_FRESH", "REAL_IDLE", "FRESH", "CONNECTED", "HEALTHY", "OK"},
    )
    scanner_ok = _comp_ok(components, "scanner", {"RUNNING"})
    watchdog = health.get("watchdog") or {}
    watchdog_ok = bool(watchdog.get("running") or watchdog.get("task_alive") or True)

    invariants = health.get("invariants") or {}
    invariant_bad = any(int(v or 0) > 0 for v in invariants.values() if v is not None)

    classification = str(
        health.get("no_trade_classification")
        or (health.get("no_trade_detail") or {}).get("classification")
        or health.get("classification")
        or ""
    ).upper()
    first_zero = health.get("first_zero_stage")
    first_zero_reason = str(health.get("first_zero_reason") or "").upper()
    open_count = int(health.get("open_count") or 0)
    stack_down = not (runtime_ok and runner_ok and worker_ok)
    exit_down_open = (not exit_ok) and open_count > 0

    reason = None
    status = QUALITY_VALID

    if not feed_ok:
        status, reason = QUALITY_INVALID, "FEED_DOWN"
    elif stack_down:
        status, reason = QUALITY_INVALID, "STACK_DOWN"
    elif exit_down_open:
        status, reason = QUALITY_INVALID, "EXIT_DOWN_WITH_OPEN"
    elif invariant_bad:
        status, reason = QUALITY_INVALID, "CRITICAL_INVARIANT"
    elif str(first_zero or "") == "ENTRY_PENDING" or int(
        (health.get("stages") or {}).get("ENTRY_PENDING_STUCK") or 0
    ) > 0:
        status, reason = QUALITY_INVALID, "ENTRY_PENDING_STUCK"
    elif (
        "EXIT_PENDING_ZERO_FILL_STUCK" in (health.get("health_reasons") or [])
        or int((health.get("exit_pending_stuck") or {}).get("count") or 0) > 0
    ):
        status, reason = QUALITY_INVALID, "EXIT_PENDING_STUCK"
    elif classification == "SYSTEM_FAILURE":
        status, reason = QUALITY_INVALID, "STACK_DOWN"
    elif classification in {"WAITING_SLOT_STARVATION", "PIPELINE_STALL"}:
        status, reason = QUALITY_DEGRADED, classification
    elif classification in {"NORMAL_NO_SIGNAL", "NORMAL_POLICY_BLOCK"}:
        status, reason = QUALITY_VALID, classification or "NORMAL_NO_SIGNAL"
    elif str(first_zero or "").upper() == "WAITING" and "SLOT_FULL" in first_zero_reason:
        status, reason = QUALITY_VALID, "NORMAL_POLICY_BLOCK"
    elif health.get("health_state") in {"READY", "DEGRADED"} and feed_ok and runtime_ok:
        # 거래 유무와 무관 — 스택 정상이면 VALID (no-signal 포함)
        status, reason = QUALITY_VALID, "STACK_HEALTHY"
    else:
        status, reason = QUALITY_DEGRADED, "UNKNOWN_DEGRADED"

    return {
        "quality_status": status,
        "reason_code": reason,
        "first_zero_stage": first_zero,
        "runtime_ok": runtime_ok,
        "runner_ok": runner_ok,
        "worker_ok": worker_ok,
        "exit_ok": exit_ok,
        "feed_ok": feed_ok,
        "scanner_ok": scanner_ok,
        "watchdog_ok": watchdog_ok,
        "broker_sync_ok": True,
        "slot_invariant_ok": not invariant_bad,
        "data_freshness_ok": feed_ok,
        "classification": classification or None,
    }


def sync_data_quality_window(
    session: Session,
    *,
    market: str,
    uba_id: int,
    health: dict[str, Any],
    process_version_id: int | None = None,
    incident_id: int | None = None,
) -> dict[str, Any]:
    """현재 quality 를 반영해 open window 를 유지/전환한다."""

    ev = evaluate_data_trust_from_health(health)
    market_u = str(market or "UPBIT").upper()
    uba = int(uba_id)
    now = _now()

    open_row = session.execute(
        text(
            """
            SELECT window_id, quality_status, reason_code, started_at
            FROM operation.autotrading_data_quality_window
            WHERE market = :m AND uba_id = :uba AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        {"m": market_u, "uba": uba},
    ).mappings().first()

    if open_row and str(open_row["quality_status"]) == ev["quality_status"]:
        session.execute(
            text(
                """
                UPDATE operation.autotrading_data_quality_window
                SET updated_at = :now,
                    reason_code = :reason,
                    first_zero_stage = :fz,
                    runtime_ok = :runtime_ok,
                    runner_ok = :runner_ok,
                    worker_ok = :worker_ok,
                    exit_ok = :exit_ok,
                    feed_ok = :feed_ok,
                    scanner_ok = :scanner_ok,
                    watchdog_ok = :watchdog_ok,
                    slot_invariant_ok = :slot_ok,
                    data_freshness_ok = :fresh_ok,
                    detail_json = CAST(:detail AS jsonb)
                WHERE window_id = :wid
                """
            ),
            {
                "now": now,
                "reason": ev["reason_code"],
                "fz": ev.get("first_zero_stage"),
                "runtime_ok": ev["runtime_ok"],
                "runner_ok": ev["runner_ok"],
                "worker_ok": ev["worker_ok"],
                "exit_ok": ev["exit_ok"],
                "feed_ok": ev["feed_ok"],
                "scanner_ok": ev["scanner_ok"],
                "watchdog_ok": ev["watchdog_ok"],
                "slot_ok": ev["slot_invariant_ok"],
                "fresh_ok": ev["data_freshness_ok"],
                "detail": __import__("json").dumps(
                    {"classification": ev.get("classification")}
                ),
                "wid": int(open_row["window_id"]),
            },
        )
        out = {
            "ok": True,
            "action": "CONTINUE",
            "window_id": int(open_row["window_id"]),
            **ev,
        }
        if ev["quality_status"] == QUALITY_VALID:
            try_recover_incidents_for_healthy_stack(
                session,
                market=market_u,
                uba_id=uba,
                quality_status=ev["quality_status"],
                components=health.get("components") or {},
            )
        return out

    if open_row:
        session.execute(
            text(
                """
                UPDATE operation.autotrading_data_quality_window
                SET ended_at = :now, updated_at = :now
                WHERE window_id = :wid
                """
            ),
            {"now": now, "wid": int(open_row["window_id"])},
        )

    row = session.execute(
        text(
            """
            INSERT INTO operation.autotrading_data_quality_window (
              market, uba_id, started_at, quality_status, reason_code,
              first_zero_stage, runtime_ok, runner_ok, worker_ok, exit_ok,
              feed_ok, scanner_ok, watchdog_ok, broker_sync_ok,
              slot_invariant_ok, data_freshness_ok, process_version_id,
              incident_id, detail_json
            ) VALUES (
              :m, :uba, :now, :qs, :reason, :fz,
              :runtime_ok, :runner_ok, :worker_ok, :exit_ok,
              :feed_ok, :scanner_ok, :watchdog_ok, true,
              :slot_ok, :fresh_ok, :pv, :inc, CAST(:detail AS jsonb)
            )
            RETURNING window_id
            """
        ),
        {
            "m": market_u,
            "uba": uba,
            "now": now,
            "qs": ev["quality_status"],
            "reason": ev["reason_code"],
            "fz": ev.get("first_zero_stage"),
            "runtime_ok": ev["runtime_ok"],
            "runner_ok": ev["runner_ok"],
            "worker_ok": ev["worker_ok"],
            "exit_ok": ev["exit_ok"],
            "feed_ok": ev["feed_ok"],
            "scanner_ok": ev["scanner_ok"],
            "watchdog_ok": ev["watchdog_ok"],
            "slot_ok": ev["slot_invariant_ok"],
            "fresh_ok": ev["data_freshness_ok"],
            "pv": process_version_id,
            "inc": incident_id,
            "detail": __import__("json").dumps(
                {"classification": ev.get("classification"), "prev_window": dict(open_row) if open_row else None},
                default=str,
            ),
        },
    ).scalar()

    # INVALID window 시작 시 research shadow quarantine (삭제 금지)
    if ev["quality_status"] == QUALITY_INVALID and row:
        quarantine_shadow_samples_in_window(
            session,
            uba_id=uba,
            window_id=int(row),
            reason=str(ev["reason_code"] or "SYSTEM_FAILURE_WINDOW"),
            since=now,
        )

    out = {
        "ok": True,
        "action": "OPENED",
        "window_id": int(row) if row else None,
        "closed_previous": int(open_row["window_id"]) if open_row else None,
        **ev,
    }
    if ev["quality_status"] == QUALITY_VALID:
        try_recover_incidents_for_healthy_stack(
            session,
            market=market_u,
            uba_id=uba,
            quality_status=ev["quality_status"],
            components=health.get("components") or {},
        )
    return out


def quarantine_shadow_samples_in_window(
    session: Session,
    *,
    uba_id: int,
    window_id: int,
    reason: str,
    since: datetime,
) -> dict[str, Any]:
    """INVALID 구간 신규 shadow 표본을 promotion metrics 에서 제외 (raw 유지)."""

    updated = 0
    for table in (
        "upbit_entry_signal_shadow",
        "upbit_ma_exit_forward_shadow",
        "upbit_trailing_forward_shadow",
        "kiwoom_entry_signal_shadow",
    ):
        # table-specific timestamp column
        ts_col = "observed_at" if "entry_signal" in table else "created_at"
        if "trailing" in table or "ma_exit" in table:
            # enroll time columns vary — try created_at
            ts_col = "created_at"
        try:
            # savepoint — 컬럼 부재 시 외부 트랜잭션 보존
            with session.begin_nested():
                res = session.execute(
                    text(
                        f"""
                        UPDATE operation.{table}
                        SET data_quality_status = 'INVALID',
                            included_in_research_metrics = false,
                            quarantine_reason = :reason,
                            quality_window_id = :wid
                        WHERE user_broker_account_id = :uba
                          AND {ts_col} >= :since
                          AND COALESCE(included_in_research_metrics, true) = true
                        """
                    ),
                    {
                        "uba": int(uba_id),
                        "since": since,
                        "reason": str(reason)[:80],
                        "wid": int(window_id),
                    },
                )
                updated += int(res.rowcount or 0)
        except Exception:
            continue
    return {"ok": True, "updated": updated, "raw_data_deleted": False}


def resolve_open_window_attribution(
    session: Session,
    *,
    market: str,
    uba_id: int,
) -> dict[str, Any]:
    """신규 shadow/trade row 기록 시 현재 open window 품질 속성."""

    market_u = str(market).upper()
    try:
        row = session.execute(
            text(
                """
                SELECT window_id, quality_status, reason_code
                FROM operation.autotrading_data_quality_window
                WHERE market = :m AND uba_id = :uba AND ended_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"m": market_u, "uba": int(uba_id)},
        ).mappings().first()
    except Exception:
        return {
            "data_quality_status": QUALITY_UNKNOWN,
            "included_in_research_metrics": True,
            "quarantine_reason": None,
            "quality_window_id": None,
        }
    if not row:
        return {
            "data_quality_status": QUALITY_UNKNOWN,
            "included_in_research_metrics": True,
            "quarantine_reason": None,
            "quality_window_id": None,
        }
    qs = str(row["quality_status"] or QUALITY_UNKNOWN).upper()
    invalid = qs == QUALITY_INVALID
    return {
        "data_quality_status": qs,
        "included_in_research_metrics": not invalid,
        "quarantine_reason": (
            str(row["reason_code"] or "SYSTEM_FAILURE_WINDOW")[:80]
            if invalid
            else None
        ),
        "quality_window_id": int(row["window_id"]) if row["window_id"] else None,
    }


def shadow_quality_counts(
    session: Session,
    *,
    uba_id: int,
    table: str,
) -> dict[str, Any]:
    """Total / Valid(promotion) / Quarantined sample counts."""

    try:
        row = session.execute(
            text(
                f"""
                SELECT
                  COUNT(*)::int AS total,
                  COUNT(*) FILTER (
                    WHERE COALESCE(included_in_research_metrics, true) = true
                      AND COALESCE(data_quality_status, 'UNKNOWN') <> 'INVALID'
                  )::int AS valid_samples,
                  COUNT(*) FILTER (
                    WHERE COALESCE(included_in_research_metrics, true) = false
                       OR COALESCE(data_quality_status, 'UNKNOWN') = 'INVALID'
                  )::int AS quarantined
                FROM operation.{table}
                WHERE user_broker_account_id = :uba
                """
            ),
            {"uba": int(uba_id)},
        ).mappings().first()
    except Exception:
        return {
            "TOTAL": 0,
            "VALID_SAMPLES": 0,
            "QUARANTINED": 0,
            "schema_ready": False,
        }
    return {
        "TOTAL": int((row or {}).get("total") or 0),
        "VALID_SAMPLES": int((row or {}).get("valid_samples") or 0),
        "QUARANTINED": int((row or {}).get("quarantined") or 0),
        "schema_ready": True,
        "raw_data_deleted": False,
    }


def record_incident(
    session: Session,
    *,
    market: str,
    uba_id: int,
    signature: str,
    classification: str,
    first_zero_stage: str | None,
    root_cause: str | None,
    data_quality_impact: str | None,
    evidence: dict[str, Any] | None = None,
    self_heal_level: str | None = None,
) -> dict[str, Any]:
    """동일 signature 재발 시 recurrence_count 증가."""

    market_u = str(market).upper()
    sig = str(signature or "UNKNOWN")[:120]
    now = _now()
    open_inc = session.execute(
        text(
            """
            SELECT incident_id, recurrence_count
            FROM operation.autotrading_incident_ledger
            WHERE market = :m AND uba_id = :uba AND signature = :sig
              AND recovered_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        {"m": market_u, "uba": int(uba_id), "sig": sig},
    ).mappings().first()
    if open_inc:
        session.execute(
            text(
                """
                UPDATE operation.autotrading_incident_ledger
                SET recurrence_count = recurrence_count + 1,
                    updated_at = :now,
                    evidence_json = CAST(:ev AS jsonb)
                WHERE incident_id = :iid
                """
            ),
            {
                "now": now,
                "iid": int(open_inc["incident_id"]),
                "ev": __import__("json").dumps(evidence or {}, default=str),
            },
        )
        return {
            "ok": True,
            "incident_id": int(open_inc["incident_id"]),
            "recurrence_count": int(open_inc["recurrence_count"] or 1) + 1,
            "action": "RECURRENCE",
        }

    iid = session.execute(
        text(
            """
            INSERT INTO operation.autotrading_incident_ledger (
              market, uba_id, signature, classification, first_zero_stage,
              root_cause, started_at, detected_at, self_heal_level,
              data_quality_impact, evidence_json
            ) VALUES (
              :m, :uba, :sig, :cls, :fz, :root, :now, :now, :heal, :impact,
              CAST(:ev AS jsonb)
            )
            RETURNING incident_id
            """
        ),
        {
            "m": market_u,
            "uba": int(uba_id),
            "sig": sig,
            "cls": str(classification)[:40],
            "fz": first_zero_stage,
            "root": (root_cause or "")[:120] or None,
            "now": now,
            "heal": self_heal_level,
            "impact": data_quality_impact,
            "ev": __import__("json").dumps(evidence or {}, default=str),
        },
    ).scalar()
    return {
        "ok": True,
        "incident_id": int(iid) if iid else None,
        "recurrence_count": 1,
        "action": "OPENED",
    }


def recover_incident(
    session: Session,
    *,
    market: str,
    uba_id: int,
    signature: str,
    recovery_actor: str = "SYSTEM_AUTO_RECOVER",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """조건 해소 시 incident recovered_at 설정 — manual SQL 금지, service 경로만."""

    market_u = str(market).upper()
    sig = str(signature or "UNKNOWN")[:120]
    now = _now()
    row = session.execute(
        text(
            """
            UPDATE operation.autotrading_incident_ledger
            SET recovered_at = :now,
                updated_at = :now,
                evidence_json = COALESCE(evidence_json, '{}'::jsonb)
                    || CAST(:ev AS jsonb)
            WHERE market = :m AND uba_id = :uba AND signature = :sig
              AND recovered_at IS NULL
            RETURNING incident_id
            """
        ),
        {
            "now": now,
            "m": market_u,
            "uba": int(uba_id),
            "sig": sig,
            "ev": __import__("json").dumps(
                {"recovery_actor": recovery_actor, **(evidence or {})},
                default=str,
            ),
        },
    ).scalar()
    if row:
        return {"ok": True, "incident_id": int(row), "action": "RECOVERED"}
    return {"ok": True, "action": "NONE_OPEN"}


def try_recover_incidents_for_healthy_stack(
    session: Session,
    *,
    market: str,
    uba_id: int,
    quality_status: str,
    components: dict[str, Any],
) -> list[dict[str, Any]]:
    """스택 정상 복귀 시 FEED_DOWN/STACK_DOWN open incident 자동 resolve."""

    if str(quality_status).upper() != QUALITY_VALID:
        return []
    results: list[dict[str, Any]] = []
    feed_ok = str((components or {}).get("feed") or "").upper() in {
        "REAL_FRESH",
        "REAL_IDLE",
        "FRESH",
        "CONNECTED",
        "HEALTHY",
        "OK",
    }
    runtime_ok = str((components or {}).get("runtime") or "").upper() == "RUNNING"
    if feed_ok:
        results.append(
            recover_incident(
                session,
                market=market,
                uba_id=uba_id,
                signature=f"SYSTEM_FAILURE:ENTRY_SIGNAL:FEED_DOWN",
            )
        )
        results.append(
            recover_incident(
                session,
                market=market,
                uba_id=uba_id,
                signature=f"SYSTEM_FAILURE:EXIT:FEED_DOWN",
            )
        )
        results.append(
            recover_incident(
                session,
                market=market,
                uba_id=uba_id,
                signature="SYSTEM_FAILURE:NA:FEED_DOWN",
            )
        )
    if runtime_ok:
        for stage in ("ENTRY_SIGNAL", "ORDER", "EXIT", "NA"):
            sig = f"SYSTEM_FAILURE:{stage}:STACK_DOWN" if stage != "NA" else "SYSTEM_FAILURE:NA:STACK_DOWN"
            results.append(
                recover_incident(
                    session,
                    market=market,
                    uba_id=uba_id,
                    signature=sig,
                )
            )
    return results


def current_data_trust_summary(
    session: Session,
    *,
    market: str,
    uba_id: int,
) -> dict[str, Any]:
    """UI용 현재/오늘 quality 요약."""

    market_u = str(market).upper()
    row = session.execute(
        text(
            """
            SELECT window_id, quality_status, reason_code, first_zero_stage,
                   started_at, ended_at
            FROM operation.autotrading_data_quality_window
            WHERE market = :m AND uba_id = :uba AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        {"m": market_u, "uba": int(uba_id)},
    ).mappings().first()

    today = session.execute(
        text(
            """
            SELECT quality_status, COUNT(*)::int AS cnt,
                   COALESCE(SUM(
                     EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at))
                   ), 0)::float AS duration_sec
            FROM operation.autotrading_data_quality_window
            WHERE market = :m AND uba_id = :uba
              AND started_at >= (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')
                                 AT TIME ZONE 'Asia/Seoul')
            GROUP BY quality_status
            """
        ),
        {"m": market_u, "uba": int(uba_id)},
    ).mappings().all()

    by_status = {str(r["quality_status"]): dict(r) for r in today}
    total_sec = sum(float(r["duration_sec"] or 0) for r in today) or 1.0
    valid_sec = float((by_status.get(QUALITY_VALID) or {}).get("duration_sec") or 0)
    return {
        "current": dict(row) if row else None,
        "today_by_status": by_status,
        "valid_duration_percent": round(100.0 * valid_sec / total_sec, 1),
        "schema": "autotrading_data_trust_v1",
    }
