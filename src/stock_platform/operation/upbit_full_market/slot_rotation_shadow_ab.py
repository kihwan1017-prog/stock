"""WAITING_SIGNAL slot rotation Shadow A/B — REAL 정책 미변경.

R0~R4 rotation 정책과 T10(10-slot)을 동일 scanner timeline에서 재현한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from stock_platform.operation.upbit_full_market.constants import (
    DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS,
    DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS,
    DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA,
)
from stock_platform.operation.upbit_full_market.slot_replacement import (
    CandidateScoreView,
    ReplacementPolicy,
    SlotScoreView,
    evaluate_slot_replacement,
    pick_best_replacement,
)

AgeBasis = Literal["updated_at", "selected_at"]

NOTIONAL_KRW = 10_000.0
FEE_RATE_ROUND_TRIP = 0.001  # 0.05% * 2 근사
WINNER_THRESHOLD_PCT = 1.0
LOSER_THRESHOLD_PCT = -1.0


@dataclass(frozen=True, slots=True)
class RotationPolicyVariant:
    """Shadow rotation 정책 변형."""

    code: str
    label: str
    max_slots: int = 5
    hold_seconds: float = float(DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS)
    max_wait_seconds: float = float(DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS)
    switch_min_score_delta: float = float(
        DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA
    )
    technical_block_min_evaluations: int = 20
    age_basis: AgeBasis = "updated_at"
    force_evict_on_max_wait: bool = False


R0_CURRENT = RotationPolicyVariant(
    code="R0",
    label="현행 Production",
)

R1_LOWER_DELTA = RotationPolicyVariant(
    code="R1",
    label="Delta 완화 (+5)",
    switch_min_score_delta=5.0,
)

R2_FORCE_MAX_WAIT = RotationPolicyVariant(
    code="R2",
    label="Max-wait 강제 해제",
    force_evict_on_max_wait=True,
)

R3_FAST_TECH_BLOCK = RotationPolicyVariant(
    code="R3",
    label="Selection-age + Tech-block 가속",
    age_basis="selected_at",
    technical_block_min_evaluations=5,
)

R4_COMBINED = RotationPolicyVariant(
    code="R4",
    label="R1+R2+R3 통합",
    switch_min_score_delta=5.0,
    force_evict_on_max_wait=True,
    age_basis="selected_at",
    technical_block_min_evaluations=5,
)

T10_BASELINE = RotationPolicyVariant(
    code="T10",
    label="10-slot 확대 (R0 동일)",
    max_slots=10,
)

ROTATION_VARIANTS: tuple[RotationPolicyVariant, ...] = (
    R0_CURRENT,
    R1_LOWER_DELTA,
    R2_FORCE_MAX_WAIT,
    R3_FAST_TECH_BLOCK,
    R4_COMBINED,
    T10_BASELINE,
)


@dataclass
class ShadowSlot:
    slot_no: int
    status: str  # EMPTY | WAITING_SIGNAL | OPEN
    symbol: str | None = None
    score: float = 0.0
    selected_at: datetime | None = None
    updated_at: datetime | None = None
    last_block_reason: str | None = None
    evaluation_count: int = 0
    last_decision: str | None = None
    entry_eligible: bool = False
    return_60m_pct: float | None = None


@dataclass
class ScannerRunRecord:
    run_id: str
    run_at: datetime
    candidates: list[dict[str, Any]]


@dataclass
class RotationSimMetrics:
    policy_code: str
    max_slots: int
    assignments: int = 0
    replacements: int = 0
    buy_eligible: int = 0
    missed_winners: int = 0
    avoided_losers: int = 0
    net_pnl_krw: float = 0.0
    gross_wins_krw: float = 0.0
    gross_losses_krw: float = 0.0
    fees_krw: float = 0.0
    profit_factor: float | None = None
    churn: int = 0
    waiting_seconds_samples: list[float] = field(default_factory=list)
    max_concurrent_exposure_krw: float = 0.0
    buy_symbols: list[str] = field(default_factory=list)
    replacement_pairs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        waits = self.waiting_seconds_samples
        pf = self.profit_factor
        if pf is None and self.gross_losses_krw < 0:
            pf = (
                self.gross_wins_krw / abs(self.gross_losses_krw)
                if self.gross_losses_krw
                else None
            )
        return {
            "policy_code": self.policy_code,
            "max_slots": self.max_slots,
            "assignments": self.assignments,
            "replacements": self.replacements,
            "buy_eligible": self.buy_eligible,
            "missed_winners": self.missed_winners,
            "avoided_losers": self.avoided_losers,
            "net_pnl_krw": round(self.net_pnl_krw, 2),
            "profit_factor": round(pf, 3) if pf is not None else None,
            "fees_krw": round(self.fees_krw, 2),
            "churn": self.churn,
            "waiting_avg_hours": round(
                (sum(waits) / len(waits) / 3600) if waits else 0.0, 2
            ),
            "waiting_max_hours": round(
                (max(waits) / 3600) if waits else 0.0, 2
            ),
            "max_concurrent_exposure_krw": round(
                self.max_concurrent_exposure_krw, 0
            ),
            "buy_symbols": self.buy_symbols,
            "replacement_count": len(self.replacement_pairs),
        }


def _utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slot_age_seconds(slot: ShadowSlot, *, now: datetime, age_basis: AgeBasis) -> float:
    ref = slot.updated_at if age_basis == "updated_at" else slot.selected_at
    if ref is None:
        return 0.0
    return max(0.0, (now - _utc(ref)).total_seconds())


def _to_replacement_policy(variant: RotationPolicyVariant) -> ReplacementPolicy:
    return ReplacementPolicy(
        hold_seconds=variant.hold_seconds,
        max_wait_seconds=variant.max_wait_seconds,
        switch_min_score_delta=variant.switch_min_score_delta,
        technical_block_min_evaluations=variant.technical_block_min_evaluations,
    )


def _shadow_to_slot_view(slot: ShadowSlot, *, age_basis: AgeBasis, now: datetime) -> SlotScoreView:
    age_ref = slot.updated_at if age_basis == "updated_at" else slot.selected_at
    return SlotScoreView(
        slot_id=slot.slot_no,
        slot_no=slot.slot_no,
        status=slot.status,
        symbol=str(slot.symbol or ""),
        score=float(slot.score),
        updated_at=age_ref,
        selected_at=slot.selected_at,
        reserved_amount_krw=0,
        entry_order_id=None,
        position_binding_id=None,
        last_block_reason=slot.last_block_reason,
        evaluation_count=slot.evaluation_count,
        last_decision=slot.last_decision,
    )


def _parse_entry_eligible(row: dict[str, Any]) -> bool:
    detail = row.get("evaluation_detail")
    if isinstance(detail, dict):
        entry_ab = detail.get("entry_ab")
        if isinstance(entry_ab, dict):
            baseline = entry_ab.get("baseline")
            if isinstance(baseline, dict) and baseline.get("eligible") is not None:
                return bool(baseline.get("eligible"))
    # fallback: ALLOW + technical snapshot from entry
    snap = row.get("entry_snapshot")
    if isinstance(snap, dict):
        rsi = snap.get("rsi14")
        if rsi is not None:
            try:
                return float(rsi) <= 70.0
            except (TypeError, ValueError):
                pass
    return str(row.get("recommendation", "")).upper() == "ALLOW"


def _return_pct(row: dict[str, Any]) -> float | None:
    raw = row.get("return_60m_pct")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def explain_re_stale_occupancy() -> dict[str, Any]:
    """RE 55h 점유 — 코드/정책 root cause (DB 이벤트는 runner에서 보강)."""

    return {
        "symptom": "KRW-RE WAITING_SIGNAL 55h+ despite max_wait=3h",
        "root_causes": [
            {
                "id": "MAX_WAIT_NOT_UNCONDITIONAL",
                "detail": (
                    "evaluate_slot_replacement path C (REASON_MAX_WAIT) requires "
                    "age >= max_wait AND new_score > old_score — max_wait alone does not evict"
                ),
                "file": "slot_replacement.py:285-298",
            },
            {
                "id": "HIGH_SCORE_TRAP",
                "detail": (
                    "RE score 88.48 — SCORE_IMPROVEMENT needs delta>=8 (96.48+); "
                    "few scanner candidates exceed RE score"
                ),
            },
            {
                "id": "REPLACEMENT_ONLY_ON_FULL",
                "detail": (
                    "_try_replace_waiting_signal runs only when consume_top_k finds "
                    "zero EMPTY slots — if any EMPTY exists, waiting slots persist"
                ),
                "file": "portfolio_service.py:1255-1265",
            },
            {
                "id": "AGE_BASIS_UPDATED_AT",
                "detail": (
                    "slot age for replacement uses updated_at; RE updated_at frozen "
                    "since 2026-08-21 assignment — age correctly exceeds max_wait"
                ),
            },
            {
                "id": "TECH_BLOCK_REQUIRES_BETTER_SCORE",
                "detail": (
                    "REASON_TECHNICAL_BLOCK_LONG also requires new_score > old_score "
                    "even after 20+ BLOCK evaluations"
                ),
                "file": "slot_replacement.py:300-321",
            },
        ],
        "verdict": "DESIGN_GAP_NOT_BUG — max_wait is a replacement gate, not TTL eviction",
    }


def _pick_force_evict_slot(
    slots: list[ShadowSlot],
    *,
    now: datetime,
    variant: RotationPolicyVariant,
) -> ShadowSlot | None:
    """max_wait 초과 WAITING 중 가장 약한 slot 강제 해제."""

    waiting = [
        s
        for s in slots
        if s.status == "WAITING_SIGNAL"
        and _slot_age_seconds(s, now=now, age_basis=variant.age_basis)
        >= variant.max_wait_seconds
    ]
    if not waiting:
        return None
    return min(waiting, key=lambda s: (s.score, s.slot_no))


def simulate_rotation_policy(
    *,
    variant: RotationPolicyVariant,
    runs: list[ScannerRunRecord],
    initial_slots: list[ShadowSlot] | None = None,
    candidate_rows: dict[str, dict[str, Any]] | None = None,
) -> RotationSimMetrics:
    """Scanner timeline shadow replay."""

    metrics = RotationSimMetrics(
        policy_code=variant.code, max_slots=variant.max_slots
    )
    pol = _to_replacement_policy(variant)
    rows = candidate_rows or {}

    slots: list[ShadowSlot] = []
    if initial_slots:
        slots = [deepcopy(s) for s in initial_slots]
    while len(slots) < variant.max_slots:
        slots.append(
            ShadowSlot(
                slot_no=len(slots) + 1,
                status="EMPTY",
            )
        )
    slots = slots[: variant.max_slots]

    assigned_symbols: set[str] = set()
    for s in slots:
        if s.symbol and s.status != "EMPTY":
            assigned_symbols.add(s.symbol.upper())

    def _update_exposure() -> None:
        open_like = sum(
            1 for s in slots if s.status in ("WAITING_SIGNAL", "OPEN")
        )
        exp = open_like * NOTIONAL_KRW
        metrics.max_concurrent_exposure_krw = max(
            metrics.max_concurrent_exposure_krw, exp
        )

    def _record_buy(row: dict[str, Any], sym: str) -> None:
        ret = _return_pct(row)
        if not _parse_entry_eligible(row):
            return
        metrics.buy_eligible += 1
        metrics.buy_symbols.append(sym)
        if ret is None:
            return
        gross = NOTIONAL_KRW * ret / 100.0
        fee = NOTIONAL_KRW * FEE_RATE_ROUND_TRIP
        net = gross - fee
        metrics.fees_krw += fee
        metrics.net_pnl_krw += net
        if gross > 0:
            metrics.gross_wins_krw += gross
        elif gross < 0:
            metrics.gross_losses_krw += gross

    for run in runs:
        now = _utc(run.run_at)
        allow = sorted(
            [
                c
                for c in run.candidates
                if str(c.get("recommendation", "")).upper() == "ALLOW"
            ],
            key=lambda c: (-float(c.get("scanner_score") or c.get("score") or 0), str(c.get("symbol"))),
        )
        if not allow:
            continue

        cand_views = [
            CandidateScoreView(
                symbol=str(c.get("symbol", "")).upper(),
                score=float(c.get("scanner_score") or c.get("score") or 0),
                recommendation="ALLOW",
                rank=c.get("scanner_rank"),
            )
            for c in allow
        ]

        for cand in cand_views:
            sym = cand.symbol
            if sym in assigned_symbols:
                continue
            empty = next((s for s in slots if s.status == "EMPTY"), None)
            if empty is None:
                break
            row = rows.get(sym, {})
            empty.status = "WAITING_SIGNAL"
            empty.symbol = sym
            empty.score = cand.score
            empty.selected_at = now
            empty.updated_at = now
            empty.return_60m_pct = _return_pct(row)
            empty.entry_eligible = _parse_entry_eligible(row)
            assigned_symbols.add(sym)
            metrics.assignments += 1
            _record_buy(row, sym)

        # 슬롯 full 시 미배정 고점수 후보 winner/loser 추적
        non_empty = sum(1 for s in slots if s.status != "EMPTY")
        if non_empty >= variant.max_slots:
            for c in allow:
                sym = str(c.get("symbol", "")).upper()
                if sym in assigned_symbols:
                    continue
                ret = _return_pct(c)
                if ret is not None and ret >= WINNER_THRESHOLD_PCT:
                    metrics.missed_winners += 1
                if ret is not None and ret <= LOSER_THRESHOLD_PCT:
                    metrics.avoided_losers += 1

        # 교체 시도 (cycle당 1건)
        waiting_views = [
            _shadow_to_slot_view(s, age_basis=variant.age_basis, now=now)
            for s in slots
            if s.status == "WAITING_SIGNAL"
        ]
        if not waiting_views:
            _update_exposure()
            continue

        decision = pick_best_replacement(
            slots=waiting_views,
            candidates=[c for c in cand_views if c.symbol not in assigned_symbols],
            policy=pol,
            now=now,
        )

        if not decision.replace and variant.force_evict_on_max_wait:
            victim = _pick_force_evict_slot(slots, now=now, variant=variant)
            best_new = next(
                (c for c in cand_views if c.symbol not in assigned_symbols),
                None,
            )
            if victim is not None and best_new is not None:
                decision = replace(
                    decision,
                    replace=True,
                    reason="FORCE_MAX_WAIT",
                    slot_id=victim.slot_no,
                    slot_no=victim.slot_no,
                    old_symbol=victim.symbol,
                    new_symbol=best_new.symbol,
                    old_score=victim.score,
                    new_score=best_new.score,
                )

        if decision.replace and decision.slot_no:
            slot = next((s for s in slots if s.slot_no == decision.slot_no), None)
            if slot and decision.new_symbol:
                old_sym = slot.symbol
                if old_sym:
                    assigned_symbols.discard(old_sym.upper())
                    if slot.selected_at:
                        metrics.waiting_seconds_samples.append(
                            (now - _utc(slot.selected_at)).total_seconds()
                        )
                new_sym = str(decision.new_symbol).upper()
                row = rows.get(new_sym, {})
                slot.symbol = new_sym
                slot.score = float(decision.new_score or 0)
                slot.selected_at = now
                slot.updated_at = now
                slot.return_60m_pct = _return_pct(row)
                slot.entry_eligible = _parse_entry_eligible(row)
                assigned_symbols.add(new_sym)
                metrics.replacements += 1
                metrics.churn += 1
                metrics.replacement_pairs.append(
                    {
                        "at": now.isoformat(),
                        "old": old_sym,
                        "new": new_sym,
                        "reason": decision.reason,
                    }
                )
                _record_buy(row, new_sym)

        _update_exposure()

    # 종료 시 WAITING 잔여 시간
    end = _utc(runs[-1].run_at) if runs else datetime.now(timezone.utc)
    for s in slots:
        if s.status == "WAITING_SIGNAL" and s.selected_at:
            metrics.waiting_seconds_samples.append(
                (end - _utc(s.selected_at)).total_seconds()
            )

    if metrics.gross_losses_krw < 0:
        metrics.profit_factor = metrics.gross_wins_krw / abs(metrics.gross_losses_krw)
    return metrics


def pick_study_verdict(
    results: dict[str, RotationSimMetrics],
    *,
    cohort: str,
    sample_count: int,
    min_sample: int = 15,
) -> str:
    """KEEP_5_SLOT | IMPROVE_ROTATION | TEST_10_SLOT | INSUFFICIENT_SAMPLE."""

    if sample_count < min_sample:
        return "INSUFFICIENT_SAMPLE"

    r0 = results.get("R0")
    r4 = results.get("R4")
    t10 = results.get("T10")
    if r0 is None:
        return "INSUFFICIENT_SAMPLE"

    r0_pnl = r0.net_pnl_krw
    best_rot = max(
        (m for code, m in results.items() if code.startswith("R")),
        key=lambda m: m.net_pnl_krw,
        default=r0,
    )
    t10_pnl = t10.net_pnl_krw if t10 else r0_pnl

    # 10-slot이 rotation 개선보다 유의미하게 좋고 exposure 증가 감수 가능
    if t10 and t10.buy_eligible > r0.buy_eligible + 2 and t10_pnl > r0_pnl + 50:
        return "TEST_10_SLOT"

    # R4 등 rotation 개선이 R0 대비 PnL/churn 개선
    if (
        best_rot.policy_code != "R0"
        and best_rot.net_pnl_krw > r0_pnl + 20
        and best_rot.missed_winners <= r0.missed_winners
    ):
        return "IMPROVE_ROTATION"

    if best_rot.policy_code == "R0" or abs(best_rot.net_pnl_krw - r0_pnl) < 20:
        return "KEEP_5_SLOT"

    return "KEEP_5_SLOT"
