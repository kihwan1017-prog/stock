"""Cross-market shadow research status — READ ONLY aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.constants import (
    KIWOOM_24H_SEMANTICS,
    KIWOOM_SAMPLE_IDENTITY,
    SOURCE_FORWARD as KIWOOM_SOURCE,
    VARIANT_K0,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.scheduler import (
    runtime_status as kiwoom_scheduler_runtime,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.service import (
    forward_collection_status as kiwoom_forward_status,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    SOURCE_FORWARD,
    UPBIT_SAMPLE_IDENTITY,
    VARIANT_E0,
    VARIANT_E2,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.scheduler import (
    runtime_status as upbit_scheduler_runtime,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
    forward_collection_status,
)

HORIZON_COLS = {
    5: "future_5m_return_pct",
    15: "future_15m_return_pct",
    30: "future_30m_return_pct",
    60: "future_60m_return_pct",
    240: "future_240m_return_pct",
    1440: "future_1440m_return_pct",
}

RESEARCH_REVIEW_MIN_E0_VALID = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _growth_counts(
    session: Session,
    *,
    table: str,
    uba_id: int,
    id_column: str,
    variant: str | None = None,
    hours: tuple[int, ...] = (1, 6, 24),
) -> dict[str, int]:
    now = _utc_now()
    out: dict[str, int] = {}
    for h in hours:
        since = now - timedelta(hours=h)
        var_clause = "AND variant = :var" if variant else ""
        params: dict[str, Any] = {"uba": int(uba_id), "since": since}
        if variant:
            params["var"] = variant
        n = session.scalar(
            text(
                f"""
                SELECT COUNT(DISTINCT {id_column})
                FROM operation.{table}
                WHERE user_broker_account_id = :uba
                  AND source = 'FORWARD_NATURAL'
                  AND created_at >= :since
                  {var_clause}
                  {"AND selection_id IS NOT NULL" if table == "upbit_entry_signal_shadow" else ""}
                """
            ),
            params,
        )
        out[f"LAST_{h}H_NEW_SAMPLES"] = int(n or 0)
    return out


def _horizon_metrics(
    session: Session,
    *,
    table: str,
    uba_id: int,
    variant: str,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for mins, col in HORIZON_COLS.items():
        label = f"{mins}M" if mins < 60 else ("1H" if mins == 60 else ("4H" if mins == 240 else "24H"))
        row = session.execute(
            text(
                f"""
                SELECT
                  COUNT(*) FILTER (
                    WHERE outcome_status = 'COMPLETED' AND {col} IS NOT NULL
                  ) AS matured_n,
                  COUNT(*) FILTER (
                    WHERE outcome_status = 'PENDING'
                  ) AS pending_n,
                  COUNT(*) FILTER (
                    WHERE outcome_status IN ('INSUFFICIENT_OUTCOME')
                       OR ({col} IS NULL AND outcome_status = 'COMPLETED')
                  ) AS missing_n,
                  AVG({col}) FILTER (
                    WHERE {col} IS NOT NULL
                      AND COALESCE(included_in_research_metrics, true) = true
                      AND COALESCE(data_quality_status, 'UNKNOWN') <> 'INVALID'
                  ) AS mean_ret,
                  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {col})
                    FILTER (WHERE {col} IS NOT NULL) AS median_ret,
                  COUNT(*) FILTER (WHERE {col} > 0) AS wins,
                  COUNT(*) FILTER (WHERE {col} IS NOT NULL) AS decided,
                  MIN({col}) AS worst,
                  MAX({col}) AS best
                FROM operation.{table}
                WHERE user_broker_account_id = :uba
                  AND source = 'FORWARD_NATURAL'
                  AND variant = :var
                  AND shadow_decision = 'PASS'
                """
            ),
            {"uba": int(uba_id), "var": variant},
        ).mappings().first()
        decided = int((row or {}).get("decided") or 0)
        wins = int((row or {}).get("wins") or 0)
        metrics[label] = {
            "MATURED_N": int((row or {}).get("matured_n") or 0),
            "PENDING_N": int((row or {}).get("pending_n") or 0),
            "MISSING_N": int((row or {}).get("missing_n") or 0),
            "MEAN_RETURN_PCT": (
                float(row["mean_ret"]) if row and row.get("mean_ret") is not None else None
            ),
            "MEDIAN_RETURN_PCT": (
                float(row["median_ret"])
                if row and row.get("median_ret") is not None
                else None
            ),
            "WIN_RATE": round(wins / decided, 4) if decided else None,
            "BEST_PCT": float(row["best"]) if row and row.get("best") is not None else None,
            "WORST_PCT": float(row["worst"]) if row and row.get("worst") is not None else None,
        }
    return metrics


def _upbit_paired_comparison(session: Session, *, uba_id: int) -> dict[str, int]:
    """E0 vs E2 — evaluated vs PASS paired semantics 분리."""

    base = int(uba_id)
    evaluated = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM (
              SELECT e0.selection_id
              FROM operation.upbit_entry_signal_shadow e0
              JOIN operation.upbit_entry_signal_shadow e2
                ON e0.user_broker_account_id = e2.user_broker_account_id
               AND e0.selection_id = e2.selection_id
               AND e0.source = e2.source
              WHERE e0.user_broker_account_id = :uba
                AND e0.source = 'FORWARD_NATURAL'
                AND e0.variant = 'E0' AND e2.variant = 'E2'
                AND e0.selection_id IS NOT NULL
            ) t
            """
        ),
        {"uba": base},
    )
    paired_pass = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM (
              SELECT e0.selection_id
              FROM operation.upbit_entry_signal_shadow e0
              JOIN operation.upbit_entry_signal_shadow e2
                ON e0.user_broker_account_id = e2.user_broker_account_id
               AND e0.selection_id = e2.selection_id
               AND e0.source = e2.source
              WHERE e0.user_broker_account_id = :uba
                AND e0.source = 'FORWARD_NATURAL'
                AND e0.variant = 'E0' AND e2.variant = 'E2'
                AND e0.selection_id IS NOT NULL
                AND e0.shadow_decision = 'PASS' AND e2.shadow_decision = 'PASS'
                AND COALESCE(e0.included_in_research_metrics, true) = true
                AND COALESCE(e2.included_in_research_metrics, true) = true
                AND COALESCE(e0.data_quality_status, 'UNKNOWN') <> 'INVALID'
                AND COALESCE(e2.data_quality_status, 'UNKNOWN') <> 'INVALID'
            ) t
            """
        ),
        {"uba": base},
    )
    e0_pass_only = session.scalar(
        text(
            """
            SELECT COUNT(DISTINCT e0.selection_id)
            FROM operation.upbit_entry_signal_shadow e0
            LEFT JOIN operation.upbit_entry_signal_shadow e2
              ON e0.user_broker_account_id = e2.user_broker_account_id
             AND e0.selection_id = e2.selection_id
             AND e0.source = e2.source AND e2.variant = 'E2'
             AND e2.shadow_decision = 'PASS'
            WHERE e0.user_broker_account_id = :uba
              AND e0.source = 'FORWARD_NATURAL'
              AND e0.variant = 'E0'
              AND e0.shadow_decision = 'PASS'
              AND e0.selection_id IS NOT NULL
              AND e2.shadow_id IS NULL
            """
        ),
        {"uba": base},
    )
    e2_pass_only = session.scalar(
        text(
            """
            SELECT COUNT(DISTINCT e2.selection_id)
            FROM operation.upbit_entry_signal_shadow e2
            LEFT JOIN operation.upbit_entry_signal_shadow e0
              ON e0.user_broker_account_id = e2.user_broker_account_id
             AND e0.selection_id = e2.selection_id
             AND e0.source = e2.source AND e0.variant = 'E0'
             AND e0.shadow_decision = 'PASS'
            WHERE e2.user_broker_account_id = :uba
              AND e2.source = 'FORWARD_NATURAL'
              AND e2.variant = 'E2'
              AND e2.shadow_decision = 'PASS'
              AND e2.selection_id IS NOT NULL
              AND e0.shadow_id IS NULL
            """
        ),
        {"uba": base},
    )
    return {
        "PAIRED_EVALUATED_N": int(evaluated or 0),
        "PAIRED_PASS_N": int(paired_pass or 0),
        "PAIRED_N": int(evaluated or 0),
        "E0_PASS_ONLY_N": int(e0_pass_only or 0),
        "E2_PASS_ONLY_N": int(e2_pass_only or 0),
        "E0_ONLY_N": int(e0_pass_only or 0),
        "E2_ONLY_N": int(e2_pass_only or 0),
    }


def _variant_pass_semantics(
    session: Session,
    *,
    uba_id: int,
    variant: str,
) -> dict[str, int]:
    """PASS / VALID / matured counts — natural opportunity pool과 분리."""

    row = session.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT selection_id) FILTER (
                WHERE selection_id IS NOT NULL
              ) AS natural_pool,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE selection_id IS NOT NULL AND shadow_decision = 'PASS'
              ) AS pass_sample,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE selection_id IS NOT NULL
                  AND shadow_decision = 'PASS'
                  AND COALESCE(included_in_research_metrics, true) = true
                  AND COALESCE(data_quality_status, 'UNKNOWN') <> 'INVALID'
              ) AS valid_pass_sample,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE selection_id IS NOT NULL
                  AND shadow_decision = 'PASS'
                  AND outcome_status = 'COMPLETED'
                  AND future_60m_return_pct IS NOT NULL
              ) AS matured_pass_1h,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE selection_id IS NOT NULL
                  AND shadow_decision = 'PASS'
                  AND future_240m_return_pct IS NOT NULL
              ) AS matured_pass_4h,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE selection_id IS NOT NULL
                  AND shadow_decision = 'PASS'
                  AND future_1440m_return_pct IS NOT NULL
              ) AS matured_pass_24h
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba
              AND source = 'FORWARD_NATURAL'
              AND variant = :var
            """
        ),
        {"uba": int(uba_id), "var": variant},
    ).mappings().first()
    r = row or {}
    return {
        "NATURAL_OPPORTUNITY_POOL": int(r.get("natural_pool") or 0),
        "PASS_SAMPLE": int(r.get("pass_sample") or 0),
        "VALID_PASS_SAMPLE": int(r.get("valid_pass_sample") or 0),
        "MATURED_PASS_1H": int(r.get("matured_pass_1h") or 0),
        "MATURED_PASS_4H": int(r.get("matured_pass_4h") or 0),
        "MATURED_PASS_24H": int(r.get("matured_pass_24h") or 0),
    }


