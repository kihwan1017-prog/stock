"""WAITING_SIGNAL slot 안전 교체 정책 (주문 없음).

EMPTY-only consume 한계를 보완한다.
ENTRY_PENDING / OPEN / reserved>0 은 절대 교체하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from stock_platform.operation.upbit_full_market.constants import (
    DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS,
    DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA,
    SLOT_ENTRY_PENDING,
    SLOT_EXIT_PENDING,
    SLOT_OPEN,
    SLOT_WAITING_SIGNAL,
)

# 최대 WAITING_SIGNAL 유지 (기본 3시간) — hold(30분) 이후 stale/장기 대기에 사용
DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS = 10800.0

REASON_SCORE_IMPROVEMENT = "SCORE_IMPROVEMENT"
REASON_MAX_WAIT = "MAX_WAIT"
REASON_STALE_CANDIDATE = "STALE_CANDIDATE"
REASON_TECHNICAL_BLOCK_LONG = "TECHNICAL_BLOCK_LONG"
REASON_SOFT_STALE_NO_SIGNAL = "SOFT_STALE_NO_ENTRY_SIGNAL"

PROTECTED_STATUSES = frozenset(
    {SLOT_ENTRY_PENDING, SLOT_OPEN, SLOT_EXIT_PENDING}
)

PERSISTENT_BLOCK_REASONS = frozenset(
    {
        "SHORT_MA_NOT_ABOVE_LONG_MA",
        "MA_SEPARATION_TOO_SMALL",
        "RSI_TOO_HIGH",
        "VOLUME_SURGE_TOO_LOW",
        "CANDIDATE_STALE",
        "FEED_STALE",
        "AI_SELECTION_NOT_ALLOW",
    }
)


@dataclass(frozen=True, slots=True)
class ReplacementPolicy:
    """hold / max_wait / score delta — settings·policy JSON에서 합성."""

    hold_seconds: float = float(DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS)
    max_wait_seconds: float = DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS
    switch_min_score_delta: float = float(
        DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA
    )
    candidate_max_age_seconds: float = 1800.0
    soft_stale_seconds: float = 1800.0
    # telemetry 기반 장기 BLOCK — hold 이후 + 최소 평가 횟수
    technical_block_min_evaluations: int = 20


@dataclass(frozen=True, slots=True)
class SlotScoreView:
    """교체 판정용 slot 스냅샷 (DB entity와 분리)."""

    slot_id: int
    slot_no: int
    status: str
    symbol: str
    score: float
    updated_at: datetime | None
    selected_at: datetime | None
    reserved_amount_krw: float | None
    entry_order_id: int | None
    position_binding_id: int | None
    has_open_order: bool = False
    last_block_reason: str | None = None
    evaluation_count: int = 0
    last_decision: str | None = None
    soft_stale_eligible: bool = False


@dataclass(frozen=True, slots=True)
class CandidateScoreView:
    symbol: str
    score: float
    recommendation: str
    rank: int | None = None
    confidence: float | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReplacementDecision:
    replace: bool
    reason: str | None = None
    slot_id: int | None = None
    slot_no: int | None = None
    old_symbol: str | None = None
    new_symbol: str | None = None
    old_score: float | None = None
    new_score: float | None = None
    age_seconds: float | None = None
    detail: dict[str, Any] | None = None


def _as_utc(value: datetime | None, now: datetime) -> datetime:
    if value is None:
        return now
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def load_replacement_policy(
    *,
    settings: Any,
    risk_group_policy_json: dict[str, Any] | None,
    candidate_max_age_seconds: float | int | None = None,
) -> ReplacementPolicy:
    """settings 기본값 + policy.risk_group_policy_json 오버라이드."""

    blob = dict(risk_group_policy_json or {})

    def _f(key: str, settings_attr: str, default: float) -> float:
        if key in blob and blob[key] is not None:
            try:
                return float(blob[key])
            except (TypeError, ValueError):
                pass
        raw = getattr(settings, settings_attr, None)
        try:
            return float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    hold = _f(
        "candidate_hold_seconds",
        "upbit_portfolio_candidate_hold_seconds",
        DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS,
    )
    max_wait = _f(
        "candidate_max_wait_seconds",
        "upbit_portfolio_candidate_max_wait_seconds",
        DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS,
    )
    delta = _f(
        "candidate_switch_min_score_delta",
        "upbit_portfolio_candidate_switch_min_score_delta",
        DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA,
    )
    age = (
        float(candidate_max_age_seconds)
        if candidate_max_age_seconds is not None
        else _f(
            "candidate_max_age_seconds",
            "upbit_portfolio_candidate_max_age_seconds",
            1800.0,
        )
    )
    # max_wait는 hold보다 짧을 수 없음
    max_wait = max(max_wait, hold)
    soft_stale = _f(
        "waiting_soft_stale_seconds",
        "upbit_waiting_soft_stale_seconds",
        1800.0,
    )
    soft_stale = min(soft_stale, max_wait)
    return ReplacementPolicy(
        hold_seconds=max(0.0, hold),
        max_wait_seconds=max(0.0, max_wait),
        switch_min_score_delta=max(0.0, delta),
        candidate_max_age_seconds=max(60.0, age),
        soft_stale_seconds=max(60.0, soft_stale),
    )


def is_slot_structurally_replaceable(slot: SlotScoreView) -> tuple[bool, str | None]:
    """구조적 교체 가능 여부 (시간·점수 제외)."""

    status = str(slot.status or "").upper()
    if status in PROTECTED_STATUSES:
        return False, f"PROTECTED_STATUS_{status}"
    if status != SLOT_WAITING_SIGNAL:
        return False, f"STATUS_NOT_WAITING_SIGNAL:{status}"
    reserved = float(slot.reserved_amount_krw or 0)
    if reserved > 0:
        return False, "RESERVED_POSITIVE"
    if slot.entry_order_id is not None:
        return False, "HAS_ENTRY_ORDER"
    if slot.position_binding_id is not None:
        return False, "HAS_POSITION_BINDING"
    if slot.has_open_order:
        return False, "HAS_OPEN_ORDER"
    if not str(slot.symbol or "").strip():
        return False, "NO_SYMBOL"
    return True, None


def slot_age_seconds(slot: SlotScoreView, *, now: datetime) -> float:
    updated = _as_utc(slot.updated_at, now)
    return max(0.0, (now - updated).total_seconds())


def selection_age_seconds(slot: SlotScoreView, *, now: datetime) -> float | None:
    if slot.selected_at is None:
        return None
    selected = _as_utc(slot.selected_at, now)
    return max(0.0, (now - selected).total_seconds())


def evaluate_slot_replacement(
    *,
    slot: SlotScoreView,
    candidate: CandidateScoreView,
    policy: ReplacementPolicy,
    now: datetime | None = None,
) -> ReplacementDecision:
    """단일 slot↔candidate 교체 가능 여부."""

    now = now or datetime.now(timezone.utc)
    ok, block = is_slot_structurally_replaceable(slot)
    if not ok:
        return ReplacementDecision(replace=False, reason=block)

    age = slot_age_seconds(slot, now=now)
    sel_age = selection_age_seconds(slot, now=now)
    new_score = float(candidate.score)
    old_score = float(slot.score)
    delta = new_score - old_score
    base_detail: dict[str, Any] = {
        "age_seconds": age,
        "selection_age_seconds": sel_age,
        "hold_seconds": policy.hold_seconds,
        "max_wait_seconds": policy.max_wait_seconds,
        "min_score_delta": policy.switch_min_score_delta,
        "score_delta": delta,
        "old_score": old_score,
        "new_score": new_score,
        "last_block_reason": slot.last_block_reason,
        "evaluation_count": slot.evaluation_count,
    }

    # 최소 보호시간 — 점수 개선이어도 hold 이전이면 금지
    if age < policy.hold_seconds:
        return ReplacementDecision(
            replace=False,
            reason="WITHIN_HOLD",
            slot_id=slot.slot_id,
            slot_no=slot.slot_no,
            old_symbol=slot.symbol,
            new_symbol=candidate.symbol,
            old_score=old_score,
            new_score=new_score,
            age_seconds=age,
            detail=base_detail,
        )

    # A0) soft stale — entry signal 없음 + hold 경과 → 더 좋은 후보로 교체
    if (
        slot.soft_stale_eligible
        and age >= policy.soft_stale_seconds
        and str(slot.last_decision or "").upper() not in {"BUY", "TECHNICAL_PASS"}
        and new_score > old_score
    ):
        return ReplacementDecision(
            replace=True,
            reason=REASON_SOFT_STALE_NO_SIGNAL,
            slot_id=slot.slot_id,
            slot_no=slot.slot_no,
            old_symbol=slot.symbol,
            new_symbol=candidate.symbol,
            old_score=old_score,
            new_score=new_score,
            age_seconds=age,
            detail={**base_detail, "path": REASON_SOFT_STALE_NO_SIGNAL},
        )

    # A) 점수 개선 교체 (hold 이후)
    if delta >= policy.switch_min_score_delta:
        return ReplacementDecision(
            replace=True,
            reason=REASON_SCORE_IMPROVEMENT,
            slot_id=slot.slot_id,
            slot_no=slot.slot_no,
            old_symbol=slot.symbol,
            new_symbol=candidate.symbol,
            old_score=old_score,
            new_score=new_score,
            age_seconds=age,
            detail={**base_detail, "path": REASON_SCORE_IMPROVEMENT},
        )

    # B) 후보 freshness stale — max_wait 이후에만 (30분 age만으로 교체 churn 금지)
    if (
        age >= policy.max_wait_seconds
        and sel_age is not None
        and sel_age > policy.candidate_max_age_seconds
        and new_score > old_score
    ):
        return ReplacementDecision(
            replace=True,
            reason=REASON_STALE_CANDIDATE,
            slot_id=slot.slot_id,
            slot_no=slot.slot_no,
            old_symbol=slot.symbol,
            new_symbol=candidate.symbol,
            old_score=old_score,
            new_score=new_score,
            age_seconds=age,
            detail={**base_detail, "path": REASON_STALE_CANDIDATE},
        )

    # C) 최대 대기 — 더 좋은 eligible 후보로 교체
    if age >= policy.max_wait_seconds and new_score > old_score:
        return ReplacementDecision(
            replace=True,
            reason=REASON_MAX_WAIT,
            slot_id=slot.slot_id,
            slot_no=slot.slot_no,
            old_symbol=slot.symbol,
            new_symbol=candidate.symbol,
            old_score=old_score,
            new_score=new_score,
            age_seconds=age,
            detail={**base_detail, "path": REASON_MAX_WAIT},
        )

    # D) telemetry 장기 technical block (DB write 없음 — 읽기 전용)
    block_reason = str(slot.last_block_reason or "").upper()
    if (
        age >= policy.max_wait_seconds
        and str(slot.last_decision or "").upper() == "BLOCK"
        and block_reason in PERSISTENT_BLOCK_REASONS
        and int(slot.evaluation_count or 0)
        >= int(policy.technical_block_min_evaluations)
        and new_score > old_score
    ):
        return ReplacementDecision(
            replace=True,
            reason=REASON_TECHNICAL_BLOCK_LONG,
            slot_id=slot.slot_id,
            slot_no=slot.slot_no,
            old_symbol=slot.symbol,
            new_symbol=candidate.symbol,
            old_score=old_score,
            new_score=new_score,
            age_seconds=age,
            detail={**base_detail, "path": REASON_TECHNICAL_BLOCK_LONG},
        )

    return ReplacementDecision(
        replace=False,
        reason="DELTA_OR_WAIT_INSUFFICIENT",
        slot_id=slot.slot_id,
        slot_no=slot.slot_no,
        old_symbol=slot.symbol,
        new_symbol=candidate.symbol,
        old_score=old_score,
        new_score=new_score,
        age_seconds=age,
        detail=base_detail,
    )


def pick_best_replacement(
    *,
    slots: list[SlotScoreView],
    candidates: list[CandidateScoreView],
    policy: ReplacementPolicy,
    now: datetime | None = None,
    protected_symbols: set[str] | None = None,
) -> ReplacementDecision:
    """scanner cycle당 최대 1건 — 약한 slot × 강한 신규 후보.

    churn 방지: 호출측에서 교체 후 hold timer 재시작 + cycle당 1회만 호출.
    """

    now = now or datetime.now(timezone.utc)
    protected = {str(s).upper() for s in (protected_symbols or set())}

    replaceable: list[SlotScoreView] = []
    for slot in slots:
        ok, _ = is_slot_structurally_replaceable(slot)
        if ok:
            replaceable.append(slot)
    if not replaceable or not candidates:
        return ReplacementDecision(replace=False, reason="NO_REPLACEABLE_OR_CANDIDATE")

    # 약한(낮은 점수) slot 우선, 강한 신규 후보 우선
    replaceable_sorted = sorted(replaceable, key=lambda s: (s.score, s.slot_no))
    candidates_sorted = sorted(
        candidates, key=lambda c: (-c.score, c.rank if c.rank is not None else 99)
    )

    last_reject: ReplacementDecision | None = None
    for cand in candidates_sorted:
        sym = str(cand.symbol or "").upper()
        if not sym or sym in protected:
            continue
        for slot in replaceable_sorted:
            # 동일 심볼 자가교체 금지 (churn)
            if sym == str(slot.symbol or "").upper():
                continue
            # 다른 WAITING slot에 이미 있는 심볼은 중복 배정 금지
            other_syms = {
                s.symbol
                for s in replaceable_sorted
                if s.slot_id != slot.slot_id and s.symbol
            }
            if sym in other_syms:
                continue
            decision = evaluate_slot_replacement(
                slot=slot, candidate=cand, policy=policy, now=now
            )
            if decision.replace:
                return decision
            last_reject = decision

    if last_reject is not None:
        return last_reject
    return ReplacementDecision(replace=False, reason="NO_MATCH")


def reason_ko(reason: str | None) -> str:
    mapping = {
        REASON_SCORE_IMPROVEMENT: "더 높은 우선순위 후보",
        REASON_MAX_WAIT: "매수 조건 장시간 미충족",
        REASON_STALE_CANDIDATE: "후보 신선도 만료",
        REASON_TECHNICAL_BLOCK_LONG: "기술적 진입 조건 장시간 미충족",
        REASON_SOFT_STALE_NO_SIGNAL: "매수 신호 없음 soft stale",
    }
    return mapping.get(str(reason or ""), str(reason or "후보 교체"))
