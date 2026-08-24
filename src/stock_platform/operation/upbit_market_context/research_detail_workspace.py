"""Upbit Research Detail Workspace — READ ONLY row queries.

SoT:
- CLEAN: clean_forward_research.assign_clean_forward_obs (collection-status와 동일)
- market/asset/llm: operation.* snapshot tables
- news: news.news_article
- experiments: entry_quality_early_dump_experiment

REAL/LIVE/정책 mutate·DB research row UPDATE 금지.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    COHORT_CLEAN_FORWARD,
    classify_forward_row,
    is_research_stamp_backfill,
    partition_forward_rows,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    ForwardObs,
    _as_utc,
    build_forward_obs,
    extract_forward_features,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    TARGET_CLEAN_MIN,
    outcome_label,
    sample_gate,
    summarize_entry_quality_experiment_from_shadows,
)
from stock_platform.operation.upbit_market_context.as_of import (
    assert_no_lookahead,
    select_latest_as_of,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitAssetContextSnapshotEntity,
    UpbitLlmContextAnalysisEntity,
    UpbitMarketContextSnapshotEntity,
)
from stock_platform.operation.upbit_market_context.snapshot_service import (
    MarketContextSnapshotService,
)

KST = ZoneInfo("Asia/Seoul")

# 기본 페이지 크기 — 전체 dump 금지
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _iso_kst(dt: datetime | None) -> str | None:
    u = _as_utc(dt)
    if u is None:
        return None
    return u.astimezone(KST).isoformat()


def _dec(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _snap(row: Any) -> dict[str, Any]:
    s = getattr(row, "entry_snapshot", None)
    return s if isinstance(s, dict) else {}


def _detail(row: Any) -> dict[str, Any]:
    d = getattr(row, "evaluation_detail", None)
    return d if isinstance(d, dict) else {}


def _provenance(row: Any) -> dict[str, Any] | None:
    p = _snap(row).get("entry_price_provenance")
    return p if isinstance(p, dict) else None


def _paginate(
    items: Sequence[Any],
    *,
    page: int,
    page_size: int,
) -> tuple[list[Any], int, int, int]:
    total = len(items)
    p = max(1, int(page or DEFAULT_PAGE))
    ps = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    start = (p - 1) * ps
    return list(items[start : start + ps]), total, p, ps


def load_completed_shadows(session: Session) -> list[UpbitOpportunityShadowEntity]:
    """collection-status와 동일 COMPLETED shadow 집합."""

    return list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )


def load_clean_obs_pairs(
    session: Session,
) -> list[tuple[UpbitOpportunityShadowEntity, ForwardObs]]:
    """CLEAN SoT — assign_clean_forward_obs와 동일 판정."""

    completed = load_completed_shadows(session)
    by_id = {int(r.shadow_id): r for r in completed}
    pairs: list[tuple[UpbitOpportunityShadowEntity, ForwardObs]] = []
    for row in completed:
        cls = classify_forward_row(row)
        if not cls.get("clean"):
            continue
        obs = build_forward_obs(row, cohort=COHORT_CLEAN_FORWARD)
        if obs is None:
            continue
        pairs.append((by_id[int(row.shadow_id)], obs))
    # detected_at DESC (UI 기본 정렬)
    pairs.sort(
        key=lambda t: (
            t[1].detected_at or datetime.min.replace(tzinfo=timezone.utc),
            t[1].shadow_id,
        ),
        reverse=True,
    )
    return pairs


def _row_list_item(
    row: UpbitOpportunityShadowEntity,
    obs: ForwardObs,
) -> dict[str, Any]:
    prov = _provenance(row)
    label = outcome_label(obs)
    return {
        "shadow_id": int(row.shadow_id),
        "detected_at": _iso_kst(obs.detected_at or row.detected_at),
        "detected_at_utc": (
            _as_utc(obs.detected_at or row.detected_at).isoformat()
            if _as_utc(obs.detected_at or row.detected_at)
            else None
        ),
        "symbol": str(row.symbol or obs.symbol or ""),
        "scanner_run_id": str(row.scanner_run_id or ""),
        "candidate_score": _dec(row.scanner_score),
        "ai_recommendation": str(row.recommendation or ""),
        "ai_score": None,  # SoT에 별도 AI score 컬럼 없음
        "ai_confidence": _dec(row.confidence),
        "canonical_entry_price": _dec(row.entry_price),
        "entry_price_provenance": prov,
        "entry_price_quality": (
            str(prov.get("quality") or "") if isinstance(prov, dict) else None
        ),
        "return_5m_pct": _dec(row.return_5m_pct),
        "return_15m_pct": _dec(row.return_15m_pct),
        "return_30m_pct": _dec(row.return_30m_pct),
        "return_60m_pct": _dec(row.return_60m_pct),
        "mfe_pct": _dec(obs.mfe_pct if obs.mfe_pct is not None else row.mfe_pct),
        "mae_pct": _dec(obs.mae_pct if obs.mae_pct is not None else row.mae_pct),
        "outcome_label": label,
        "early_dump": bool(obs.early_dump),
        "data_quality": (
            str(prov.get("quality") or "") if isinstance(prov, dict) else None
        ),
        "is_clean": True,
        "clean_cohort": COHORT_CLEAN_FORWARD,
        "research_stamp_backfill": is_research_stamp_backfill(row),
    }


def list_clean_forward(
    session: Session,
    *,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    symbol: str | None = None,
    recommendation: str | None = None,
    outcome: str | None = None,
    early_dump: bool | None = None,
    data_quality: str | None = None,
    detected_from: datetime | None = None,
    detected_to: datetime | None = None,
) -> dict[str, Any]:
    """CLEAN Forward 목록 — Legacy/Backfill 제외, 서버 pagination."""

    pairs = load_clean_obs_pairs(session)
    filtered: list[tuple[UpbitOpportunityShadowEntity, ForwardObs]] = []
    sym_q = (symbol or "").strip().upper()
    rec_q = (recommendation or "").strip().upper()
    out_q = (outcome or "").strip().upper()
    dq_q = (data_quality or "").strip().upper()
    from_u = _as_utc(detected_from)
    to_u = _as_utc(detected_to)

    for row, obs in pairs:
        if sym_q and str(row.symbol or "").upper() != sym_q:
            continue
        if rec_q and str(row.recommendation or "").upper() != rec_q:
            continue
        if early_dump is not None and bool(obs.early_dump) != bool(early_dump):
            continue
        det = _as_utc(obs.detected_at or row.detected_at)
        if from_u is not None and (det is None or det < from_u):
            continue
        if to_u is not None and (det is None or det > to_u):
            continue
        item_preview = _row_list_item(row, obs)
        if out_q and str(item_preview.get("outcome_label") or "").upper() != out_q:
            continue
        if dq_q and str(item_preview.get("data_quality") or "").upper() != dq_q:
            continue
        filtered.append((row, obs))

    page_items, total, p, ps = _paginate(filtered, page=page, page_size=page_size)
    return {
        "schema": "upbit_research_clean_forward_list_v1",
        "research_only": True,
        "items": [_row_list_item(r, o) for r, o in page_items],
        "total": total,
        "page": p,
        "page_size": ps,
        "sort": "detected_at_desc",
        "legacy_excluded": True,
        "backfill_excluded": True,
        "filters": {
            "symbol": symbol,
            "recommendation": recommendation,
            "outcome": outcome,
            "early_dump": early_dump,
            "data_quality": data_quality,
            "detected_from": from_u.isoformat() if from_u else None,
            "detected_to": to_u.isoformat() if to_u else None,
        },
    }


def _market_as_of_bundle(
    session: Session,
    *,
    detected_at: datetime,
    symbol: str,
) -> dict[str, Any]:
    """entry 시점 context — lookahead 금지. 연결 불확실 시 명시."""

    svc = MarketContextSnapshotService(session)
    det = _as_utc(detected_at)
    if det is None:
        return {
            "ok": False,
            "reason": "MISSING_DETECTED_AT",
            "market": None,
            "asset": None,
            "relation_confidence": "NONE",
        }

    fear = select_latest_as_of(
        svc.list_market_feature("fear_greed", limit=50), detected_at=det
    )
    adv = select_latest_as_of(
        svc.list_market_feature("advancing_asset_ratio", limit=50), detected_at=det
    )
    turn = select_latest_as_of(
        svc.list_market_feature("24h_turnover", limit=50), detected_at=det
    )
    mret = select_latest_as_of(
        svc.list_market_feature("market_return", limit=50), detected_at=det
    )
    asset = select_latest_as_of(
        svc.list_asset_feature(symbol, "asset_ticker_bundle", limit=50),
        detected_at=det,
    )

    checks = []
    for name, row in (
        ("fear_greed", fear),
        ("advancing_asset_ratio", adv),
        ("24h_turnover", turn),
        ("market_return", mret),
        ("asset", asset),
    ):
        if row is None:
            checks.append({"field": name, "ok": False, "reason": "NOT_FOUND"})
            continue
        checks.append(
            assert_no_lookahead(
                detected_at=det,
                context_timestamp=row.get("source_timestamp") or row.get("observed_at"),
                field=name,
            )
        )

    return {
        "ok": all(c.get("ok") for c in checks if c.get("reason") != "NOT_FOUND"),
        "relation_confidence": "BEST_EFFORT_AS_OF",
        "lookahead_checks": checks,
        "fear_greed": fear,
        "advancing_asset_ratio": adv,
        "turnover_24h": turn,
        "market_return": mret,
        "asset_context": asset,
        "collected_at_hint": _iso_kst(det),
    }


def _news_before(
    session: Session,
    *,
    symbol: str,
    detected_at: datetime,
    limit: int = 20,
) -> dict[str, Any]:
    """detected_at 이전 뉴스/공지만 — 미래 뉴스 제외."""

    from stock_platform.news.collector_constants import (
        SOURCE_CODE_CRYPTO_NEWS,
        SOURCE_CODE_UPBIT_NOTICE,
    )
    from stock_platform.news.models import NewsArticle, NewsArticleSymbol

    det = _as_utc(detected_at)
    if det is None:
        return {
            "items": [],
            "lookahead_protected": True,
            "cutoff": None,
            "relation_confidence": "NONE",
        }

    # symbol 직접 매칭 + symbol map
    q = (
        select(NewsArticle)
        .outerjoin(
            NewsArticleSymbol,
            NewsArticleSymbol.article_id == NewsArticle.article_id,
        )
        .where(
            NewsArticle.published_at.is_not(None),
            NewsArticle.published_at <= det,
            or_(
                func.upper(NewsArticle.symbol) == symbol.upper(),
                func.upper(NewsArticleSymbol.symbol) == symbol.upper(),
            ),
            NewsArticle.source_code.in_(
                [SOURCE_CODE_CRYPTO_NEWS, SOURCE_CODE_UPBIT_NOTICE]
            ),
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    rows = list(session.scalars(q).unique())
    items = []
    for a in rows:
        src = str(a.source_code or "")
        items.append(
            {
                "article_id": int(a.article_id),
                "published_at": _iso_kst(a.published_at),
                "collected_at": _iso_kst(a.created_at),
                "source": src,
                "type": "NOTICE" if "NOTICE" in src.upper() else "NEWS",
                "title": a.title,
                "related_symbol": a.symbol,
                "summary": a.description,
                "url": a.original_link or a.naver_link,
                "llm_used": None,  # 기사 단위 LLM 플래그 SoT 없으면 추측 금지
                "duplicate_hint": None,
                "lookahead_ok": True,
            }
        )
    return {
        "items": items,
        "lookahead_protected": True,
        "cutoff": det.isoformat(),
        "cutoff_kst": _iso_kst(det),
        "relation_confidence": "BEST_EFFORT_SYMBOL_AS_OF",
        "note_ko": "detected_at 이후 발행 뉴스는 제외했습니다 (lookahead 방지).",
    }


def _llm_for_shadow(
    session: Session,
    *,
    shadow_id: int,
    symbol: str,
    detected_at: datetime | None,
) -> dict[str, Any]:
    row = session.scalar(
        select(UpbitLlmContextAnalysisEntity)
        .where(UpbitLlmContextAnalysisEntity.shadow_id == shadow_id)
        .order_by(UpbitLlmContextAnalysisEntity.created_at.desc())
        .limit(1)
    )
    relation = "EXACT_SHADOW_ID"
    if row is None and detected_at is not None:
        # best-effort: 동일 symbol + context_as_of <= detected_at
        det = _as_utc(detected_at)
        if det is not None:
            row = session.scalar(
                select(UpbitLlmContextAnalysisEntity)
                .where(
                    UpbitLlmContextAnalysisEntity.symbol == symbol,
                    UpbitLlmContextAnalysisEntity.context_as_of <= det,
                )
                .order_by(UpbitLlmContextAnalysisEntity.context_as_of.desc())
                .limit(1)
            )
            relation = "BEST_EFFORT_SYMBOL_AS_OF" if row else "NONE"

    if row is None:
        return {
            "found": False,
            "relation_confidence": relation,
            "empty_hint_ko": "신규 Scanner Shadow 후보 발생 시 분석됩니다.",
            "analysis": None,
        }

    out = row.output_json if isinstance(row.output_json, dict) else {}
    inp = row.input_json if isinstance(row.input_json, dict) else {}
    return {
        "found": True,
        "relation_confidence": relation,
        "analysis": {
            "analysis_id": int(row.analysis_id),
            "shadow_id": row.shadow_id,
            "symbol": row.symbol,
            "recommendation": row.recommendation,
            "confidence": row.confidence,
            "entry_quality_score": row.entry_quality_score,
            "risk_flags": out.get("risk_flags") if isinstance(out, dict) else None,
            "reason": out.get("reason") or out.get("rationale"),
            "analysis_at": _iso_kst(row.created_at),
            "context_as_of": _iso_kst(row.context_as_of),
            "quality": row.quality,
            "lookahead_ok": bool(row.lookahead_ok),
            "model": (
                (inp.get("model") if isinstance(inp, dict) else None)
                or (out.get("model") if isinstance(out, dict) else None)
            ),
            "structured_input": inp,  # prompt 전문이 아닌 structured context
            "structured_output": out,
        },
    }


def get_clean_forward_detail(
    session: Session,
    *,
    shadow_id: int,
) -> dict[str, Any] | None:
    """CLEAN row drill-down. CLEAN이 아니면 None (404)."""

    row = session.scalar(
        select(UpbitOpportunityShadowEntity).where(
            UpbitOpportunityShadowEntity.shadow_id == shadow_id,
            UpbitOpportunityShadowEntity.deleted_at.is_(None),
        )
    )
    if row is None:
        return None

    cls = classify_forward_row(row)
    if not cls.get("clean"):
        return None
    obs = build_forward_obs(row, cohort=COHORT_CLEAN_FORWARD)
    if obs is None:
        return None

    snap = _snap(row)
    cand = snap.get("candidate") if isinstance(snap.get("candidate"), dict) else {}
    detail = _detail(row)
    features = extract_forward_features(row)
    prov = _provenance(row)
    det = _as_utc(row.detected_at)

    market_bundle = _market_as_of_bundle(
        session, detected_at=det or datetime.now(timezone.utc), symbol=str(row.symbol)
    )
    news_bundle = _news_before(
        session,
        symbol=str(row.symbol),
        detected_at=det or datetime.now(timezone.utc),
    )
    llm_bundle = _llm_for_shadow(
        session,
        shadow_id=int(row.shadow_id),
        symbol=str(row.symbol),
        detected_at=det,
    )

    return {
        "schema": "upbit_research_clean_forward_detail_v1",
        "research_only": True,
        "lookahead_sections_separated": True,
        "shadow_id": int(row.shadow_id),
        "classification": cls,
        "list_fields": _row_list_item(row, obs),
        # ── entry 당시 (lookahead 금지 영역) ─────────────────────────────
        "at_entry": {
            "candidate": {
                "scanner_run_id": str(row.scanner_run_id or ""),
                "detected_at": _iso_kst(row.detected_at),
                "symbol": str(row.symbol),
                "score": _dec(row.scanner_score),
                "scanner_rank": row.scanner_rank,
                "candidate_reason": cand.get("reason") or cand.get("recommendation"),
                "candidate_snapshot": cand,
            },
            "technical_features": {
                "ma5": _dec(row.ma5),
                "ma20": _dec(row.ma20),
                "rsi14": _dec(row.rsi14),
                "macd": _dec(row.macd),
                "atr14": _dec(row.atr14),
                "volume_surge": _dec(row.volume_surge),
                "trade_value_24h": _dec(row.trade_value_24h),
                "ma_separation_pct": features.get("ma_separation_pct"),
                "pre_spike": {
                    "return_1m": features.get("return_1m"),
                    "return_3m": features.get("return_3m"),
                },
                "near_high": features.get("dist_from_15m_high"),
                "stored_features": features,
            },
            "market_context": market_bundle,
            "asset_context": market_bundle.get("asset_context"),
            "news_notice": news_bundle,
            "llm_analysis": llm_bundle,
        },
        # ── outcome (entry 이후) ─────────────────────────────────────────
        "forward_outcome": {
            "entry_price": _dec(row.entry_price),
            "return_5m_pct": _dec(row.return_5m_pct),
            "return_15m_pct": _dec(row.return_15m_pct),
            "return_30m_pct": _dec(row.return_30m_pct),
            "return_60m_pct": _dec(row.return_60m_pct),
            "mfe_pct": _dec(row.mfe_pct),
            "mae_pct": _dec(row.mae_pct),
            "outcome_label": outcome_label(obs),
            "early_dump": bool(obs.early_dump),
            "baseline_outcome": obs.outcome,
            "completed_at": _iso_kst(row.completed_at),
        },
        "research_quality": {
            "canonical_price_provenance": prov,
            "exit_ab": detail.get("exit_ab"),
            "entry_ab": detail.get("entry_ab"),
            "entry_forward_features": detail.get("entry_forward_features"),
            "research_stamp_backfill": is_research_stamp_backfill(row),
            "clean_eligible": bool(cls.get("promotion_eligible")),
            "classification_reasons": cls.get("reasons"),
            "exclusions": cls.get("exclusions"),
        },
    }


def _flatten_market_value(value_json: Any) -> dict[str, Any]:
    if not isinstance(value_json, dict):
        return {}
    return value_json


def list_market_context(
    session: Session,
    *,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    feature_key: str | None = None,
    collected_from: datetime | None = None,
    collected_to: datetime | None = None,
) -> dict[str, Any]:
    q = select(UpbitMarketContextSnapshotEntity)
    cq = select(func.count(UpbitMarketContextSnapshotEntity.snapshot_id))
    if feature_key:
        q = q.where(UpbitMarketContextSnapshotEntity.feature_key == feature_key)
        cq = cq.where(UpbitMarketContextSnapshotEntity.feature_key == feature_key)
    if collected_from is not None:
        fr = _as_utc(collected_from)
        q = q.where(UpbitMarketContextSnapshotEntity.observed_at >= fr)
        cq = cq.where(UpbitMarketContextSnapshotEntity.observed_at >= fr)
    if collected_to is not None:
        to = _as_utc(collected_to)
        q = q.where(UpbitMarketContextSnapshotEntity.observed_at <= to)
        cq = cq.where(UpbitMarketContextSnapshotEntity.observed_at <= to)
    total = int(session.scalar(cq) or 0)
    p = max(1, int(page or DEFAULT_PAGE))
    ps = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    rows = list(
        session.scalars(
            q.order_by(UpbitMarketContextSnapshotEntity.observed_at.desc())
            .offset((p - 1) * ps)
            .limit(ps)
        )
    )
    items = []
    now = datetime.now(timezone.utc)
    for r in rows:
        vj = _flatten_market_value(r.value_json)
        stale = False
        if r.stale_after is not None and _as_utc(r.stale_after):
            stale = now > _as_utc(r.stale_after)  # type: ignore[operator]
        items.append(
            {
                "snapshot_id": int(r.snapshot_id),
                "collected_at": _iso_kst(r.observed_at),
                "source_timestamp": _iso_kst(r.source_timestamp),
                "feature_key": r.feature_key,
                "fear_greed": vj.get("value") if r.feature_key == "fear_greed" else vj.get("fear_greed"),
                "market_breadth": vj.get("ratio")
                if r.feature_key == "advancing_asset_ratio"
                else vj.get("advancing_ratio"),
                "total_turnover": vj.get("turnover_krw")
                or vj.get("total_turnover")
                or vj.get("value"),
                "market_return_proxy": vj.get("return_pct")
                or vj.get("market_return"),
                "source": r.source,
                "freshness": "STALE" if stale else "FRESH",
                "quality": r.quality,
                "status": r.quality,
                "value_json": r.value_json,
                "raw_provenance": r.raw_provenance,
            }
        )
    return {
        "schema": "upbit_research_market_context_list_v1",
        "research_only": True,
        "items": items,
        "total": total,
        "page": p,
        "page_size": ps,
    }


def list_asset_context(
    session: Session,
    *,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    symbol: str | None = None,
    collected_from: datetime | None = None,
    collected_to: datetime | None = None,
    rank_min: int | None = None,
    rank_max: int | None = None,
) -> dict[str, Any]:
    q = select(UpbitAssetContextSnapshotEntity)
    if symbol:
        q = q.where(
            func.upper(UpbitAssetContextSnapshotEntity.symbol) == symbol.strip().upper()
        )
    if collected_from is not None:
        q = q.where(
            UpbitAssetContextSnapshotEntity.observed_at >= _as_utc(collected_from)
        )
    if collected_to is not None:
        q = q.where(
            UpbitAssetContextSnapshotEntity.observed_at <= _as_utc(collected_to)
        )

    # rank 필터는 value_json 내부 — SQL 후 필터 (표본 규모 고려)
    rows_all = list(
        session.scalars(
            q.order_by(UpbitAssetContextSnapshotEntity.observed_at.desc()).limit(5000)
        )
    )

    def _rank(vj: dict[str, Any]) -> int | None:
        for k in ("turnover_rank", "rank", "volume_rank"):
            if vj.get(k) is not None:
                try:
                    return int(vj[k])
                except (TypeError, ValueError):
                    return None
        return None

    filtered = []
    for r in rows_all:
        vj = r.value_json if isinstance(r.value_json, dict) else {}
        rk = _rank(vj)
        if rank_min is not None and (rk is None or rk < rank_min):
            continue
        if rank_max is not None and (rk is None or rk > rank_max):
            continue
        filtered.append(r)

    page_rows, total, p, ps = _paginate(filtered, page=page, page_size=page_size)
    items = []
    for r in page_rows:
        vj = r.value_json if isinstance(r.value_json, dict) else {}
        items.append(
            {
                "snapshot_id": int(r.snapshot_id),
                "collected_at": _iso_kst(r.observed_at),
                "symbol": r.symbol,
                "feature_key": r.feature_key,
                "trade_price": vj.get("trade_price") or vj.get("price"),
                "daily_change_pct": vj.get("signed_change_rate")
                or vj.get("change_rate")
                or vj.get("daily_change_pct"),
                "turnover_24h": vj.get("acc_trade_price_24h")
                or vj.get("turnover_24h"),
                "turnover_rank": _rank(vj),
                "volume": vj.get("acc_trade_volume_24h") or vj.get("volume"),
                "context_quality": r.quality,
                "source": r.source,
                "value_json": r.value_json,
            }
        )
    return {
        "schema": "upbit_research_asset_context_list_v1",
        "research_only": True,
        "items": items,
        "total": total,
        "page": p,
        "page_size": ps,
        "note_ko": "rank 필터는 value_json 기반 best-effort입니다.",
    }


def list_news_notice(
    session: Session,
    *,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    symbol: str | None = None,
    source_type: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
) -> dict[str, Any]:
    from stock_platform.news.collector_constants import (
        SOURCE_CODE_CRYPTO_NEWS,
        SOURCE_CODE_UPBIT_NOTICE,
    )
    from stock_platform.news.models import NewsArticle

    codes = [SOURCE_CODE_CRYPTO_NEWS, SOURCE_CODE_UPBIT_NOTICE]
    st = (source_type or "").strip().upper()
    if st == "NOTICE":
        codes = [SOURCE_CODE_UPBIT_NOTICE]
    elif st == "NEWS":
        codes = [SOURCE_CODE_CRYPTO_NEWS]

    q = select(NewsArticle).where(NewsArticle.source_code.in_(codes))
    cq = select(func.count(NewsArticle.article_id)).where(
        NewsArticle.source_code.in_(codes)
    )
    if symbol:
        sym_u = symbol.strip().upper()
        q = q.where(func.upper(NewsArticle.symbol) == sym_u)
        cq = cq.where(func.upper(NewsArticle.symbol) == sym_u)
    if published_from is not None:
        fr = _as_utc(published_from)
        q = q.where(NewsArticle.published_at >= fr)
        cq = cq.where(NewsArticle.published_at >= fr)
    if published_to is not None:
        to = _as_utc(published_to)
        q = q.where(NewsArticle.published_at <= to)
        cq = cq.where(NewsArticle.published_at <= to)

    total = int(session.scalar(cq) or 0)
    p = max(1, int(page or DEFAULT_PAGE))
    ps = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    rows = list(
        session.scalars(
            q.order_by(NewsArticle.published_at.desc().nullslast())
            .offset((p - 1) * ps)
            .limit(ps)
        )
    )
    items = []
    for a in rows:
        src = str(a.source_code or "")
        items.append(
            {
                "article_id": int(a.article_id),
                "published_at": _iso_kst(a.published_at),
                "collected_at": _iso_kst(a.created_at),
                "source": src,
                "type": "NOTICE" if "NOTICE" in src.upper() else "NEWS",
                "title": a.title,
                "related_symbol": a.symbol,
                "summary": a.description,
                "url": a.original_link or a.naver_link,
                "llm_used": None,
                "content_hash": a.content_hash,
            }
        )
    return {
        "schema": "upbit_research_news_list_v1",
        "research_only": True,
        "items": items,
        "total": total,
        "page": p,
        "page_size": ps,
    }


def list_llm_analysis(
    session: Session,
    *,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    symbol: str | None = None,
    recommendation: str | None = None,
    shadow_id: int | None = None,
) -> dict[str, Any]:
    q = select(UpbitLlmContextAnalysisEntity)
    cq = select(func.count(UpbitLlmContextAnalysisEntity.analysis_id))
    if symbol:
        sym_u = symbol.strip().upper()
        q = q.where(func.upper(UpbitLlmContextAnalysisEntity.symbol) == sym_u)
        cq = cq.where(func.upper(UpbitLlmContextAnalysisEntity.symbol) == sym_u)
    if recommendation:
        rec_u = recommendation.strip().upper()
        q = q.where(
            func.upper(UpbitLlmContextAnalysisEntity.recommendation) == rec_u
        )
        cq = cq.where(
            func.upper(UpbitLlmContextAnalysisEntity.recommendation) == rec_u
        )
    if shadow_id is not None:
        q = q.where(UpbitLlmContextAnalysisEntity.shadow_id == shadow_id)
        cq = cq.where(UpbitLlmContextAnalysisEntity.shadow_id == shadow_id)

    total = int(session.scalar(cq) or 0)
    p = max(1, int(page or DEFAULT_PAGE))
    ps = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    rows = list(
        session.scalars(
            q.order_by(UpbitLlmContextAnalysisEntity.created_at.desc())
            .offset((p - 1) * ps)
            .limit(ps)
        )
    )
    items = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        inp = r.input_json if isinstance(r.input_json, dict) else {}
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "analysis_at": _iso_kst(r.created_at),
                "symbol": r.symbol,
                "shadow_id": r.shadow_id,
                "recommendation": r.recommendation,
                "score": r.entry_quality_score,
                "confidence": r.confidence,
                "risk_flags": out.get("risk_flags"),
                "context_as_of": _iso_kst(r.context_as_of),
                "model": inp.get("model") or out.get("model"),
                "status": r.quality,
                "lookahead_ok": bool(r.lookahead_ok),
            }
        )
    return {
        "schema": "upbit_research_llm_analysis_list_v1",
        "research_only": True,
        "items": items,
        "total": total,
        "page": p,
        "page_size": ps,
        "empty_hint_ko": (
            "신규 Scanner Shadow 후보 발생 시 분석됩니다." if total == 0 else None
        ),
    }


def get_llm_analysis_detail(
    session: Session,
    *,
    analysis_id: int,
) -> dict[str, Any] | None:
    row = session.scalar(
        select(UpbitLlmContextAnalysisEntity).where(
            UpbitLlmContextAnalysisEntity.analysis_id == analysis_id
        )
    )
    if row is None:
        return None
    out = row.output_json if isinstance(row.output_json, dict) else {}
    inp = row.input_json if isinstance(row.input_json, dict) else {}
    return {
        "schema": "upbit_research_llm_analysis_detail_v1",
        "research_only": True,
        "analysis_id": int(row.analysis_id),
        "symbol": row.symbol,
        "shadow_id": row.shadow_id,
        "recommendation": row.recommendation,
        "score": row.entry_quality_score,
        "confidence": row.confidence,
        "risk_flags": out.get("risk_flags"),
        "reason": out.get("reason") or out.get("rationale"),
        "analysis_at": _iso_kst(row.created_at),
        "context_as_of": _iso_kst(row.context_as_of),
        "model": inp.get("model") or out.get("model"),
        "status": row.quality,
        "lookahead_ok": bool(row.lookahead_ok),
        "structured_context": {
            "technical": inp.get("technical"),
            "market": inp.get("market"),
            "asset": inp.get("asset"),
            "news": inp.get("news"),
            "description": inp.get("description"),
            "candidate": inp.get("candidate"),
        },
        "structured_output": out,
        "note_ko": "LLM 원문 prompt 전체가 아닌 저장된 structured context를 표시합니다.",
    }


def get_filter_experiments(session: Session) -> dict[str, Any]:
    completed = load_completed_shadows(session)
    partition = partition_forward_rows(completed)
    exp = summarize_entry_quality_experiment_from_shadows(completed)
    clean_n = int(exp.get("CLEAN_SAMPLE_COUNT") or len(partition.get("clean_rows") or []))
    # CLEAN obs 기준 재확인 (collection-status 정합)
    clean_pairs = load_clean_obs_pairs(session)
    clean_total = len(clean_pairs)

    filters = exp.get("filters") if isinstance(exp.get("filters"), dict) else {}
    arms = []
    for code in ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"):
        arm = filters.get(code)
        if not isinstance(arm, dict):
            continue
        kpi = arm.get("kpi") if isinstance(arm.get("kpi"), dict) else {}
        arms.append(
            {
                "experiment": code,
                "name": arm.get("name") or arm.get("description") or code,
                "accepted": arm.get("accepted"),
                "filtered": arm.get("filtered"),
                "avoided_loss": arm.get("avoided_loser_value")
                or arm.get("avoided_losers"),
                "missed_winner": arm.get("missed_winner_value")
                or arm.get("missed_winners"),
                "benefit": arm.get("filter_benefit") or arm.get("net_filter_benefit"),
                "net": kpi.get("net_pnl") if kpi else arm.get("net_pnl"),
                "pf": kpi.get("profit_factor") if kpi else arm.get("profit_factor"),
                "early_dump_rate": kpi.get("early_dump_rate")
                if kpi
                else arm.get("early_dump_rate"),
                "skipped": bool(arm.get("skipped")),
            }
        )

    best = exp.get("BEST_FILTER_CURRENTLY")
    under_target = clean_total < TARGET_CLEAN_MIN
    return {
        "schema": "upbit_research_filter_experiments_v1",
        "research_only": True,
        "clean_sample_count": clean_total,
        "sample_gate": sample_gate(clean_total),
        "under_promotion_sample": under_target,
        "warning_ko": (
            "연구 표본 수집 중 — REAL 전략 승격 근거로 사용할 수 없습니다."
            if under_target
            else None
        ),
        "best_filter_currently": best,
        "best_filter_label_ko": "현재 연구 후보" if best else None,
        "arms": arms,
        "experiment_raw_summary": {
            "FINAL_VERDICT": exp.get("FINAL_VERDICT"),
            "REAL_PROMOTION_RECOMMENDED": exp.get("REAL_PROMOTION_RECOMMENDED"),
            "AUTO_PROMOTE": exp.get("AUTO_PROMOTE"),
        },
        "legacy_excluded": True,
        "backfill_excluded": True,
    }


def clean_total_count(session: Session) -> int:
    """collection-status CLEAN count와 동일 SoT."""

    return len(load_clean_obs_pairs(session))
