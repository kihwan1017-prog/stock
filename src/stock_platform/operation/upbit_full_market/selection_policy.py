"""후보 선택 순수 정책 — Broker 주문 없음."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stock_platform.operation.upbit_full_market.constants import (
    AI_GATE_ENFORCE,
    AI_GATE_OFF,
    AI_GATE_SHADOW,
    ALLOW_RECOMMENDATIONS,
    BLOCK_RECOMMENDATIONS,
)


@dataclass
class SelectionPolicy:
    """FULL_MARKET 후보 선택 임계값 (config-driven)."""

    min_score: float = 0.0
    min_liquidity_krw: float = 0.0
    min_confidence: float = 0.0
    max_candidate_age_seconds: float = 1800.0
    ai_live_gate_mode: str = AI_GATE_ENFORCE
    excluded_symbols: frozenset[str] = field(default_factory=frozenset)
    allow_reduce_as_entry: bool = True


@dataclass
class RankedCandidate:
    symbol: str
    rank: int | None
    score: float | None
    recommendation: str
    confidence: float | None
    liquidity: float | None
    market_data_timestamp: datetime | None
    ai_analysis_id: int | None
    technical_metrics: dict[str, Any]
    raw: dict[str, Any]


@dataclass
class SelectionDecision:
    selected: RankedCandidate | None
    reason: str
    skip_trace: list[dict[str, Any]]
    scanner_run_id: str | None = None


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def candidate_from_scanner_row(
    row: dict[str, Any],
    *,
    rank: int | None = None,
) -> RankedCandidate:
    """Scanner top candidate dict → RankedCandidate."""

    rec = str(row.get("recommendation") or row.get("ai_recommendation") or "HOLD").upper()
    conf = row.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None
    score = row.get("score") or row.get("scanner_score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    liq = row.get("trade_value_24h") or row.get("liquidity")
    try:
        liq_f = float(liq) if liq is not None else None
    except (TypeError, ValueError):
        liq_f = None
    ts_raw = row.get("market_data_timestamp") or row.get("analyzed_at")
    ts: datetime | None = None
    if isinstance(ts_raw, datetime):
        ts = ts_raw
    elif isinstance(ts_raw, str) and ts_raw.strip():
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            ts = None
    aid = row.get("market_analysis_id") or row.get("ai_analysis_id")
    try:
        aid_i = int(aid) if aid is not None else None
    except (TypeError, ValueError):
        aid_i = None
    tech = {
        k: row.get(k)
        for k in (
            "ma5",
            "ma20",
            "rsi14",
            "macd",
            "atr14",
            "volume_surge",
            "trend",
            "momentum",
            "volatility",
            "risk_level",
        )
        if row.get(k) is not None
    }
    rnk = rank if rank is not None else row.get("rank") or row.get("scanner_rank")
    try:
        rnk_i = int(rnk) if rnk is not None else None
    except (TypeError, ValueError):
        rnk_i = None
    return RankedCandidate(
        symbol=str(row.get("symbol") or "").strip().upper(),
        rank=rnk_i,
        score=score_f,
        recommendation=rec,
        confidence=conf_f,
        liquidity=liq_f,
        market_data_timestamp=_aware(ts),
        ai_analysis_id=aid_i,
        technical_metrics=tech,
        raw=dict(row),
    )


def evaluate_candidate_gates(
    candidate: RankedCandidate,
    policy: SelectionPolicy,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """단일 후보 PASS/FAIL. HOLD는 강제 ALLOW 하지 않음."""

    now = now or datetime.now(timezone.utc)
    sym = candidate.symbol
    if not sym or not sym.startswith("KRW-"):
        return False, "INVALID_SYMBOL"
    if sym in policy.excluded_symbols:
        return False, "SYMBOL_EXCLUDED"

    if candidate.score is not None and candidate.score < policy.min_score:
        return False, "SCORE_BELOW_THRESHOLD"
    if (
        candidate.liquidity is not None
        and policy.min_liquidity_krw > 0
        and candidate.liquidity < policy.min_liquidity_krw
    ):
        return False, "LIQUIDITY_BELOW_THRESHOLD"

    age_limit = float(policy.max_candidate_age_seconds)
    if age_limit > 0 and candidate.market_data_timestamp is not None:
        age = (now - candidate.market_data_timestamp).total_seconds()
        if age > age_limit:
            return False, "CANDIDATE_STALE"

    gate = str(policy.ai_live_gate_mode or AI_GATE_ENFORCE).upper()
    rec = candidate.recommendation
    if gate == AI_GATE_OFF:
        # AI gate 미사용 — 기술 점수만 (권장하지 않음, fail-open for gate only)
        pass
    elif gate == AI_GATE_SHADOW:
        # SHADOW: 기록용, selection은 ALLOW 계열만 통과 (강제 변환 없음)
        if rec in BLOCK_RECOMMENDATIONS:
            return False, "AI_BLOCK_SHADOW"
        if rec == "HOLD":
            return False, "AI_HOLD"
        if rec not in ALLOW_RECOMMENDATIONS:
            return False, f"AI_REC_{rec}"
        if not policy.allow_reduce_as_entry and rec == "REDUCE":
            return False, "AI_REDUCE_NOT_ALLOWED"
    else:
        # ENFORCE (기본)
        if rec in BLOCK_RECOMMENDATIONS:
            return False, "AI_BLOCK"
        if rec == "HOLD":
            return False, "AI_HOLD"
        if rec not in ALLOW_RECOMMENDATIONS:
            return False, f"AI_REC_{rec}"
        if not policy.allow_reduce_as_entry and rec == "REDUCE":
            return False, "AI_REDUCE_NOT_ALLOWED"

    if (
        candidate.confidence is not None
        and policy.min_confidence > 0
        and candidate.confidence < policy.min_confidence
    ):
        return False, "CONFIDENCE_BELOW_THRESHOLD"

    return True, "PASS"


def select_best_eligible_candidate(
    candidates: list[dict[str, Any]] | list[RankedCandidate],
    policy: SelectionPolicy,
    *,
    scanner_run_id: str | None = None,
    now: datetime | None = None,
    scanner_completed_at: datetime | None = None,
) -> SelectionDecision:
    """rank 순으로 평가. #1 HOLD면 #2 ALLOW 선택 가능. 전부 실패면 None."""

    now = now or datetime.now(timezone.utc)
    skip_trace: list[dict[str, Any]] = []

    # Scanner run 자체 staleness
    if (
        scanner_completed_at is not None
        and policy.max_candidate_age_seconds > 0
    ):
        age = (now - _aware(scanner_completed_at)).total_seconds()  # type: ignore[arg-type]
        if age > float(policy.max_candidate_age_seconds):
            return SelectionDecision(
                selected=None,
                reason="SCANNER_RESULT_STALE",
                skip_trace=[{"reason": "SCANNER_RESULT_STALE", "age_seconds": age}],
                scanner_run_id=scanner_run_id,
            )

    ranked: list[RankedCandidate] = []
    for idx, row in enumerate(candidates):
        if isinstance(row, RankedCandidate):
            ranked.append(row)
        else:
            ranked.append(
                candidate_from_scanner_row(
                    row, rank=row.get("rank") or row.get("scanner_rank") or (idx + 1)
                )
            )

    # rank 오름차순 (None은 맨 뒤)
    ranked.sort(
        key=lambda c: (c.rank is None, c.rank if c.rank is not None else 10**9)
    )

    for cand in ranked:
        ok, reason = evaluate_candidate_gates(cand, policy, now=now)
        skip_trace.append(
            {
                "symbol": cand.symbol,
                "rank": cand.rank,
                "recommendation": cand.recommendation,
                "ok": ok,
                "reason": reason,
            }
        )
        if ok:
            return SelectionDecision(
                selected=cand,
                reason=f"SELECTED_RANK_{cand.rank}",
                skip_trace=skip_trace,
                scanner_run_id=scanner_run_id,
            )

    return SelectionDecision(
        selected=None,
        reason="NO_ELIGIBLE_CANDIDATE",
        skip_trace=skip_trace,
        scanner_run_id=scanner_run_id,
    )