def _horizon_pass_state_counts(
    session: Session,
    *,
    uba_id: int,
    variant: str,
    minutes: int,
    col: str,
) -> dict[str, int]:
    """Per-horizon PENDING/MATURED/MISSING — PASS sample only."""

    row = session.execute(
        text(
            f"""
            SELECT
              COUNT(*) FILTER (
                WHERE shadow_decision = 'PASS'
                  AND observed_at + (:mins || ' minutes')::interval > now()
              ) AS pending_n,
              COUNT(*) FILTER (
                WHERE shadow_decision = 'PASS'
                  AND observed_at + (:mins || ' minutes')::interval <= now()
                  AND {col} IS NOT NULL
              ) AS matured_n,
              COUNT(*) FILTER (
                WHERE shadow_decision = 'PASS'
                  AND observed_at + (:mins || ' minutes')::interval <= now()
                  AND {col} IS NULL
                  AND COALESCE(data_quality_status, 'UNKNOWN') = 'INVALID'
              ) AS quarantined_n,
              COUNT(*) FILTER (
                WHERE shadow_decision = 'PASS'
                  AND observed_at + (:mins || ' minutes')::interval <= now()
                  AND {col} IS NULL
                  AND COALESCE(data_quality_status, 'UNKNOWN') <> 'INVALID'
              ) AS missing_n
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba
              AND source = 'FORWARD_NATURAL'
              AND variant = :var
              AND selection_id IS NOT NULL
            """
        ),
        {"uba": int(uba_id), "var": variant, "mins": int(minutes)},
    ).mappings().first()
    r = row or {}
    return {
        "PENDING_N": int(r.get("pending_n") or 0),
        "MATURED_N": int(r.get("matured_n") or 0),
        "MISSING_N": int(r.get("missing_n") or 0),
        "QUARANTINED_N": int(r.get("quarantined_n") or 0),
    }


