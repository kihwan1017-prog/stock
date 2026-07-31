"""STEP 12-2-2 — 기존 Prompt Template/Output Schema 구조 재사용(get-or-create).

`ai.prompt_template`/`ai.prompt_template_version`/`ai.output_schema`
(STEP 11-4)를 그대로 사용한다 — 신규 Prompt 테이블을 만들지 않는다.
최초 호출 시 이 모듈의 템플릿 텍스트/스키마로 ACTIVE 버전을 1회 생성하고,
이후에는 있는 것을 그대로 읽는다(멱등). Prompt Version이 나중에
갱신되더라도, 이미 생성된 Generation Run은 자신이 참조한
prompt_version_id의 저장된 텍스트를 그대로 유지하므로 재현 가능하다.

STEP12-2-3A: 과거 구현은 `version == 1`을 고정으로 조회해, 코드에서
SYSTEM_TEMPLATE_V1/USER_TEMPLATE_V1/출력 스키마를 수정해도 이미 DB에
심어진(stale) version=1 텍스트를 계속 재사용하는 결함이 있었다(실 Ollama
검증 중 발견 — 스키마를 보강했는데도 오래된 스키마가 그대로 Provider에
전달됨). 이제는 "현재 코드 내용"의 checksum으로 조회해, 일치하는 버전이
없으면 다음 버전 번호로 새 버전(+ 새 output_schema 행)을 만든다. 기존
버전은 그대로 남아 과거 Run의 prompt_version_id가 가리키는 텍스트/스키마는
바뀌지 않는다(재현성 유지) — in-place update가 아니라 append-only.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)
from stock_platform.ai.prompt.renderer import checksum_text
from stock_platform.ai.strategy_draft_generation.constants import (
    OUTPUT_SCHEMA_CODE,
    PROMPT_TEMPLATE_CODE,
    TASK_TYPE,
)
from stock_platform.ai.strategy_draft_generation.prompt import (
    STRATEGY_DRAFT_OUTPUT_ENVELOPE,
    SYSTEM_TEMPLATE_V1,
    USER_TEMPLATE_V1,
)

_SEED_ACTOR = "system:strategy_draft_generation_seed"


def _output_schema_checksum(json_schema: dict[str, Any]) -> str:
    return checksum_text(json.dumps(json_schema, sort_keys=True, ensure_ascii=False))


def ensure_prompt_template(session: Session) -> dict[str, Any]:
    """현재 코드 내용과 일치하는 ACTIVE Prompt Template/Version/Output Schema를
    보장하고 정보를 반환한다(코드 변경 시 자동으로 다음 버전을 만든다)."""

    template_row = session.scalar(
        select(AIPromptTemplateEntity).where(
            AIPromptTemplateEntity.code == PROMPT_TEMPLATE_CODE
        )
    )
    if template_row is None:
        template_row = AIPromptTemplateEntity(
            code=PROMPT_TEMPLATE_CODE,
            name="Strategy Draft Generation v1",
            task_type=TASK_TYPE,
            description=(
                "STEP12-2-2 — Candidate/Strategy Request 근거로 구조화된 "
                "Strategy Draft 초안을 생성하는 Prompt."
            ),
            status="ACTIVE",
            created_by=_SEED_ACTOR,
            updated_by=_SEED_ACTOR,
        )
        session.add(template_row)
        session.flush()

    schema_checksum = _output_schema_checksum(STRATEGY_DRAFT_OUTPUT_ENVELOPE)
    combined_checksum = checksum_text(
        SYSTEM_TEMPLATE_V1, USER_TEMPLATE_V1, PROMPT_TEMPLATE_CODE, schema_checksum
    )

    version_row = session.scalar(
        select(AIPromptTemplateVersionEntity).where(
            AIPromptTemplateVersionEntity.prompt_template_id
            == template_row.prompt_template_id,
            AIPromptTemplateVersionEntity.checksum == combined_checksum,
        )
    )
    if version_row is None:
        next_version = 1 + int(
            session.scalar(
                select(func.max(AIPromptTemplateVersionEntity.version)).where(
                    AIPromptTemplateVersionEntity.prompt_template_id
                    == template_row.prompt_template_id
                )
            )
            or 0
        )
        schema_row = AIOutputSchemaEntity(
            code=f"{OUTPUT_SCHEMA_CODE}_r{next_version}",
            name=f"Strategy Draft Generation Output r{next_version}",
            task_type=TASK_TYPE,
            schema_version=f"1.{next_version - 1}",
            json_schema=STRATEGY_DRAFT_OUTPUT_ENVELOPE,
            strict_mode=True,
            additional_properties_allowed=False,
            status="ACTIVE",
            checksum=schema_checksum,
            created_by=_SEED_ACTOR,
            updated_by=_SEED_ACTOR,
        )
        session.add(schema_row)
        session.flush()

        version_row = AIPromptTemplateVersionEntity(
            prompt_template_id=template_row.prompt_template_id,
            version=next_version,
            system_template=SYSTEM_TEMPLATE_V1,
            user_template=USER_TEMPLATE_V1,
            output_schema_id=schema_row.output_schema_id,
            change_reason=(
                "Initial seed (STEP12-2-2)"
                if next_version == 1
                else f"Auto-versioned: code content changed (r{next_version})"
            ),
            checksum=combined_checksum,
            status="ACTIVE",
            created_by=_SEED_ACTOR,
        )
        session.add(version_row)
        session.flush()

        template_row.active_version_id = version_row.prompt_template_version_id
        session.flush()

    output_schema_row = session.get(AIOutputSchemaEntity, version_row.output_schema_id)

    return {
        "prompt_template_id": int(template_row.prompt_template_id),
        "prompt_version_id": int(version_row.prompt_template_version_id),
        "system_template": version_row.system_template,
        "user_template": version_row.user_template,
        "output_schema_id": int(version_row.output_schema_id),
        "json_schema": output_schema_row.json_schema if output_schema_row else None,
    }
