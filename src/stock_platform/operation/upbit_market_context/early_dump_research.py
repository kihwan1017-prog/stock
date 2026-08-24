"""Early-dump research design — technical vs technical+LLM context.

CLEAN Forward only. REAL promotion 자동 금지.
"""

from __future__ import annotations

from typing import Any, Sequence

from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    ForwardObs,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    REAL_14_REFERENCE,
    evaluate_filter_arm,
)
from stock_platform.operation.upbit_market_context.schemas import LlmContextOutput


def llm_quality_accept(
    out: LlmContextOutput | None,
    *,
    min_score: int = 55,
    reject_flags: frozenset[str] | None = None,
) -> bool:
    """Entry filter candidate: LLM quality gate (research thresholds — not REAL)."""

    reject_flags = reject_flags or frozenset(
        {"RECENT_SPIKE", "OVERHEATED", "SELL_PRESSURE", "NEWS_NEGATIVE"}
    )
    if out is None:
        return True  # fail-open research
    if any(f in reject_flags for f in out.risk_flags):
        return False
    if out.recommendation == "REDUCE":
        return False
    if out.context_unavailable:
        return True  # missing context — do not block
    if out.entry_quality_score < min_score:
        return False
    return True


def early_dump_research_design() -> dict[str, Any]:
    return {
        "question": (
            "Can LLM context score separate EARLY_DUMP candidates before entry "
            "on CLEAN Forward?"
        ),
        "baseline": "CURRENT technical entry (E0 REAL entry gates)",
        "candidate": "technical entry + market/news/context LLM quality filter",
        "metrics": [
            "accepted",
            "filtered",
            "avoided_losers",
            "missed_winners",
            "net_filter_benefit",
            "early_dump_rate",
            "PF",
            "Net",
        ],
        "sample_gates": {
            "N<100": "COLLECTION_ONLY",
            "N>=100": "DIAGNOSTIC_ONLY",
            "N>=500": "PRIMARY_REVIEW",
            "N>=1000": "RECOMMENDED_REVIEW",
        },
        "no_lookahead": "context_as_of <= detected_at required on every row",
        "legacy_excluded": True,
        "real_promotion_auto": False,
        "REAL_14_REFERENCE": REAL_14_REFERENCE,
    }


def compare_technical_vs_llm_filter(
    baseline_accepted: Sequence[ForwardObs],
    llm_outputs_by_shadow_id: dict[int, LlmContextOutput],
) -> dict[str, Any]:
    """동일 CLEAN baseline 집합에서 LLM filter arm 비교."""

    def _accept(o: ForwardObs) -> bool:
        return llm_quality_accept(llm_outputs_by_shadow_id.get(o.shadow_id))

    arm = evaluate_filter_arm(
        list(baseline_accepted),
        code="LLM_CTX",
        name_ko="기술+LLM 컨텍스트",
        accept_fn=_accept,
    )
    return {
        "design": early_dump_research_design(),
        "llm_filter_arm": arm,
        "coverage": {
            "baseline_n": len(baseline_accepted),
            "llm_labeled": sum(
                1 for o in baseline_accepted if o.shadow_id in llm_outputs_by_shadow_id
            ),
        },
        "REAL_PROMOTION_RECOMMENDED": "NO",
        "note": "Heuristic/LLM labels research-only until CLEAN N>=500",
    }
