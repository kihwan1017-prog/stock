"""STEP 11-7 — Eligibility (Prompt ACTIVE, Snapshot, Data Quality)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.market_analysis.constants import (
    ANALYSIS_TYPES,
    REFERENCE_DISCLAIMER,
    TIMEFRAMES,
    VISION_ENABLED_DEFAULT,
)
from stock_platform.ai.market_analysis.snapshot import MarketSnapshotBuilder
from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPolicyDefinitionEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)


class AIMarketEligibilityService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._snapshots = MarketSnapshotBuilder(session)

    def evaluate(
        self,
        *,
        analysis_type: str,
        exchange_code: str,
        symbol: str | None = None,
        timeframe: str = "1D",
        data_from: date | None = None,
        data_to: date | None = None,
        include_incomplete_candle: bool = False,
        execution_mode: str = "MOCK",
        provider_code: str | None = "mock",
        prompt_version_id: int | None = None,
        use_vision: bool = False,
    ) -> dict[str, Any]:
        if analysis_type not in ANALYSIS_TYPES:
            return {
                "eligible": False,
                "blockers": ["INVALID_ANALYSIS_TYPE"],
            }
        if use_vision and not VISION_ENABLED_DEFAULT:
            return {
                "eligible": False,
                "blockers": ["VISION_DISABLED"],
                "message": "Vision chart analysis disabled in STEP 11-7",
            }

        if analysis_type == "SYMBOL_CHART":
            if not symbol:
                return {"eligible": False, "blockers": ["SYMBOL_REQUIRED"]}
            if timeframe not in TIMEFRAMES:
                return {"eligible": False, "blockers": ["INVALID_TIMEFRAME"]}
            snap = self._snapshots.build_chart_snapshot(
                exchange_code=exchange_code,
                symbol=symbol,
                timeframe=timeframe,
                data_from=data_from,
                data_to=data_to,
                include_incomplete_candle=include_incomplete_candle,
            )
            task_type = "CHART_ANALYSIS"
            schema_code = "CHART_ANALYSIS_RESULT_V1"
            prompt_code = "CHART_ANALYSIS_BASE"
        else:
            snap = self._snapshots.build_market_overview(
                exchange_code=exchange_code
            )
            task_type = "MARKET_ANALYSIS"
            schema_code = "MARKET_ANALYSIS_RESULT_V1"
            prompt_code = "MARKET_ANALYSIS_BASE"

        if not snap.get("ok"):
            return {
                "eligible": False,
                "blockers": [snap.get("code") or "SNAPSHOT_FAILED"],
                "message": snap.get("message"),
                "snapshot": snap,
            }

        quality = snap.get("data_quality_status") or "UNKNOWN"
        blockers: list[str] = []
        warnings: list[str] = list(snap.get("quality_warnings") or [])
        if quality == "INVALID":
            blockers.append("DATA_QUALITY_INVALID")

        schema = self._session.scalar(
            select(AIOutputSchemaEntity).where(
                AIOutputSchemaEntity.code == schema_code,
                AIOutputSchemaEntity.status == "ACTIVE",
            )
        )
        prompt_tpl = self._session.scalar(
            select(AIPromptTemplateEntity).where(
                AIPromptTemplateEntity.code == prompt_code
            )
        )
        prompt_version = None
        if prompt_version_id:
            prompt_version = self._session.get(
                AIPromptTemplateVersionEntity, prompt_version_id
            )
        elif prompt_tpl and prompt_tpl.active_version_id:
            prompt_version = self._session.get(
                AIPromptTemplateVersionEntity, prompt_tpl.active_version_id
            )

        core_policy = self._session.scalar(
            select(AIPolicyDefinitionEntity).where(
                AIPolicyDefinitionEntity.code == "CORE_FINANCIAL_GUARDRAIL",
                AIPolicyDefinitionEntity.status == "ACTIVE",
            )
        )

        if schema is None:
            blockers.append("SCHEMA_INACTIVE_OR_MISSING")
        if prompt_tpl is None:
            blockers.append("PROMPT_TEMPLATE_MISSING")
        elif prompt_tpl.status != "ACTIVE":
            blockers.append("PROMPT_DRAFT_OR_INACTIVE")
        if prompt_version is None:
            blockers.append("PROMPT_VERSION_MISSING")
        elif prompt_version.status != "ACTIVE":
            blockers.append("PROMPT_VERSION_INACTIVE")
        if core_policy is None:
            blockers.append("CORE_POLICY_INACTIVE")

        # 외부 mode에서 mock 금지는 Execution이 처리
        provider = (provider_code or "mock").lower()
        if execution_mode == "MOCK" and provider != "mock":
            blockers.append("MOCK_MODE_REQUIRES_MOCK")

        # Snapshot JSON에 계좌/주문 필드 없는지 확인
        snap_text = json.dumps(snap.get("snapshot") or {}, ensure_ascii=False)
        for banned in (
            "account_balance",
            "avg_buy_price",
            "position_qty",
            "api_key",
            "broker_credential",
        ):
            if banned in snap_text.lower():
                blockers.append("DATA_POLICY_ACCOUNT_LEAK")

        return {
            "eligible": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "task_type": task_type,
            "schema_id": schema.output_schema_id if schema else None,
            "prompt_template_id": (
                prompt_tpl.prompt_template_id if prompt_tpl else None
            ),
            "prompt_version_id": (
                prompt_version.prompt_template_version_id
                if prompt_version
                else None
            ),
            "policy_ids": (
                [core_policy.policy_definition_id] if core_policy else []
            ),
            "snapshot": snap,
            "data_classification": "PUBLIC",
            "disclaimer": REFERENCE_DISCLAIMER,
            "vision_used": False,
            "external_ai_called": False,
        }