def _sample_counts_upbit(session: Session, *, uba_id: int) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    for var in (VARIANT_E0, VARIANT_E2):
        unique = session.scalar(
            text(
                """
                SELECT COUNT(DISTINCT selection_id)
                FROM operation.upbit_entry_signal_shadow
                WHERE user_broker_account_id = :uba
                  AND source = :src AND variant = :var
                  AND selection_id IS NOT NULL
                """
            ),
            {"uba": int(uba_id), "src": SOURCE_FORWARD, "var": var},
        )
        valid = session.scalar(
            text(
                """
                SELECT COUNT(DISTINCT selection_id)
                FROM operation.upbit_entry_signal_shadow
                WHERE user_broker_account_id = :uba
                  AND source = :src AND variant = :var
                  AND selection_id IS NOT NULL
                  AND COALESCE(included_in_research_metrics, true) = true
                  AND COALESCE(data_quality_status, 'UNKNOWN') <> 'INVALID'
                """
            ),
            {"uba": int(uba_id), "src": SOURCE_FORWARD, "var": var},
        )
        counts[var] = {
            "UNIQUE_SAMPLE": int(unique or 0),
            "VALID_SAMPLE": int(valid or 0),
        }
    return counts


def _research_health(*, valid_sample: int, pending_24h: int, quarantined: int) -> str:
    if quarantined > 0 and valid_sample == 0:
        return "DATA_QUALITY_BLOCKED"
    if valid_sample == 0:
        return "LOW_SAMPLE"
    if pending_24h > 0:
        return "MATURATION_PENDING"
    if valid_sample < RESEARCH_REVIEW_MIN_E0_VALID:
        return "LOW_SAMPLE"
    return "HEALTHY"


