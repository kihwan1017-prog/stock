"""STEP 11-10 — Provider 독립성 분류."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.candidate_consensus.constants import (
    INDEPENDENCE_STATUS,
    PROVIDER_FAMILY_MAP,
)


def _provider_family(provider_code: str | None) -> str:
    code = (provider_code or "unknown").lower().strip()
    return PROVIDER_FAMILY_MAP.get(code, code or "unknown")


class AIConsensusIndependenceService:
    """멤버 간 provider/model 독립성 판정."""

    def classify(self, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for member in members:
            provider = (member.get("provider_code") or "unknown").lower()
            model = (member.get("model") or "default").lower()
            family = _provider_family(provider)
            enriched.append(
                {
                    **member,
                    "provider_family": family,
                    "provider_key": f"{provider}:{model}",
                    "family_key": family,
                }
            )

        family_counts: dict[str, int] = {}
        provider_model_counts: dict[str, int] = {}
        for item in enriched:
            family_counts[item["family_key"]] = (
                family_counts.get(item["family_key"], 0) + 1
            )
            provider_model_counts[item["provider_key"]] = (
                provider_model_counts.get(item["provider_key"], 0) + 1
            )

        result: list[dict[str, Any]] = []
        for item in enriched:
            status = self._resolve_status(
                item,
                family_counts=family_counts,
                provider_model_counts=provider_model_counts,
            )
            if status not in INDEPENDENCE_STATUS:
                status = "UNKNOWN"
            result.append(
                {
                    **item,
                    "independence_status": status,
                }
            )
        return result

    @staticmethod
    def _resolve_status(
        item: dict[str, Any],
        *,
        family_counts: dict[str, int],
        provider_model_counts: dict[str, int],
    ) -> str:
        family = item["family_key"]
        provider_key = item["provider_key"]

        if provider_model_counts.get(provider_key, 0) > 1:
            return "DUPLICATE"

        if family == "mock" and family_counts.get("mock", 0) > 1:
            # mock 여러 개 — 동일 family
            return "SAME_PROVIDER_FAMILY"

        if family_counts.get(family, 0) > 1:
            return "SAME_PROVIDER_FAMILY"

        # openai vs openai_compatible 는 family map 에서 동일 openai
        return "INDEPENDENT"
