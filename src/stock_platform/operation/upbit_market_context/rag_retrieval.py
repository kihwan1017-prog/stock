"""CLEAN Forward RAG — lightweight hybrid retrieval (no Vector DB).

원칙:
- CLEAN eligible + outcome 확정된 과거 사례만
- Legacy / Backfill / invalid price / lookahead 제외
- rag_case.outcome_completed_at < current.detected_at (필수)
- 현재 후보 자신의 미래 outcome은 입력 금지
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_market_context.as_of import as_utc
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    classify_forward_row,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    build_forward_obs,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    metrics_from_shadow_row,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    outcome_label,
)
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    COHORT_CLEAN_FORWARD,
)

# 유사도 가중치 (합=1.0) — 수치 feature 중심
_W_RSI = 0.25
_W_MA = 0.20
_W_VOL = 0.20
_W_SCORE = 0.20
_W_CAT = 0.15

# 정규화 스케일 (대략적 feature range)
_SCALE = {
    "rsi": 50.0,
    "ma_sep": 2.0,
    "vol": 3.0,
    "score": 50.0,
}


class RagRetrievalCache:
    """유사 candidate context TTL cache — 무기한 금지."""

    def __init__(self, max_items: int = 128) -> None:
        self._max = max_items
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            expires, payload = item
            if expires < now:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return dict(payload)

    def put(self, key: str, payload: dict[str, Any], *, ttl_seconds: float) -> None:
        with self._lock:
            self._data[key] = (time.time() + max(30.0, ttl_seconds), dict(payload))
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


rag_cache = RagRetrievalCache()


def _num(v: Any) -> float | None:
    if v is None or v == "NOT_AVAILABLE":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_dist(a: float | None, b: float | None, scale: float) -> float:
    """0=동일, 1=멀리 — 결측은 중립 0.5."""

    if a is None or b is None:
        return 0.5
    return min(1.0, abs(a - b) / max(scale, 1e-6))


def is_rag_eligible_row(row: Any) -> bool:
    """CLEAN + COMPLETED + outcome windows 존재."""

    if getattr(row, "status", None) != SHADOW_STATUS_COMPLETED:
        return False
    if getattr(row, "completed_at", None) is None:
        return False
    cls = classify_forward_row(row)
    if not cls.get("clean"):
        return False
    # outcome window 핵심 품질
    if getattr(row, "return_5m_pct", None) is None:
        return False
    if getattr(row, "return_60m_pct", None) is None and getattr(row, "mfe_pct", None) is None:
        return False
    return True


def build_rag_case_document(row: Any) -> dict[str, Any] | None:
    """CLEAN 사례 → RAG document. 미래 결과는 outcome에만."""

    if not is_rag_eligible_row(row):
        return None
    cls = classify_forward_row(row)
    obs = build_forward_obs(row, cohort=COHORT_CLEAN_FORWARD)
    if obs is None:
        return None
    metrics = metrics_from_shadow_row(row)
    feat = obs.features or {}
    label = outcome_label(obs)
    completed = as_utc(getattr(row, "completed_at", None))
    detected = as_utc(getattr(row, "detected_at", None))
    return {
        "case_id": f"shadow:{int(row.shadow_id)}",
        "shadow_id": int(row.shadow_id),
        "symbol": str(row.symbol or ""),
        "detected_at": detected.isoformat() if detected else None,
        "outcome_completed_at": completed.isoformat() if completed else None,
        "clean": True,
        "cohort": cls.get("cohort"),
        "entry_context": {
            "rsi": metrics.rsi14,
            "ma_separation_pct": metrics.ma_separation_pct,
            "volume_ratio": metrics.volume_surge,
            "scanner_score": (
                float(row.scanner_score)
                if getattr(row, "scanner_score", None) is not None
                else None
            ),
            "recommendation": getattr(row, "recommendation", None),
            "pre_entry_return_5m": feat.get("pre_entry_return_5m"),
            "near_high_distance": feat.get("dist_from_15m_high"),
            "market_state": None,
            "fear_greed": None,
            "analysis_risk_flags": [],
        },
        "outcome": {
            "return_5m": getattr(row, "return_5m_pct", None),
            "return_15m": getattr(row, "return_15m_pct", None),
            "return_30m": getattr(row, "return_30m_pct", None),
            "return_60m": getattr(row, "return_60m_pct", None),
            "mfe": obs.mfe_pct,
            "mae": obs.mae_pct,
            "early_dump": bool(obs.early_dump),
            "label": label,
        },
    }


def candidate_feature_vector(
    *,
    technical: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tech = technical or {}
    cand = candidate or {}
    ana = analysis or {}
    rsi = _num(tech.get("rsi14") if "rsi14" in tech else tech.get("rsi"))
    ma = _num(tech.get("ma_separation_pct"))
    if ma is None:
        ma5 = _num(tech.get("ma5"))
        ma20 = _num(tech.get("ma20"))
        if ma5 is not None and ma20 is not None and abs(ma20) > 1e-12:
            ma = ((ma5 - ma20) / abs(ma20)) * 100.0
    vol = _num(tech.get("volume_surge") or tech.get("volume_ratio"))
    score = _num(cand.get("score") or cand.get("scanner_score"))
    risks = ana.get("risk_factors") or ana.get("risk_flags") or []
    if not isinstance(risks, list):
        risks = []
    return {
        "rsi": rsi,
        "ma_separation_pct": ma,
        "volume_ratio": vol,
        "scanner_score": score,
        "pre_entry_return": _num(tech.get("pre_entry_return") or tech.get("pre_entry_return_5m")),
        "risk_flags": [str(x).upper()[:40] for x in risks[:10]],
        "tone": str(ana.get("tone") or "").upper() or None,
    }


def similarity_score(query: dict[str, Any], case: dict[str, Any]) -> float:
    """1.0 = 가장 유사. structured distance + categorical match."""

    ec = case.get("entry_context") or {}
    d_rsi = _norm_dist(query.get("rsi"), _num(ec.get("rsi")), _SCALE["rsi"])
    d_ma = _norm_dist(
        query.get("ma_separation_pct"),
        _num(ec.get("ma_separation_pct")),
        _SCALE["ma_sep"],
    )
    d_vol = _norm_dist(
        query.get("volume_ratio"),
        _num(ec.get("volume_ratio")),
        _SCALE["vol"],
    )
    d_score = _norm_dist(
        query.get("scanner_score"),
        _num(ec.get("scanner_score")),
        _SCALE["score"],
    )
    # categorical: risk flag Jaccard distance (0=동일)
    q_flags = set(query.get("risk_flags") or [])
    c_flags = set(ec.get("analysis_risk_flags") or [])
    if not q_flags and not c_flags:
        cat = 0.5
    elif not q_flags or not c_flags:
        cat = 0.65
    else:
        inter = len(q_flags & c_flags)
        union = len(q_flags | c_flags) or 1
        cat = 1.0 - (inter / union)
    dist = (
        _W_RSI * d_rsi
        + _W_MA * d_ma
        + _W_VOL * d_vol
        + _W_SCORE * d_score
        + _W_CAT * cat
    )
    return round(max(0.0, min(1.0, 1.0 - dist)), 6)


def _cache_key(query: dict[str, Any], *, detected_at: datetime) -> str:
    blob = {
        "rsi": query.get("rsi"),
        "ma": query.get("ma_separation_pct"),
        "vol": query.get("volume_ratio"),
        "score": query.get("scanner_score"),
        "flags": sorted(query.get("risk_flags") or []),
        "as_of_min": detected_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
    }
    raw = str(sorted(blob.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]


def retrieve_similar_cases(
    session: Session,
    *,
    detected_at: datetime,
    technical: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    analysis: dict[str, Any] | None = None,
    top_k: int | None = None,
    exclude_shadow_id: int | None = None,
) -> dict[str, Any]:
    """과거 CLEAN 사례 hybrid TOP-K. no-lookahead 강제."""

    s = get_settings()
    k = int(top_k if top_k is not None else getattr(s, "dual_llm_rag_top_k", 5) or 5)
    k = max(1, min(10, k))
    ttl = float(getattr(s, "dual_llm_rag_cache_ttl_seconds", 300.0) or 300.0)
    det = as_utc(detected_at) or detected_at
    if det.tzinfo is None:
        det = det.replace(tzinfo=timezone.utc)

    query = candidate_feature_vector(
        technical=technical, candidate=candidate, analysis=analysis
    )
    ck = _cache_key(query, detected_at=det)
    cached = rag_cache.get(ck)
    if cached is not None:
        # exclude self if needed
        examples = [
            e
            for e in (cached.get("examples") or [])
            if exclude_shadow_id is None
            or int(e.get("shadow_id") or 0) != int(exclude_shadow_id)
        ]
        return {
            **cached,
            "examples": examples[:k],
            "cache_hit": True,
            "top_k": k,
        }

    rows = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
                UpbitOpportunityShadowEntity.completed_at.is_not(None),
                UpbitOpportunityShadowEntity.completed_at < det,
            )
        )
    )

    scored: list[tuple[float, dict[str, Any]]] = []
    excluded = {
        "legacy_or_not_clean": 0,
        "lookahead_or_incomplete": 0,
        "self": 0,
        "build_failed": 0,
    }
    for row in rows:
        sid = int(row.shadow_id)
        if exclude_shadow_id is not None and sid == int(exclude_shadow_id):
            excluded["self"] += 1
            continue
        completed = as_utc(row.completed_at)
        if completed is None or completed >= det:
            excluded["lookahead_or_incomplete"] += 1
            continue
        if not is_rag_eligible_row(row):
            excluded["legacy_or_not_clean"] += 1
            continue
        doc = build_rag_case_document(row)
        if doc is None:
            excluded["build_failed"] += 1
            continue
        sim = similarity_score(query, doc)
        prompt_ex = {
            "case_id": doc["case_id"],
            "shadow_id": sid,
            "symbol": doc["symbol"],
            "similarity_score": sim,
            "entry_summary": {
                "rsi": (doc["entry_context"] or {}).get("rsi"),
                "ma_separation_pct": (doc["entry_context"] or {}).get(
                    "ma_separation_pct"
                ),
                "volume_ratio": (doc["entry_context"] or {}).get("volume_ratio"),
                "scanner_score": (doc["entry_context"] or {}).get("scanner_score"),
            },
            "actual_label": (doc["outcome"] or {}).get("label"),
            "mfe": (doc["outcome"] or {}).get("mfe"),
            "mae": (doc["outcome"] or {}).get("mae"),
            "early_dump": (doc["outcome"] or {}).get("early_dump"),
            "outcome_completed_at": doc.get("outcome_completed_at"),
            # 과거 실제 결과 — 예제로만 허용 (현재 후보 미래 아님)
            "historical_returns": {
                "return_5m": (doc["outcome"] or {}).get("return_5m"),
                "return_60m": (doc["outcome"] or {}).get("return_60m"),
            },
        }
        scored.append((sim, prompt_ex))

    scored.sort(key=lambda x: (-x[0], x[1].get("shadow_id") or 0))
    examples = [e for _, e in scored[:k]]
    payload = {
        "ok": True,
        "retrieval_method": "structured_hybrid_normalized_distance",
        "top_k": k,
        "pool_scanned": len(rows),
        "eligible_scored": len(scored),
        "excluded": excluded,
        "examples": examples,
        "query_features": query,
        "no_lookahead": True,
        "clean_only": True,
        "cache_hit": False,
        "as_of": det.isoformat(),
    }
    rag_cache.put(ck, {**payload, "cache_hit": False}, ttl_seconds=ttl)
    return payload


def assert_no_lookahead(
    examples: list[dict[str, Any]], *, detected_at: datetime
) -> bool:
    """테스트용 — 모든 RAG case가 detected_at 이전에 완료됐는지."""

    det = as_utc(detected_at) or detected_at
    for ex in examples:
        completed_s = ex.get("outcome_completed_at")
        if not completed_s:
            return False
        completed = as_utc(datetime.fromisoformat(str(completed_s).replace("Z", "+00:00")))
        if completed is None or completed >= det:
            return False
    return True


__all__ = [
    "rag_cache",
    "is_rag_eligible_row",
    "build_rag_case_document",
    "candidate_feature_vector",
    "similarity_score",
    "retrieve_similar_cases",
    "assert_no_lookahead",
]