def build_upbit_research_status(
    session: Session,
    *,
    user_broker_account_id: int = 1380,
) -> dict[str, Any]:
    uba = int(user_broker_account_id)
    samples = _sample_counts_upbit(session, uba_id=uba)
    e0_sem = _variant_pass_semantics(session, uba_id=uba, variant=VARIANT_E0)
    e2_sem = _variant_pass_semantics(session, uba_id=uba, variant=VARIANT_E2)
    paired = _upbit_paired_comparison(session, uba_id=uba)
    horizon_state = {
        "E0": {
            "4H": _horizon_pass_state_counts(
                session,
                uba_id=uba,
                variant=VARIANT_E0,
                minutes=240,
                col="future_240m_return_pct",
            ),
            "24H": _horizon_pass_state_counts(
                session,
                uba_id=uba,
                variant=VARIANT_E0,
                minutes=1440,
                col="future_1440m_return_pct",
            ),
        },
        "E2": {
            "4H": _horizon_pass_state_counts(
                session,
                uba_id=uba,
                variant=VARIANT_E2,
                minutes=240,
                col="future_240m_return_pct",
            ),
            "24H": _horizon_pass_state_counts(
                session,
                uba_id=uba,
                variant=VARIANT_E2,
                minutes=1440,
                col="future_1440m_return_pct",
            ),
        },
    }
    growth_e0 = _growth_counts(
        session,
        table="upbit_entry_signal_shadow",
        uba_id=uba,
        id_column="selection_id",
        variant=VARIANT_E0,
    )
    e0_outcomes = _horizon_metrics(
        session, table="upbit_entry_signal_shadow", uba_id=uba, variant=VARIANT_E0
    )
    e2_outcomes = _horizon_metrics(
        session, table="upbit_entry_signal_shadow", uba_id=uba, variant=VARIANT_E2
    )
    fwd = forward_collection_status(session, uba_id=uba)
    try:
        from stock_platform.trading.autotrading_data_trust import shadow_quality_counts

        dq = shadow_quality_counts(
            session, uba_id=uba, table="upbit_entry_signal_shadow"
        )
    except Exception as exc:  # noqa: BLE001
        dq = {"QUARANTINED": 0, "error": type(exc).__name__}

    e0_valid = samples.get(VARIANT_E0, {}).get("VALID_SAMPLE", 0)
    pending_24h = e0_outcomes.get("24H", {}).get("PENDING_N", 0)
    matured_24h = e0_outcomes.get("24H", {}).get("MATURED_N", 0)
    review_ready = (
        e0_valid >= RESEARCH_REVIEW_MIN_E0_VALID
        and samples.get(VARIANT_E2, {}).get("VALID_SAMPLE", 0) > 0
        and pending_24h == 0
        and matured_24h >= RESEARCH_REVIEW_MIN_E0_VALID
        and int(dq.get("QUARANTINED") or 0) == 0
    )

    return {
        "market": "UPBIT",
        "UPBIT_SAMPLE_IDENTITY": UPBIT_SAMPLE_IDENTITY,
        "research_only": True,
        "REAL_POLICY_PROMOTION": False,
        "NATURAL_OPPORTUNITY_POOL": e0_sem["NATURAL_OPPORTUNITY_POOL"],
        "sample_semantics": {
            "labels": {
                "NATURAL_OPPORTUNITY_POOL": "전체 자연기회 (distinct selection_id)",
                "PASS_SAMPLE": "PASS 연구표본",
                "VALID_PASS_SAMPLE": "VALID 연구표본",
                "MATURED_PASS_4H": "4h 완료표본",
                "MATURED_PASS_24H": "24h 완료표본",
            },
            "note": (
                "124 natural opportunities ≠ 124 REAL BUY. "
                "PASS matured counts are strategy research samples only."
            ),
        },
        "samples": samples,
        "variant_semantics": {"E0": e0_sem, "E2": e2_sem},
        "paired_comparison": paired,
        "horizon_state": horizon_state,
        "growth": growth_e0,
        "outcomes": {"E0": e0_outcomes, "E2": e2_outcomes},
        "forward": fwd,
        "data_quality": dq,
        "RESEARCH_REVIEW_READY": review_ready,
        "RESEARCH_HEALTH": _research_health(
            valid_sample=e0_valid,
            pending_24h=pending_24h,
            quarantined=int(dq.get("QUARANTINED") or 0),
        ),
        "scheduler": upbit_scheduler_runtime(),
        "PROMOTION_SAMPLE_BASIS": "VALID_ONLY",
        # Exit Order Recovery Shadow Lab — research observability only (not READY blocker)
        "EXIT_ORDER_RECOVERY_SHADOW": _exit_order_recovery_shadow_obs(
            session, uba_id=uba
        ),
    }


