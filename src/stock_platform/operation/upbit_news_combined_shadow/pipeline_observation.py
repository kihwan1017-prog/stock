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


def observation_bundle(session: Session) -> dict[str, Any]:
    return {
        "env": pipeline_env_snapshot(),
        "schedulers": pipeline_scheduler_snapshot(),
        "availability": diagnose_news_availability(session),
        "milestone": compute_sample_milestone(session),
        "lags": measure_pipeline_lags(session),
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
                "(limit=50 recent); no Scanner architecture change"
            ),
        },
        "llm_calls_policy": "N4 only when enabled; N5/N6 = 0",
        "apply_to_scanner": False,
    }
