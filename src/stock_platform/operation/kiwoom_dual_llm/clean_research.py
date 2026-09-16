"""KIWOOM CLEAN research cohort — separate from UPBIT CLEAN."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM, normalize_market
from stock_platform.operation.upbit_market_context.learning_dataset import sample_stage


def classify_kiwoom_research_row(
    *,
    input_json: dict[str, Any] | None,
    output_json: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prediction/outcome row → CLEAN / EXCLUDED. 강제 CLEAN 승격 금지."""

    inp = input_json if isinstance(input_json, dict) else {}
    out = output_json if isinstance(output_json, dict) else {}
    market = normalize_market(inp.get("market") or out.get("market"))
    exclusions: list[str] = []
    reasons: list[str] = []

    if market != MARKET_KIWOOM:
        return {
            "market": market,
            "clean": False,
            "cohort": "EXCLUDED",
            "exclusions": ["NOT_KIWOOM"],
            "reasons": [],
        }

    prov = inp.get("provenance") if isinstance(inp.get("provenance"), dict) else {}
    if prov.get("forced") or prov.get("synthetic"):
        exclusions.append("FORCED_OR_SYNTHETIC")
    if prov.get("imported_position"):
        exclusions.append("IMPORTED_POSITION")
    if prov.get("backfill") or out.get("research_stamp_backfill"):
        exclusions.append("BACKFILL")
    if inp.get("lookahead_ok") is False or out.get("lookahead_ok") is False:
        exclusions.append("LOOKAHEAD")

    # 자연 MA entry만 기본 CLEAN 후보
    source = str(prov.get("source") or "")
    if source and source not in {
        "MA_ENTRY_EVALUATION",
        "MA_GOLDEN_CROSS",
        "NATURAL_RUNTIME",
    }:
        # 명시 source가 이상한 경우만 제외 — 빈 source는 보수적 EXCLUDED
        if source.upper().startswith("TEST") or "FORCE" in source.upper():
            exclusions.append("NON_NATURAL_SOURCE")

    if not prov.get("signal_id") and not prov.get("fingerprint"):
        exclusions.append("MISSING_PROVENANCE")

    # canonical price
    if not (inp.get("reference_price") or (inp.get("asset_context") or {}).get("price")):
        exclusions.append("INVALID_PRICE_SOURCE")

    fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
    outcome = fb.get("actual_outcome") if isinstance(fb.get("actual_outcome"), dict) else {}
    outcome_status = str(outcome.get("status") or out.get("outcome_status") or "")
    if outcome_status == "TRUNCATED_BY_MARKET_CLOSE":
        reasons.append("TRUNCATED_BY_MARKET_CLOSE")
    if outcome.get("label") == "INSUFFICIENT_DATA":
        exclusions.append("INSUFFICIENT_OUTCOME")

    clean = not exclusions
    return {
        "market": MARKET_KIWOOM,
        "clean": clean,
        "cohort": "CLEAN_FORWARD" if clean else "EXCLUDED",
        "exclusions": exclusions,
        "reasons": reasons or (["CANONICAL_KIWOOM_NATURAL"] if clean else []),
        "promotion_eligible": clean,
    }


def kiwoom_sample_stage(clean_n: int) -> dict[str, Any]:
    """UPBIT count와 합산 금지 — market 분리 stage."""

    st = sample_stage(clean_n)
    return {
        **st,
        "market": MARKET_KIWOOM,
        "note": "UPBIT CLEAN과 합산 승격 금지",
    }
