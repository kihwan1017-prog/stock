"""STEP 12-2-3 — Strategy Draft Version/Revision 비교(Diff) 유틸리티.

기존 비교 관련 코드(`backtest/comparison_service.py` — 백테스트 성과
랭킹, `ai/reproducibility.py` — AI 재현 실행 간 순위·점수 비교)를
조사했으나 둘 다 이 도메인(자유 텍스트/JSON 혼재 필드의 added/removed/
changed/unchanged 판정)과 무관해 재사용하지 못했다. 이 모듈이 그 유일한
필드 단위 구조화 diff 구현이다.
"""

from __future__ import annotations

import json
from typing import Any

# ai.strategy_draft 테이블에 실제로 저장되는 필드만 비교 대상으로 삼는다.
COMPARABLE_FIELDS = (
    "title",
    "summary",
    "timeframe",
    "market_type",
    "entry_rule",
    "exit_rule",
    "stop_loss_rule",
    "take_profit_rule",
    "position_sizing_rule",
    "risk_parameters",
    "indicator_configuration",
)

# Draft 테이블 자체에는 없고, AI 생성 시 Generation Attempt의
# structured_response에만 존재하는 필드(STEP12-2-1 스키마 설계상 별도
# 컬럼이 없음) — 두 Draft 모두 AI 생성본일 때만 채워진다.
ATTEMPT_ONLY_FIELDS = ("symbols", "warnings", "assumptions", "confidence")


def _try_parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _normalize(value: Any) -> Any:
    """배열은 순서 무관 비교를 위해 정규화 정렬한다."""
    parsed = _try_parse_json(value)
    if isinstance(parsed, list):
        try:
            return sorted(
                parsed, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)
            )
        except TypeError:
            return parsed
    return parsed


def _field_status(before: Any, after: Any) -> str:
    if before is None and after is None:
        return "unchanged"
    if before is None:
        return "added"
    if after is None:
        return "removed"
    return "unchanged" if _normalize(before) == _normalize(after) else "changed"


def compare_drafts(
    draft_a: dict[str, Any],
    draft_b: dict[str, Any],
    *,
    attempt_a: dict[str, Any] | None = None,
    attempt_b: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """draft_a(기준) vs draft_b(대상)의 필드 단위 diff.

    배열 순서만 바뀐 경우는 unchanged로 판정하고, 실제 항목이 달라진
    경우만 changed로 표시한다.
    """
    fields: dict[str, dict[str, Any]] = {}
    for name in COMPARABLE_FIELDS:
        before = draft_a.get(name)
        after = draft_b.get(name)
        fields[name] = {
            "status": _field_status(before, after),
            "before": before,
            "after": after,
        }

    response_a = (attempt_a or {}).get("structured_response") or {}
    response_b = (attempt_b or {}).get("structured_response") or {}
    for name in ATTEMPT_ONLY_FIELDS:
        before = response_a.get(name)
        after = response_b.get(name)
        fields[name] = {
            "status": _field_status(before, after),
            "before": before,
            "after": after,
        }

    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for entry in fields.values():
        counts[entry["status"]] += 1

    return {
        "draft_a_id": draft_a.get("draft_id"),
        "draft_b_id": draft_b.get("draft_id"),
        "fields": fields,
        "summary": counts,
    }
