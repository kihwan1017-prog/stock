"""Upbit research data collection status — READ-ONLY aggregate SoT.

CLEAN Forward / Market·Asset Context / News / LLM / Entry experiment.
REAL 정책·주문과 무관. UBA id는 표시용(연구 데이터는 플랫폼 공통 shadow).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    TARGET_CLEAN_MIN,
    TARGET_CLEAN_RECOMMENDED,
    assign_clean_forward_obs,
    partition_forward_rows,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    sample_gate,
    summarize_entry_quality_experiment_from_shadows,
)

KST = ZoneInfo("Asia/Seoul")

# Freshness thresholds
STALE_MARKET_MINUTES = 30
STALE_ASSET_MINUTES = 30
STALE_NEWS_HOURS = 24
STALE_LLM_HOURS = 24
# CLEAN unchanged is WAITING not ERROR
CLEAN_WAITING_HOURS = 6


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_kst(dt: Any) -> str | None:
    u = _as_utc(dt)
    if u is None:
        return None
    return u.astimezone(KST).isoformat()


def _age_seconds(dt: Any) -> float | None:
    u = _as_utc(dt)
    if u is None:
        return None
    return max(0.0, (_utc_now() - u).total_seconds())


def _status_from_age(
    age_sec: float | None,
    *,
    stale_after_sec: float,
    has_error: bool = False,
) -> str:
    if has_error:
        return "ERROR"
    if age_sec is None:
        return "WAITING"
    if age_sec > stale_after_sec:
        return "STALE"
    return "OK"


def _sample_stage_ko(gate: str) -> dict[str, str]:
    mapping = {
        "COLLECTION_ONLY": (
            "수집 단계",
            "CLEAN 표본이 아직 적어 REAL 전략 변경 근거로 사용하지 않습니다.",
        ),
        "DIAGNOSTIC_ONLY": (
            "중간 진단 가능",
            "진단용으로만 참고합니다. REAL 승격 근거로는 부족합니다.",
        ),
        "PRIMARY_REVIEW": (
            "1차 정책 검토 가능",
            "1차 검토는 가능하나 권장 표본(1000)에는 미달입니다.",
        ),
        "RECOMMENDED_REVIEW": (
            "권장 검토 표본 확보",
            "권장 표본에 도달했습니다. 자동 승격은 하지 않습니다.",
        ),
    }
    label, desc = mapping.get(gate, ("알 수 없음", ""))
    return {"sample_stage": gate, "sample_stage_ko": label, "sample_stage_desc_ko": desc}


def _overall_ko(status: str) -> str:
    return {
        "COLLECTING": "수집 중",
        "WAITING": "신규 후보 대기",
        "PARTIAL": "일부 수집 지연",
        "STALE": "수집 지연",
        "ERROR": "수집 중단 확인 필요",
    }.get(status, status)


def build_research_collection_status(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """단일 READ aggregate — fan-out 없이 한 응답."""

    now = _utc_now()
    today_start_kst = datetime.now(KST).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_start = today_start_kst.astimezone(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    # ── CLEAN / Legacy / Backfill ──────────────────────────────────────────
    completed = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )
    partition = partition_forward_rows(completed)
    clean_obs = assign_clean_forward_obs(completed)
    clean_n = len(clean_obs)

    def _in_window(dt: Any, start: datetime) -> bool:
        u = _as_utc(dt)
        return u is not None and u >= start

    today_new = sum(1 for o in clean_obs if _in_window(o.detected_at, today_start))
    hour_new = sum(1 for o in clean_obs if _in_window(o.detected_at, hour_ago))
    day_new = sum(1 for o in clean_obs if _in_window(o.detected_at, day_ago))
    last_clean = max(
        (_as_utc(o.detected_at) for o in clean_obs if o.detected_at),
        default=None,
    )
    gate = sample_gate(clean_n)
    stage = _sample_stage_ko(gate)

    clean_age = _age_seconds(last_clean)
    clean_status = "WAITING"
    if clean_n > 0 and clean_age is not None:
        if clean_age > CLEAN_WAITING_HOURS * 3600:
            clean_status = "WAITING"  # no new opportunity — not ERROR
        else:
            clean_status = "OK"
    elif clean_n == 0:
        clean_status = "WAITING"

    clean_block = {
        "count": clean_n,
        "target_primary": TARGET_CLEAN_MIN,
        "target_recommended": TARGET_CLEAN_RECOMMENDED,
        "progress_primary_pct": round(clean_n / TARGET_CLEAN_MIN * 100, 2)
        if TARGET_CLEAN_MIN
        else 0,
        "progress_recommended_pct": round(
            clean_n / TARGET_CLEAN_RECOMMENDED * 100, 2
        )
        if TARGET_CLEAN_RECOMMENDED
        else 0,
        "today_new": today_new,
        "hour_new": hour_new,
        "day_new": day_new,
        "last_new_at": _iso_kst(last_clean),
        "last_new_age_seconds": clean_age,
        "status": clean_status,
        **stage,
    }

    reference = {
        # 실측 cohort 건수 (상수 LEGACY_FORWARD_COUNT와 혼동 금지)
        "legacy_count": len(partition.get("legacy_rows") or []),
        "backfill_count": int(partition.get("new_stamped_count") or 0),
        "legacy_historical_label": int(partition.get("legacy_total") or 0),
        "label_ko": "참고용 · 승격 판단 제외",
        "note": "CLEAN과 합산하지 않음",
    }

    # ── Market / Asset context ─────────────────────────────────────────────
    market = _snapshot_table_stats(
        session,
        table="operation.upbit_market_context_snapshot",
        today_start=today_start,
        stale_after_sec=STALE_MARKET_MINUTES * 60,
    )
    asset = _asset_table_stats(
        session,
        today_start=today_start,
        stale_after_sec=STALE_ASSET_MINUTES * 60,
    )

    # ── News ───────────────────────────────────────────────────────────────
    news = _news_stats(session, day_ago=day_ago)

    # ── LLM ────────────────────────────────────────────────────────────────
    llm = _llm_stats(session, today_start=today_start)

    # ── Experiment ─────────────────────────────────────────────────────────
    exp_raw = summarize_entry_quality_experiment_from_shadows(completed)
    best = exp_raw.get("BEST_FILTER_CURRENTLY") if isinstance(exp_raw, dict) else None
    experiment = {
        "status": exp_raw.get("SAMPLE_GATE") or gate,
        "status_ko": stage["sample_stage_ko"],
        "best_candidate": (best or {}).get("code") if isinstance(best, dict) else None,
        "best_candidate_label_ko": (
            (best or {}).get("name_ko") if isinstance(best, dict) else None
        ),
        "best_net_filter_benefit": (
            (best or {}).get("net_filter_benefit") if isinstance(best, dict) else None
        ),
        "sample_warning": clean_n < 100,
        "sample_warning_ko": "표본 부족 · 연구용" if clean_n < 100 else None,
        "provisional_badge": clean_n < 100,
        "baseline_net": (exp_raw.get("BASELINE") or {}).get("net")
        if isinstance(exp_raw, dict)
        else None,
        "baseline_pf": (exp_raw.get("BASELINE") or {}).get("PF")
        if isinstance(exp_raw, dict)
        else None,
        "baseline_early_dump_rate": (exp_raw.get("BASELINE") or {}).get(
            "early_dump_rate"
        )
        if isinstance(exp_raw, dict)
        else None,
        "REAL_PROMOTION_RECOMMENDED": "NO",
    }

    # ── Overall ────────────────────────────────────────────────────────────
    statuses = [
        market.get("status"),
        asset.get("status"),
        news.get("status"),
        llm.get("status"),
    ]
    if "ERROR" in statuses:
        overall = "ERROR"
    elif statuses.count("STALE") >= 2:
        overall = "STALE"
    elif "STALE" in statuses:
        overall = "PARTIAL"
    elif clean_status == "WAITING" and clean_n > 0 and (hour_new == 0):
        overall = "WAITING"
    else:
        overall = "COLLECTING"

    last_collected_candidates = [
        market.get("last_collected_at"),
        asset.get("last_collected_at"),
        news.get("last_collected_at"),
        llm.get("last_analysis_at"),
        clean_block.get("last_new_at"),
    ]
    last_collected = max(
        (x for x in last_collected_candidates if x),
        default=None,
    )

    return {
        "schema": "upbit_research_collection_status_v1",
        "as_of": _iso_kst(now),
        "user_broker_account_id": user_broker_account_id,
        "research_only": True,
        "live_order": False,
        "overall_status": overall,
        "overall_status_ko": _overall_ko(overall),
        "last_collected_at": last_collected,
        "clean_forward": clean_block,
        "reference": reference,
        "market_context": market,
        "asset_context": asset,
        "news": news,
        "llm": llm,
        "experiment": experiment,
        "mutations": {
            "REAL_ORDER_MUTATION": 0,
            "LIVE_ARM_MUTATION": 0,
            "ENTRY_POLICY_MUTATION": 0,
            "EXIT_POLICY_MUTATION": 0,
            "RISK_MUTATION": 0,
            "SLOT_POLICY_MUTATION": 0,
            "UBA1381_MUTATION": 0,
        },
        "labels_ko": {
            "clean_forward": "정상 신규 검증",
            "target_500": "1차 검토 최소 표본",
            "target_1000": "권장 검토 표본",
            "legacy": "이전 연구 데이터",
            "backfill": "보완 데이터",
            "market": "시장 Context",
            "asset": "종목 Context",
            "news": "뉴스·공지",
            "llm": "LLM 분석",
        },
        "tooltips_ko": {
            "clean_forward": "가격 소스 수정 이후 새로 수집한 검증 가능한 연구 데이터입니다.",
            "target_500": "전략 후보를 1차 검토하기 위한 최소 표본 목표입니다.",
            "target_1000": "보다 안정적인 판단을 위한 권장 표본 목표입니다.",
            "legacy": "과거 가격 품질 문제가 있어 참고용으로만 사용합니다.",
            "llm": "시장·뉴스·종목 정보를 보조 분석하며 REAL 주문을 직접 생성하지 않습니다.",
            "waiting": "Scanner 후보가 잠시 없어도 정상일 수 있습니다. ERROR가 아닙니다.",
        },
    }


def _snapshot_table_stats(
    session: Session,
    *,
    table: str,
    today_start: datetime,
    stale_after_sec: float,
) -> dict[str, Any]:
    try:
        rows = int(
            session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        )
        today = int(
            session.execute(
                text(
                    f"""
                    SELECT COUNT(*) FROM {table}
                    WHERE observed_at >= :t0
                    """
                ),
                {"t0": today_start},
            ).scalar()
            or 0
        )
        last = session.execute(
            text(f"SELECT MAX(observed_at) FROM {table}")
        ).scalar()
        age = _age_seconds(last)
        status = _status_from_age(age, stale_after_sec=stale_after_sec)
        if rows == 0:
            status = "WAITING"
        return {
            "status": status,
            "status_ko": {
                "OK": "정상",
                "STALE": "수집 지연",
                "WAITING": "대기",
                "ERROR": "오류",
            }.get(status, status),
            "rows": rows,
            "today_new": today,
            "last_collected_at": _iso_kst(last),
            "age_seconds": age,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {
            "status": "ERROR",
            "status_ko": "오류",
            "rows": 0,
            "today_new": 0,
            "last_collected_at": None,
            "error": type(exc).__name__,
            "detail": str(exc)[:120],
        }


def _asset_table_stats(
    session: Session,
    *,
    today_start: datetime,
    stale_after_sec: float,
) -> dict[str, Any]:
    table = "operation.upbit_asset_context_snapshot"
    base = _snapshot_table_stats(
        session,
        table=table,
        today_start=today_start,
        stale_after_sec=stale_after_sec,
    )
    if base.get("status") == "ERROR":
        return {**base, "symbols": 0}
    try:
        symbols = int(
            session.execute(
                text(f"SELECT COUNT(DISTINCT symbol) FROM {table}")
            ).scalar()
            or 0
        )
        base["symbols"] = symbols
        return base
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {**base, "symbols": 0, "symbols_error": type(exc).__name__}


def _news_stats(session: Session, *, day_ago: datetime) -> dict[str, Any]:
    try:
        from stock_platform.news.models import NewsArticle

        recent = int(
            session.scalar(
                select(func.count())
                .select_from(NewsArticle)
                .where(NewsArticle.published_at >= day_ago)
            )
            or 0
        )
        last = session.scalar(select(func.max(NewsArticle.published_at)))
        # upbit notice heuristic: source_code / exchange
        notice = 0
        try:
            notice = int(
                session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM news.news_article
                        WHERE published_at >= :t0
                          AND (
                            COALESCE(source_code, '') ILIKE '%UPBIT%'
                            OR COALESCE(exchange_code, '') ILIKE '%UPBIT%'
                          )
                        """
                    ),
                    {"t0": day_ago},
                ).scalar()
                or 0
            )
        except Exception:  # noqa: BLE001
            session.rollback()
            notice = None  # type: ignore[assignment]

        linked = None
        try:
            linked = int(
                session.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT article_id)
                        FROM news.news_article_symbol
                        WHERE created_at >= :t0
                        """
                    ),
                    {"t0": day_ago},
                ).scalar()
                or 0
            )
        except Exception:  # noqa: BLE001
            session.rollback()
            try:
                linked = int(
                    session.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM news.news_article_symbol
                            """
                        )
                    ).scalar()
                    or 0
                )
            except Exception:  # noqa: BLE001
                session.rollback()
                linked = None

        age = _age_seconds(last)
        status = _status_from_age(age, stale_after_sec=STALE_NEWS_HOURS * 3600)
        if recent == 0 and last is None:
            status = "WAITING"
        return {
            "status": status,
            "status_ko": {
                "OK": "정상",
                "STALE": "수집 지연",
                "WAITING": "대기",
                "ERROR": "오류",
            }.get(status, status),
            "recent_count": recent,
            "upbit_notice_count": notice,
            "candidate_linked_count": linked,
            "last_collected_at": _iso_kst(last),
            "age_seconds": age,
            "dedupe": "headline+published_at pipeline",
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {
            "status": "WAITING",
            "status_ko": "대기",
            "recent_count": None,
            "last_collected_at": None,
            "note": "news table unavailable",
            "error": type(exc).__name__,
        }


def _llm_stats(session: Session, *, today_start: datetime) -> dict[str, Any]:
    table = "operation.upbit_llm_context_analysis"
    try:
        total = int(
            session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        )
        today = int(
            session.execute(
                text(
                    f"""
                    SELECT COUNT(*) FROM {table}
                    WHERE created_at >= :t0
                    """
                ),
                {"t0": today_start},
            ).scalar()
            or 0
        )
        last = session.execute(
            text(f"SELECT MAX(created_at) FROM {table}")
        ).scalar()

        def _rec_count(rec: str) -> int:
            return int(
                session.execute(
                    text(
                        f"""
                        SELECT COUNT(*) FROM {table}
                        WHERE created_at >= :t0 AND recommendation = :r
                        """
                    ),
                    {"t0": today_start, "r": rec},
                ).scalar()
                or 0
            )

        allow = _rec_count("ALLOW") if today else 0
        hold = _rec_count("HOLD") if today else 0
        reduce = _rec_count("REDUCE") if today else 0
        failed = int(
            session.execute(
                text(
                    f"""
                    SELECT COUNT(*) FROM {table}
                    WHERE created_at >= :t0
                      AND (
                        quality ILIKE '%FAIL%'
                        OR quality ILIKE '%ERROR%'
                        OR (output_json->>'context_unavailable') = 'true'
                      )
                    """
                ),
                {"t0": today_start},
            ).scalar()
            or 0
        )
        age = _age_seconds(last)
        status = _status_from_age(age, stale_after_sec=STALE_LLM_HOURS * 3600)
        if total == 0:
            status = "WAITING"
        return {
            "status": status,
            "status_ko": {
                "OK": "정상",
                "STALE": "수집 지연",
                "WAITING": "대기",
                "ERROR": "오류",
            }.get(status, status),
            "total": total,
            "today_count": today,
            "allow": allow,
            "hold": hold,
            "reduce": reduce,
            "failed": failed,
            "last_analysis_at": _iso_kst(last),
            "age_seconds": age,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {
            "status": "WAITING",
            "status_ko": "대기",
            "total": 0,
            "today_count": 0,
            "allow": 0,
            "hold": 0,
            "reduce": 0,
            "failed": 0,
            "last_analysis_at": None,
            "error": type(exc).__name__,
            "detail": str(exc)[:120],
        }
