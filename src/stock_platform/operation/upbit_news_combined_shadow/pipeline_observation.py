"""STEP N8 — News pipeline continuous observation helpers (READ diagnostics)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.news.news_ai_analysis_models import NewsAIAnalysis
from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
    compute_sample_milestone,
    diagnose_news_availability,
    list_matched_details,
)
from stock_platform.operation.upbit_news_combined_shadow.entities import (
    UpbitNewsCombinedShadowEntity,
)


def _avg(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def _med(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(float(median(vals)), 6)


def _lag_seconds(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds()


def pipeline_env_snapshot() -> dict[str, Any]:
    s = get_settings()
    return {
        "UPBIT_NOTICE_COLLECTION_ENABLED": bool(
            s.upbit_notice_collection_enabled
        ),
        "CRYPTO_NEWS_COLLECTION_ENABLED": bool(
            s.crypto_news_collection_enabled
        ),
        "UPBIT_NEWS_AI_ANALYSIS_ENABLED": bool(
            s.upbit_news_ai_analysis_enabled
        ),
        "UPBIT_NEWS_SIGNAL_ENABLED": bool(s.upbit_news_signal_enabled),
        "UPBIT_NEWS_COMBINED_SHADOW_ENABLED": bool(
            s.upbit_news_combined_shadow_enabled
        ),
        "intervals": {
            "notice_s": float(s.upbit_notice_collection_interval_seconds),
            "crypto_s": float(s.crypto_news_collection_interval_seconds),
            "n4_s": float(s.upbit_news_ai_analysis_interval_seconds),
            "n5_s": float(s.upbit_news_signal_interval_seconds),
            "n6_s": float(s.upbit_news_combined_shadow_interval_seconds),
        },
        "naver_credentials_configured": bool(
            (s.naver_client_id or "").strip()
            and (s.naver_client_secret or "").strip()
        ),
        "n4_batch_size": int(s.upbit_news_ai_analysis_batch_size),
        "control_mutation_forbidden": True,
        "apply_to_scanner": False,
    }


def pipeline_scheduler_snapshot() -> dict[str, Any]:
    from stock_platform.news.collector_scheduler import (
        upbit_news_notice_collector_scheduler,
    )
    from stock_platform.news.news_ai_analysis_scheduler import (
        upbit_news_ai_analysis_scheduler,
    )
    from stock_platform.news.news_signal_scheduler import (
        upbit_news_signal_scheduler,
    )
    from stock_platform.operation.upbit_news_combined_shadow.scheduler import (
        upbit_news_combined_shadow_scheduler,
    )

    return {
        "collector": upbit_news_notice_collector_scheduler.status(),
        "n4": upbit_news_ai_analysis_scheduler.status(),
        "n5": upbit_news_signal_scheduler.status(),
        "n6_experiment": upbit_news_combined_shadow_scheduler.status(),
        "failure_isolation": True,
        "scanner_hook": False,
    }


def measure_pipeline_lags(
    session: Session, *, since: datetime | None = None
) -> dict[str, Any]:
    """publication→collection, collection→N4, N4→N5, signal→Scanner T0 lags."""

    now = datetime.now(timezone.utc)
    since = since or (now - timedelta(hours=24))

    pub_collect: list[float] = []
    collect_n4: list[float] = []
    n4_n5: list[float] = []
    signal_t0: list[float] = []

    rows = session.execute(
        text(
            """
            SELECT
              a.published_at,
              a.created_at AS collected_at,
              n4.analyzed_at,
              n4.created_at AS n4_created_at,
              ns.signal_at,
              ns.created_at AS signal_created_at
            FROM news.news_article a
            LEFT JOIN news.news_ai_analysis n4
              ON n4.article_id = a.article_id AND n4.status = 'COMPLETED'
            LEFT JOIN news.news_signal ns
              ON ns.article_id = a.article_id
            WHERE a.created_at >= :since
              AND a.source_code IN ('UPBIT_NOTICE', 'CRYPTO_NEWS')
            ORDER BY a.created_at DESC
            LIMIT 200
            """
        ),
        {"since": since},
    ).mappings().all()

    for r in rows:
        lag = _lag_seconds(r["published_at"], r["collected_at"])
        if lag is not None:
            pub_collect.append(lag)
        n4_at = r["analyzed_at"] or r["n4_created_at"]
        lag2 = _lag_seconds(r["collected_at"], n4_at)
        if lag2 is not None:
            collect_n4.append(lag2)
        lag3 = _lag_seconds(n4_at, r["signal_at"] or r["signal_created_at"])
        if lag3 is not None:
            n4_n5.append(lag3)

    # matched rows: signal_at → candidate T0
    matched = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity).where(
                UpbitNewsCombinedShadowEntity.news_context_status
                == "NEWS_MATCHED",
                UpbitNewsCombinedShadowEntity.created_at >= since,
            )
        )
    )
    for m in matched:
        snap = m.news_snapshot if isinstance(m.news_snapshot, dict) else {}
        influence = snap.get("influence_signals") or []
        for item in influence:
            if not isinstance(item, dict):
                continue
            sig_at = item.get("signal_at")
            if not sig_at or m.candidate_detected_at is None:
                continue
            try:
                sig_dt = datetime.fromisoformat(str(sig_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            lag4 = _lag_seconds(sig_dt, m.candidate_detected_at)
            if lag4 is not None:
                signal_t0.append(lag4)

    def _pack(vals: list[float]) -> dict[str, Any]:
        return {
            "n": len(vals),
            "avg_s": _avg(vals),
            "median_s": _med(vals),
            "max_s": round(max(vals), 3) if vals else None,
            "min_s": round(min(vals), 3) if vals else None,
        }

    return {
        "window_since": since.isoformat(),
        "publication_to_collection": _pack(pub_collect),
        "collection_to_n4": _pack(collect_n4),
        "n4_to_n5": _pack(n4_n5),
        "signal_to_scanner_t0": _pack(signal_t0),
    }


def future_signal_at_stats(
    session: Session, *, since: datetime | None = None
) -> dict[str, Any]:
    """N8 이후 EXCLUDED FUTURE_SIGNAL_AT 비율 관찰 (조건 완화 금지)."""

    now = datetime.now(timezone.utc)
    since = since or (now - timedelta(hours=24))
    rows = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity).where(
                UpbitNewsCombinedShadowEntity.created_at >= since
            )
        )
    )
    future_n = 0
    excluded_n = 0
    for row in rows:
        if row.news_context_status != "EXCLUDED_ONLY":
            continue
        excluded_n += 1
        snap = row.news_snapshot if isinstance(row.news_snapshot, dict) else {}
        for item in snap.get("excluded_signals") or []:
            if (
                isinstance(item, dict)
                and str(item.get("exclude_reason") or "") == "FUTURE_SIGNAL_AT"
            ):
                future_n += 1
                break
    return {
        "window_since": since.isoformat(),
        "experiment_rows": len(rows),
        "excluded_only": excluded_n,
        "future_signal_at_excluded": future_n,
        "future_signal_at_rate": (
            round(future_n / max(1, excluded_n), 4) if excluded_n else 0.0
        ),
        "policy": "look_ahead_not_relaxed",
    }


def n4_latency_snapshot(session: Session) -> dict[str, Any]:
    """N4 elapsed_ms / analyzed_at lag 관찰."""

    rows = list(
        session.scalars(
            select(NewsAIAnalysis)
            .where(NewsAIAnalysis.status == "COMPLETED")
            .order_by(NewsAIAnalysis.created_at.desc())
            .limit(50)
        )
    )
    lags: list[float] = []
    for r in rows:
        if r.elapsed_ms is not None:
            try:
                lags.append(float(r.elapsed_ms) / 1000.0)
                continue
            except (TypeError, ValueError):
                pass
        lag = _lag_seconds(r.created_at, r.analyzed_at)
        if lag is not None and lag >= 0:
            lags.append(lag)
    return {
        "completed_sample_n": len(rows),
        "latency_s": {
            "n": len(lags),
            "avg": _avg(lags),
            "median": _med(lags),
            "max": round(max(lags), 3) if lags else None,
        },
        "concurrency_policy": 1,
        "batch_size_max": 5,
    }


def matched_provenance(
    session: Session, *, limit: int = 10
) -> list[dict[str, Any]]:
    """NEWS_MATCHED 시간 순서 provenance (look-ahead 증명용)."""

    details = list_matched_details(session, limit=limit)
    out: list[dict[str, Any]] = []
    for d in details:
        exp_id = d.get("experiment_id")
        row = session.get(UpbitNewsCombinedShadowEntity, exp_id) if exp_id else None
        snap = (
            row.news_snapshot
            if row is not None and isinstance(row.news_snapshot, dict)
            else {}
        )
        influence = (snap.get("influence_signals") or [None])[0] or {}
        published = influence.get("published_at")
        signal_at = influence.get("signal_at")
        collected = influence.get("collected_at") or influence.get("article_created_at")
        t0 = d.get("t0")
        analyzed = influence.get("analyzed_at")
        created = (
            row.created_at.isoformat() if row is not None and row.created_at else None
        )

        def _parse(v: Any) -> datetime | None:
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except ValueError:
                return None

        pub_dt = _parse(published)
        col_dt = _parse(collected)
        sig_dt = _parse(signal_at)
        t0_dt = _parse(t0)
        gates = {
            "published_le_t0": (
                pub_dt is not None
                and t0_dt is not None
                and pub_dt <= t0_dt
            ),
            "collected_le_t0": (
                col_dt is None
                or (t0_dt is not None and col_dt <= t0_dt)
            ),
            "signal_le_t0": (
                sig_dt is not None
                and t0_dt is not None
                and sig_dt <= t0_dt
            ),
        }
        out.append(
            {
                **d,
                "provenance": {
                    "published_at": published,
                    "collected_at": collected,
                    "n4_analyzed_at": analyzed,
                    "n5_signal_at": signal_at,
                    "scanner_t0": t0,
                    "experiment_created_at": created,
                    "gates": gates,
                    "min_gate_ok": all(
                        [
                            gates["published_le_t0"],
                            gates["collected_le_t0"],
                            gates["signal_le_t0"],
                        ]
                    ),
                },
            }
        )
    return out


def diagnose_latency_alignment(
    session: Session,
    *,
    realtime_since: datetime | None = None,
) -> dict[str, Any]:
    """Historical backfill vs N8+ realtime latency 분리 + backlog/capacity."""

    now = datetime.now(timezone.utc)
    # N8 활성화 근사 — 인자 없으면 24h (호출측에서 n8 snapshot 전달 권장)
    since = realtime_since or (now - timedelta(hours=24))

    rows = session.execute(
        text(
            """
            SELECT
              a.article_id,
              a.published_at,
              a.created_at AS collected_at,
              a.raw_data->'symbol_mapping'->>'updated_at' AS mapped_at_txt,
              n4.created_at AS n4_created_at,
              n4.analyzed_at,
              n4.elapsed_ms,
              ns.signal_at,
              ns.created_at AS signal_created_at,
              CASE
                WHEN a.created_at >= :since THEN 'realtime'
                ELSE 'historical'
              END AS cohort
            FROM news.news_article a
            LEFT JOIN news.news_ai_analysis n4
              ON n4.article_id = a.article_id AND n4.status = 'COMPLETED'
            LEFT JOIN LATERAL (
              SELECT signal_at, created_at
              FROM news.news_signal ns0
              WHERE ns0.article_id = a.article_id
              ORDER BY ns0.created_at DESC
              LIMIT 1
            ) ns ON true
            WHERE a.source_code IN ('UPBIT_NOTICE', 'CRYPTO_NEWS')
              AND n4.analysis_id IS NOT NULL
            ORDER BY a.created_at DESC
            LIMIT 200
            """
        ),
        {"since": since},
    ).mappings().all()

    def _parse_map(txt: Any) -> datetime | None:
        if not txt:
            return None
        try:
            return datetime.fromisoformat(str(txt).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _pack(items: list[dict[str, Any]]) -> dict[str, Any]:
        pub_c: list[float] = []
        c_map: list[float] = []
        map_n4: list[float] = []
        n4_ex: list[float] = []
        n4_n5: list[float] = []
        c_n5: list[float] = []
        pub_c = [
            v
            for r in items
            if (v := _lag_seconds(r["published_at"], r["collected_at"])) is not None
        ]
        for r in items:
            mapped = _parse_map(r["mapped_at_txt"])
            if (v := _lag_seconds(r["collected_at"], mapped)) is not None:
                c_map.append(v)
            base = mapped or r["collected_at"]
            if (v := _lag_seconds(base, r["n4_created_at"])) is not None:
                map_n4.append(v)
            if r["elapsed_ms"] is not None:
                try:
                    n4_ex.append(float(r["elapsed_ms"]) / 1000.0)
                except (TypeError, ValueError):
                    pass
            elif (v := _lag_seconds(r["n4_created_at"], r["analyzed_at"])) is not None:
                n4_ex.append(v)
            n5_at = r["signal_at"] or r["signal_created_at"]
            if (
                v := _lag_seconds(r["analyzed_at"] or r["n4_created_at"], n5_at)
            ) is not None:
                n4_n5.append(v)
            if (v := _lag_seconds(r["collected_at"], n5_at)) is not None:
                c_n5.append(v)

        def st(vals: list[float]) -> dict[str, Any]:
            if not vals:
                return {"n": 0}
            return {
                "n": len(vals),
                "avg_s": _avg(vals),
                "median_s": _med(vals),
                "max_s": round(max(vals), 3),
                "min_s": round(min(vals), 3),
            }

        return {
            "count": len(items),
            "publication_to_collection": st(pub_c),
            "collection_to_mapping": st(c_map),
            "mapping_to_n4_start": st(map_n4),
            "n4_execution": st(n4_ex),
            "n4_to_n5": st(n4_n5),
            "collection_to_n5": st(c_n5),
        }

    hist = [dict(r) for r in rows if r["cohort"] == "historical"]
    rt = [dict(r) for r in rows if r["cohort"] == "realtime"]

    backlog = session.execute(
        text(
            """
            WITH trusted AS (
              SELECT DISTINCT a.article_id, a.created_at
              FROM news.news_article a
              CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(a.raw_data->'symbol_mapping'->'mappings', '[]'::jsonb)
              ) m
              WHERE m.value->>'quality_status' = 'TRUSTED'
            ),
            pending AS (
              SELECT t.article_id, t.created_at
              FROM trusted t
              LEFT JOIN news.news_ai_analysis n4 ON n4.article_id = t.article_id
              WHERE n4.analysis_id IS NULL
            )
            SELECT
              (SELECT COUNT(*) FROM trusted) AS trusted_n,
              (SELECT COUNT(*) FROM pending) AS pending_n,
              (SELECT COUNT(*) FROM news.news_ai_analysis WHERE status='COMPLETED') AS n4_ok,
              (SELECT COUNT(*) FROM news.news_ai_analysis WHERE status='FAILED') AS n4_fail,
              (SELECT COUNT(*) FROM news.news_ai_analysis WHERE status='SKIPPED') AS n4_skip,
              (SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) FROM pending)
                AS oldest_pending_age_s,
              (SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) FROM pending)
                AS newest_pending_age_s,
              (SELECT COUNT(*) FROM news.news_ai_analysis n4
                WHERE n4.status='COMPLETED'
                  AND NOT EXISTS (
                    SELECT 1 FROM news.news_signal ns
                    WHERE ns.article_id = n4.article_id
                  )
              ) AS n5_pending_completed_n4,
              (SELECT COUNT(*) FROM news.news_article
                WHERE created_at >= NOW() - INTERVAL '1 hour'
                  AND source_code IN ('UPBIT_NOTICE','CRYPTO_NEWS')
              ) AS articles_1h,
              (SELECT COUNT(*) FROM news.news_ai_analysis
                WHERE status='COMPLETED'
                  AND COALESCE(analyzed_at, created_at) >= NOW() - INTERVAL '1 hour'
              ) AS n4_ok_1h
            """
        )
    ).mappings().one()

    pending_n = int(backlog["pending_n"] or 0)
    articles_1h = int(backlog["articles_1h"] or 0)
    n4_capacity_hour = 4 * 5  # 900s interval × batch 5
    causes: list[str] = []
    if pending_n > 10:
        causes.append("BATCH_CAPACITY_BOTTLENECK")
    # N4 exec itself typically << scheduler wait → alignment
    hist_pack = _pack(hist)
    n4_to_n5_med = (hist_pack.get("n4_to_n5") or {}).get("median_s")
    if n4_to_n5_med is not None and float(n4_to_n5_med) > 120:
        causes.append("SCHEDULER_ALIGNMENT_BOTTLENECK")
    n4_ex_med = (hist_pack.get("n4_execution") or {}).get("median_s")
    if n4_ex_med is not None and float(n4_ex_med) > 120:
        causes.append("OLLAMA_LATENCY_BOTTLENECK")
    if not causes:
        causes.append("NO_BACKLOG")
    root = (
        "MIXED"
        if len(causes) >= 2
        else causes[0]
    )

    return {
        "realtime_since": since.isoformat(),
        "historical": hist_pack,
        "realtime": _pack(rt),
        "backlog": {
            "trusted_n": int(backlog["trusted_n"] or 0),
            "pending_n": pending_n,
            "n4_completed": int(backlog["n4_ok"] or 0),
            "n4_failed": int(backlog["n4_fail"] or 0),
            "n4_skipped": int(backlog["n4_skip"] or 0),
            "oldest_pending_age_s": (
                float(backlog["oldest_pending_age_s"])
                if backlog["oldest_pending_age_s"] is not None
                else None
            ),
            "newest_pending_age_s": (
                float(backlog["newest_pending_age_s"])
                if backlog["newest_pending_age_s"] is not None
                else None
            ),
            "n5_pending_completed_n4": int(
                backlog["n5_pending_completed_n4"] or 0
            ),
        },
        "capacity": {
            "incoming_articles_1h": articles_1h,
            "n4_completed_1h": int(backlog["n4_ok_1h"] or 0),
            "n4_theoretical_capacity_per_hour": n4_capacity_hour,
            "note": "interval 900s × batch 5; actual lower under Ollama/Scanner contention",
        },
        "root_cause": root,
        "root_cause_factors": causes,
        "chosen_fix": {
            "n4_to_n5_event_driven": True,
            "n5_periodic_recovery": True,
            "n4_fresh_unprocessed_priority": True,
            "n4_interval_changed": False,
            "n4_batch_increased": False,
            "look_ahead_relaxed": False,
        },
        "target": {
            "collection_to_n5_median_s": 900,
            "soft_max_s": 1200,
        },
    }


def observation_bundle(session: Session) -> dict[str, Any]:
    alignment = diagnose_latency_alignment(session)
    return {
        "env": pipeline_env_snapshot(),
        "schedulers": pipeline_scheduler_snapshot(),
        "availability": diagnose_news_availability(session),
        "milestone": compute_sample_milestone(session),
        "lags": measure_pipeline_lags(session),
        "latency_alignment": alignment,
        "future_signal_at": future_signal_at_stats(session),
        "n4_latency": n4_latency_snapshot(session),
        "matched_provenance": matched_provenance(session, limit=10),
        "top_n_history_reusable": False,
        "top_n_history_followup_candidate": (
            "Scanner Top-N Observation Snapshot (append-only) "
            "if NEWS accumulates but experiment coverage stays low"
        ),
        "telegram": {
            "per_article": False,
            "trading_recommendation": False,
            "allowed": [
                "pipeline_failure",
                "repeated_n4_failure",
                "PIPELINE_BACKLOG_HIGH",
                "milestone_NEWS_AB_REVIEW_READY",
            ],
            "wired": False,
            "note": "no Telegram notifier module for news track yet",
        },
        "n3_automation": {
            "dedicated_scheduler": False,
            "post_collect_glue": True,
            "note": (
                "N8: fail-isolated mapping after collector tick "
                "(limit=50 recent); Collector does not invoke Ollama"
            ),
        },
        "n9_latency_fix": alignment.get("chosen_fix"),
        "llm_calls_policy": "N4 only when enabled; N5/N6 = 0",
        "apply_to_scanner": False,
    }