def _exit_order_recovery_shadow_obs(
    session: Session, *, uba_id: int
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
            summarize_exit_order_recovery_lab,
        )

        summary = summarize_exit_order_recovery_lab(
            session, user_broker_account_id=uba_id
        )
        return {
            "EXIT_RECOVERY_SHADOW_ACTIVE": summary.get(
                "EXIT_RECOVERY_SHADOW_ACTIVE"
            ),
            "EXIT_RECOVERY_VARIANTS": summary.get("EXIT_RECOVERY_VARIANTS"),
            "EXIT_RECOVERY_VALID_PAIRED_N": summary.get("VALID_PAIRED_N_MAX"),
            "READINESS": summary.get("READINESS"),
            "FORWARD_START_AT": summary.get("FORWARD_START_AT"),
            "REAL_POLICY_CHANGED": False,
            "SHADOW_ONLY": True,
            "blocks_auto_ready": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "EXIT_RECOVERY_SHADOW_ACTIVE": False,
            "error": type(exc).__name__,
            "blocks_auto_ready": False,
            "REAL_TRADING_BLOCKED": False,
        }


def build_kiwoom_research_status(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    uba = int(user_broker_account_id)
    fwd = kiwoom_forward_status(session, uba_id=uba)
    growth = _growth_counts(
        session,
        table="kiwoom_entry_signal_shadow",
        uba_id=uba,
        id_column="research_opportunity_id",
        variant=VARIANT_K0,
    )
    outcomes = _horizon_metrics(
        session,
        table="kiwoom_entry_signal_shadow",
        uba_id=uba,
        variant=VARIANT_K0,
    )
    try:
        from stock_platform.trading.autotrading_data_trust import shadow_quality_counts

        dq = shadow_quality_counts(
            session, uba_id=uba, table="kiwoom_entry_signal_shadow"
        )
    except Exception as exc:  # noqa: BLE001
        dq = {"QUARANTINED": 0, "error": type(exc).__name__}

    valid = int(fwd.get("VALID_SAMPLE_COUNT") or 0)
    pending_24h = outcomes.get("24H", {}).get("PENDING_N", 0)

    return {
        "market": "KIWOOM",
        "KIWOOM_SAMPLE_IDENTITY": KIWOOM_SAMPLE_IDENTITY,
        "SHADOW_IMPLEMENTED": True,
        "KIWOOM_VARIANT_DEFERRED": True,
        "VARIANTS": [VARIANT_K0],
        "K0_SAMPLE": int(fwd.get("FORWARD_SAMPLE_COUNT") or 0),
        "K0_VALID_SAMPLE": valid,
        "growth": growth,
        "outcomes": outcomes,
        "KIWOOM_24H_SEMANTICS": KIWOOM_24H_SEMANTICS,
        "forward": fwd,
        "data_quality": dq,
        "RESEARCH_HEALTH": _research_health(
            valid_sample=valid,
            pending_24h=pending_24h,
            quarantined=int(dq.get("QUARANTINED") or 0),
        ),
        "scheduler": kiwoom_scheduler_runtime(),
        "research_only": True,
        "REAL_POLICY_PROMOTION": False,
    }


def build_cross_market_research_status(
    session: Session,
    *,
    upbit_uba_id: int = 1380,
    kiwoom_uba_id: int | None = None,
) -> dict[str, Any]:
    """Unified admin research status — trading path와 단방향 분리."""

    upbit = build_upbit_research_status(session, user_broker_account_id=upbit_uba_id)
    kiwoom: dict[str, Any] | None = None
    if kiwoom_uba_id is not None and int(kiwoom_uba_id) > 0:
        kiwoom = build_kiwoom_research_status(
            session, user_broker_account_id=int(kiwoom_uba_id)
        )

    return {
        "schema": "cross_market_shadow_research_v1",
        "research_only": True,
        "RESEARCH_CAN_AFFECT_REAL_ORDER": False,
        "REAL_POLICY_PROMOTION": False,
        "UPBIT": upbit,
        "KIWOOM": kiwoom,
        "change_history_tag": "CROSS_MARKET_SHADOW_RESEARCH_OUTCOME_OBSERVABILITY",
    }


def build_cross_market_research_status_for_daily_report(
    session: Session,
    *,
    upbit_uba_id: int = 1380,
    kiwoom_uba_id: int | None = None,
) -> dict[str, Any]:
    """일일보고용 research slim projection.

    Admin research SoT(전체 horizon/outcomes)는 변경하지 않는다.
    Daily Report UI가 쓰는 sample count + NATURAL_OPPORTUNITY_POOL만 조회.
    """

    uba = int(upbit_uba_id)
    samples = _sample_counts_upbit(session, uba_id=uba)
    e0_unique = int((samples.get(VARIANT_E0) or {}).get("UNIQUE_SAMPLE") or 0)
    upbit = {
        "market": "UPBIT",
        "research_only": True,
        "REAL_POLICY_PROMOTION": False,
        "NATURAL_OPPORTUNITY_POOL": e0_unique,
        "samples": samples,
        "projection": "daily_report_slim_v1",
    }

    kiwoom: dict[str, Any] | None = None
    if kiwoom_uba_id is not None and int(kiwoom_uba_id) > 0:
        fwd = kiwoom_forward_status(session, uba_id=int(kiwoom_uba_id))
        k0_valid = int(fwd.get("VALID_SAMPLE_COUNT") or 0)
        k0_total = int(fwd.get("FORWARD_SAMPLE_COUNT") or 0)
        kiwoom = {
            "market": "KIWOOM",
            "research_only": True,
            "REAL_POLICY_PROMOTION": False,
            "K0_VALID_SAMPLE": k0_valid,
            "K0_SAMPLE": k0_total,
            "samples": {
                VARIANT_K0: {
                    "UNIQUE_SAMPLE": k0_total,
                    "VALID_SAMPLE": k0_valid,
                }
            },
            "projection": "daily_report_slim_v1",
        }

    return {
        "schema": "cross_market_shadow_research_daily_report_v1",
        "research_only": True,
        "RESEARCH_CAN_AFFECT_REAL_ORDER": False,
        "REAL_POLICY_PROMOTION": False,
        "UPBIT": upbit,
        "KIWOOM": kiwoom,
        "projection": "daily_report_slim_v1",
        "change_history_tag": "DAILY_REPORT_RESEARCH_SAMPLE_PROJECTION",
    }
