"""STEP 11-5 — Token 비용 추정 (관리자 입력 Pricing만)."""

from __future__ import annotations

import fnmatch
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.execution.entities import AIProviderPricingEntity


def calculate_cost(
    session: Session,
    *,
    provider_code: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> dict[str, Any]:
    """가격 미설정/Mock은 null — 0으로 오인하지 않음."""

    if provider_code in {"mock"}:
        return {
            "estimated_cost": None,
            "currency": "USD",
            "cost_calculation_status": "NOT_APPLICABLE",
            "pricing_version": None,
        }

    if input_tokens is None and output_tokens is None:
        return {
            "estimated_cost": None,
            "currency": "USD",
            "cost_calculation_status": "USAGE_NOT_PROVIDED",
            "pricing_version": None,
        }

    now = datetime.now(timezone.utc)
    rows = list(
        session.scalars(
            select(AIProviderPricingEntity).where(
                AIProviderPricingEntity.provider_code == provider_code
            )
        )
    )
    match: AIProviderPricingEntity | None = None
    for row in rows:
        if row.effective_to is not None and row.effective_to < now:
            continue
        if row.effective_from > now:
            continue
        if fnmatch.fnmatch(model or "", row.model_pattern):
            match = row
            break

    if match is None:
        status = "UNKNOWN_MODEL" if rows else "PRICING_NOT_CONFIGURED"
        return {
            "estimated_cost": None,
            "currency": "USD",
            "cost_calculation_status": status,
            "pricing_version": None,
        }

    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    cost = (inp / 1_000_000.0) * float(match.input_price_per_1m_tokens) + (
        out / 1_000_000.0
    ) * float(match.output_price_per_1m_tokens)
    return {
        "estimated_cost": round(cost, 8),
        "currency": match.currency,
        "cost_calculation_status": "CALCULATED",
        "pricing_version": match.pricing_version,
    }
