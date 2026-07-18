from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def build_context_hash(
    *,
    source_candidate_run_id: int,
    model_name: str,
    prompt_version: str,
    requested_limit: int,
    contexts: dict[str, Any],
) -> str:
    """동일 입력 재현을 위한 정규화 해시."""
    payload = {
        "source_candidate_run_id": source_candidate_run_id,
        "model_name": model_name,
        "prompt_version": prompt_version,
        "requested_limit": requested_limit,
        "contexts": contexts,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compare_analysis_results(
    *,
    baseline: list[dict[str, Any]],
    reproduced: list[dict[str, Any]],
) -> dict[str, Any]:
    """두 AI 실행 결과의 순위·점수 차이를 요약한다."""
    baseline_by_symbol = {
        item["symbol"]: item for item in baseline
    }
    reproduced_by_symbol = {
        item["symbol"]: item for item in reproduced
    }

    baseline_symbols = set(baseline_by_symbol)
    reproduced_symbols = set(reproduced_by_symbol)

    added = sorted(reproduced_symbols - baseline_symbols)
    removed = sorted(baseline_symbols - reproduced_symbols)

    score_changed: list[dict[str, Any]] = []
    rank_changed: list[dict[str, Any]] = []
    action_changed: list[dict[str, Any]] = []

    for symbol in sorted(baseline_symbols & reproduced_symbols):
        left = baseline_by_symbol[symbol]
        right = reproduced_by_symbol[symbol]
        if Decimal(str(left["ai_score"])) != Decimal(
            str(right["ai_score"])
        ):
            score_changed.append(
                {
                    "symbol": symbol,
                    "baseline_ai_score": left["ai_score"],
                    "reproduced_ai_score": right["ai_score"],
                }
            )
        if left["rank"] != right["rank"]:
            rank_changed.append(
                {
                    "symbol": symbol,
                    "baseline_rank": left["rank"],
                    "reproduced_rank": right["rank"],
                }
            )
        if left.get("action") != right.get("action"):
            action_changed.append(
                {
                    "symbol": symbol,
                    "baseline_action": left.get("action"),
                    "reproduced_action": right.get("action"),
                }
            )

    identical = (
        not added
        and not removed
        and not score_changed
        and not rank_changed
        and not action_changed
    )
    return {
        "identical": identical,
        "added_symbols": added,
        "removed_symbols": removed,
        "score_changed": score_changed,
        "rank_changed": rank_changed,
        "action_changed": action_changed,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")
