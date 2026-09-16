"""STEP 12-2-2 — Strategy Draft Generation Service.

권장 흐름(스펙 §9)을 그대로 구현한다.

A. 짧은 트랜잭션 — Request/Candidate 잠금, 상태·fingerprint 검증,
   Generation Run을 PENDING으로 저장, commit(락 해제).
B. DB 락 없이 AI 호출.
C. 결과 저장 트랜잭션 — Request/Candidate를 다시 잠그고 재검증한 뒤
   (STEP12-2-1A의 `StrategyDraftService.create()`가 이미 수행하는
   재검증을 그대로 재사용 — 중복 구현하지 않음) 구조화 결과를 검증하고
   Draft를 생성한다. 상태가 바뀌었으면 결과를 폐기하고 FAILED로 기록한다.

AIExecutionRunner(STEP11-5)는 재사용하지 않는다 — 그 상위 상태머신
(execution_request의 DRAFT/READY/예산/lease)은 이번 STEP이 요구하는
단순한 PENDING/RUNNING/종결 흐름보다 훨씬 무겁고 목적이 다르다. 대신 더
하위 레벨인 AIManager/prompt 렌더러/output_validator를 직접 재사용하고,
Run/Attempt는 도메인 전용 경량 모델로 신설한다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.service import AICandidateLifecycleService
from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPromptTemplateVersionEntity,
)
from stock_platform.ai.prompt.output_validator import validate_ai_output
from stock_platform.ai.providers.dto import AIChatRequest, ChatMessage, FinishReason
from stock_platform.ai.providers.manager import AIManager, get_ai_manager
from stock_platform.ai.strategy_draft.service import (
    StrategyDraftError,
    StrategyDraftService,
)
from stock_platform.ai.strategy_draft_generation.constants import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS,
    TERMINAL_GENERATION_RUN_STATUSES,
)
from stock_platform.ai.strategy_draft_generation.entities import (
    StrategyDraftGenerationAttemptEntity,
    StrategyDraftGenerationRunEntity,
)
from stock_platform.ai.strategy_draft_generation.prompt import (
    STRATEGY_DRAFT_OUTPUT_ENVELOPE,
    SYSTEM_TEMPLATE_V1,
    USER_TEMPLATE_V1,
    build_prompt_variables,
    render_system_prompt,
    render_user_prompt,
)
from stock_platform.ai.strategy_draft_generation.schema import (
    GenerationSchemaError,
    parse_and_validate_output,
)
from stock_platform.ai.strategy_draft_generation.seed import ensure_prompt_template
from stock_platform.ai.strategy_request.entities import StrategyRequestEntity
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.security_mask import redact_mapping
from stock_platform.operation.audit_repository import AuditEventRepository


class StrategyDraftGenerationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _to_dict(row: StrategyDraftGenerationRunEntity) -> dict[str, Any]:
    return {
        "generation_run_id": int(row.generation_run_id),
        "strategy_request_id": int(row.strategy_request_id),
        "candidate_id": int(row.candidate_id),
        "draft_id": int(row.draft_id) if row.draft_id is not None else None,
        "idempotency_key": row.idempotency_key,
        "status": row.status,
        "candidate_lifecycle_status_at_request": row.candidate_lifecycle_status_at_request,
        "candidate_fingerprint_at_request": row.candidate_fingerprint_at_request,
        "provider": row.provider,
        "model": row.model,
        "model_parameters": row.model_parameters,
        "timeout_seconds": row.timeout_seconds,
        "retry_of_run_id": row.retry_of_run_id,
        "retry_number": row.retry_number,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "requested_by": row.requested_by,
        "executed_by": row.executed_by,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _attempt_to_dict(row: StrategyDraftGenerationAttemptEntity) -> dict[str, Any]:
    return {
        "generation_attempt_id": int(row.generation_attempt_id),
        "generation_run_id": int(row.generation_run_id),
        "attempt_no": row.attempt_no,
        "provider": row.provider,
        "model": row.model,
        "prompt_hash": row.prompt_hash,
        "response_hash": row.response_hash,
        "structured_response": row.structured_response,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
    }


class StrategyDraftGenerationService:
    def __init__(
        self, session: Session, *, ai_manager: AIManager | None = None
    ) -> None:
        self._session = session
        self._ai_manager = ai_manager or get_ai_manager()

    # ------------------------------------------------------------------
    # Step A — 짧은 트랜잭션: 재검증 + Run(PENDING) 생성
    # ------------------------------------------------------------------
    def create_generation_run(
        self,
        *,
        strategy_request_id: int,
        actor: str,
        idempotency_key: str | None = None,
        provider_id: str | None = None,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry_of_run_id: int | None = None,
        retry_number: int = 0,
    ) -> dict[str, Any]:
        key = (idempotency_key or "").strip() or uuid.uuid4().hex

        existing = self._session.scalar(
            select(StrategyDraftGenerationRunEntity).where(
                StrategyDraftGenerationRunEntity.strategy_request_id
                == int(strategy_request_id),
                StrategyDraftGenerationRunEntity.idempotency_key == key,
            )
        )
        if existing is not None:
            return {**_to_dict(existing), "idempotent_replay": True}

        active = self._session.scalar(
            select(StrategyDraftGenerationRunEntity).where(
                StrategyDraftGenerationRunEntity.strategy_request_id
                == int(strategy_request_id),
                StrategyDraftGenerationRunEntity.status.in_(("PENDING", "RUNNING")),
            )
        )
        if active is not None:
            raise StrategyDraftGenerationError(
                "DUPLICATE_ACTIVE_GENERATION_RUN",
                f"이미 진행 중인 Generation Run이 있습니다: #{active.generation_run_id}",
            )

        draft_svc = StrategyDraftService(self._session)
        try:
            request, candidate = draft_svc.validate_creatable(strategy_request_id)
        except StrategyDraftError as exc:
            raise StrategyDraftGenerationError(exc.code, exc.message) from exc

        provenance_fingerprint: str | None = None
        provenance_schema_version: str | None = None
        try:
            provenance = AICandidateLifecycleService(self._session).get_provenance(
                int(candidate.candidate_id)
            )
            provenance_fingerprint = provenance.get("combined_source_fingerprint")
            provenance_schema_version = provenance.get("schema_version")
        except Exception:  # noqa: BLE001 — provenance는 참고용, 없으면 생략
            pass

        resolved_provider = provider_id or self._ai_manager.select_provider().provider_id
        cfg = self._ai_manager.registry.get_config(resolved_provider)
        resolved_model = model or (cfg.model if cfg else "")

        template_info = ensure_prompt_template(self._session)

        row = StrategyDraftGenerationRunEntity(
            strategy_request_id=int(strategy_request_id),
            candidate_id=int(candidate.candidate_id),
            idempotency_key=key,
            status="PENDING",
            candidate_lifecycle_status_at_request=candidate.lifecycle_status,
            candidate_fingerprint_at_request=candidate.source_fingerprint,
            strategy_request_fingerprint_at_review=request.candidate_fingerprint_at_review,
            candidate_provenance_fingerprint=provenance_fingerprint,
            candidate_provenance_schema_version=provenance_schema_version,
            prompt_template_id=template_info["prompt_template_id"],
            prompt_version_id=template_info["prompt_version_id"],
            provider=resolved_provider,
            model=resolved_model,
            model_parameters={"temperature": temperature, "max_tokens": max_tokens},
            timeout_seconds=timeout_seconds,
            retry_of_run_id=retry_of_run_id,
            retry_number=retry_number,
            requested_by=actor,
            executed_by=actor,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise StrategyDraftGenerationError(
                "DUPLICATE_ACTIVE_GENERATION_RUN",
                "이미 진행 중인 Generation Run이 있습니다(동시 요청 감지).",
            ) from exc
        self._session.commit()
        self._session.refresh(row)
        return {**_to_dict(row), "idempotent_replay": False}

    def start_generation(self, generation_run_id: int, *, actor: str) -> dict[str, Any]:
        """PENDING -> RUNNING 전이(STEP12-2-3/STEP12-2-3A).

        STEP12-2-3A: API 경로(admin_strategy_draft_generations.py)를 거치지
        않고 이 메서드가 직접 호출되는 경로(테스트, 향후 배치 작업 등)에서도
        STARTED가 항상 기록되도록, Audit 기록 책임을 이 메서드 자체로
        옮겼다(기존에는 API 레이어에서만 호출 직후 별도로 Audit을 남겨,
        서비스를 직접 호출하면 STARTED가 누락되는 결함이 있었다).
        `ai/` 패키지 서비스는 원래 Audit을 직접 남기지 않는 관례였지만,
        이 이벤트는 "PENDING->RUNNING 상태 전이" 자체와 1:1로 묶여 있어
        호출 경로(HTTP API vs 직접 호출)에 관계없이 상태 전이와 원자적으로
        기록되어야 한다고 판단해 예외적으로 이 서비스에 둔다(FastAPI에
        의존하지 않는 `operation.audit_repository.AuditEventRepository`를
        직접 사용 — `api.deps_admin`을 임포트해 계층을 거스르지 않는다).
        Audit 기록 실패는 기존 정책대로 본 상태 전이(RUNNING)에 영향을
        주지 않는다(이미 커밋된 뒤 별도 시도이므로 실패해도 롤백하지 않음).
        """
        run = self._require(generation_run_id)
        if run.status != "PENDING":
            raise StrategyDraftGenerationError(
                "INVALID_STATE_TRANSITION",
                f"{run.status} 상태에서는 시작할 수 없습니다(PENDING 전용).",
            )
        run.status = "RUNNING"
        run.started_at = _utcnow()
        self._session.flush()
        self._session.commit()
        self._session.refresh(run)
        self._record_started_audit(run, actor=actor)
        return _to_dict(run)

    def _record_started_audit(
        self, run: StrategyDraftGenerationRunEntity, *, actor: str
    ) -> None:
        try:
            AuditEventRepository(self._session).create(
                event_type="STRATEGY_DRAFT_GENERATION_STARTED",
                actor=actor,
                request_id=None,
                run_id=str(run.generation_run_id),
                strategy_id=str(run.strategy_request_id),
                account_hash=None,
                order_id=None,
                client_order_id=None,
                symbol=None,
                detail=redact_mapping(
                    to_jsonable(
                        {
                            "generation_run_id": run.generation_run_id,
                            "strategy_request_id": run.strategy_request_id,
                            "provider": run.provider,
                            "model": run.model,
                        }
                    )
                ),
                created_at=_utcnow(),
            )
            self._session.commit()
        except Exception:  # noqa: BLE001 — Audit 실패가 상태 전이를 막지 않는다.
            self._session.rollback()

    # ------------------------------------------------------------------
    # Step B(락 없이 AI 호출) + Step C(짧은 트랜잭션: 재검증 + Draft 생성)
    # ------------------------------------------------------------------
    async def generate(self, generation_run_id: int, *, actor: str) -> dict[str, Any]:
        run = self._require(generation_run_id)
        if run.status == "PENDING":
            # API 레이어가 start_generation()을 먼저 호출하지 않고 바로
            # generate()를 호출하는 기존(STEP12-2-2) 호출 경로와의 하위
            # 호환을 위해 자동으로 시작한다.
            self.start_generation(generation_run_id, actor=actor)
            run = self._require(generation_run_id)
        elif run.status != "RUNNING":
            raise StrategyDraftGenerationError(
                "INVALID_STATE_TRANSITION",
                f"{run.status} 상태에서는 generate()를 호출할 수 없습니다(PENDING/RUNNING 전용).",
            )

        # Run이 생성 시점에 참조한 prompt_version_id의 저장된 텍스트를 그대로
        # 사용한다(현재 ACTIVE 버전이 그 뒤 바뀌었어도 이 Run은 재현 가능).
        version_row = self._session.get(
            AIPromptTemplateVersionEntity, run.prompt_version_id
        )
        output_schema_row = (
            self._session.get(AIOutputSchemaEntity, version_row.output_schema_id)
            if version_row and version_row.output_schema_id
            else None
        )
        json_schema = (
            output_schema_row.json_schema
            if output_schema_row
            else STRATEGY_DRAFT_OUTPUT_ENVELOPE
        )

        variables = self._build_variables(run)
        system_prompt = render_system_prompt(
            variables,
            system_template=(
                version_row.system_template if version_row else SYSTEM_TEMPLATE_V1
            ),
        )
        user_prompt = render_user_prompt(
            variables,
            user_template=(
                version_row.user_template if version_row else USER_TEMPLATE_V1
            ),
        )
        model_params = run.model_parameters or {}

        chat_request = AIChatRequest(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            model=run.model or None,
            temperature=float(model_params.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=int(model_params.get("max_tokens", DEFAULT_MAX_TOKENS)),
            json_mode=True,
            # STEP12-3 §18: DB에 기록된 run.timeout_seconds를 실제 호출에도
            # 적용한다(과거엔 기록값과 AIProviderConfig의 전역 설정이 서로
            # 달라도 겉보기엔 알 수 없었던 Known Issue를 해소).
            timeout_seconds=float(run.timeout_seconds),
            metadata={
                "task_type": "STRATEGY_DRAFT",
                # think=False: 추론형 Provider(Ollama qwen3.5 등)가 구조화
                # 출력 요청에서 "생각" 단계에 토큰 예산을 소진해 content가
                # 비는 것을 방지한다(§11 실제 Ollama 스모크 테스트로 확인).
                "think": False,
                # STEP12-2-3A: json_schema를 넘기면 이를 지원하는 Provider
                # (Ollama 등)가 문자열 "json" 대신 grammar 제약 디코딩으로
                # 스키마를 구조적으로 강제한다 — 지원하지 않는 Provider는
                # 이 키를 무시하므로 하위 호환에 영향 없다.
                "json_schema": json_schema,
            },
        )

        response = await self._ai_manager.chat(
            chat_request, provider_id=run.provider, fallback=False
        )

        attempt_no = 1 + int(
            self._session.scalar(
                select(func.count()).where(
                    StrategyDraftGenerationAttemptEntity.generation_run_id
                    == run.generation_run_id
                )
            )
            or 0
        )
        system_hash = _hash(system_prompt)
        user_hash = _hash(user_prompt)
        prompt_hash = _hash(system_prompt + "\n" + user_prompt)
        payload_hash = _hash(
            json.dumps(
                {
                    "model": chat_request.model,
                    "temperature": chat_request.temperature,
                    "max_tokens": chat_request.max_tokens,
                    "prompt_hash": prompt_hash,
                },
                sort_keys=True,
            )
        )

        if not response.ok:
            is_timeout = response.finish_reason == FinishReason.TIMEOUT
            return self._finish_failed(
                run,
                attempt_no=attempt_no,
                provider=response.provider_id,
                model=response.model,
                system_hash=system_hash,
                user_hash=user_hash,
                prompt_hash=prompt_hash,
                payload_hash=payload_hash,
                response_hash=None,
                structured_response=None,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                latency_ms=response.latency_ms,
                error_code=(response.error.code if response.error else "PROVIDER_ERROR"),
                error_message=(
                    response.error.message if response.error else "Provider error"
                ),
                run_status="TIMED_OUT" if is_timeout else "FAILED",
                actor=actor,
            )

        response_hash = _hash(response.content)
        validation = validate_ai_output(
            raw=response.content,
            json_schema=json_schema,
            expected_task_type="STRATEGY_DRAFT",
        )
        if validation["status"] in {"INVALID", "BLOCKED"}:
            return self._finish_failed(
                run,
                attempt_no=attempt_no,
                provider=response.provider_id,
                model=response.model,
                system_hash=system_hash,
                user_hash=user_hash,
                prompt_hash=prompt_hash,
                payload_hash=payload_hash,
                response_hash=response_hash,
                structured_response=None,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                latency_ms=response.latency_ms,
                error_code=validation["code"],
                error_message=validation["message"],
                run_status="FAILED",
                actor=actor,
            )

        try:
            structured = parse_and_validate_output(validation["data"]["result"])
        except GenerationSchemaError as exc:
            return self._finish_failed(
                run,
                attempt_no=attempt_no,
                provider=response.provider_id,
                model=response.model,
                system_hash=system_hash,
                user_hash=user_hash,
                prompt_hash=prompt_hash,
                payload_hash=payload_hash,
                response_hash=response_hash,
                structured_response=validation["data"].get("result"),
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                latency_ms=response.latency_ms,
                error_code=exc.code,
                error_message=exc.message,
                run_status="FAILED",
                actor=actor,
            )

        # ---- Step C: 재잠금 + 재검증(StrategyDraftService.create 재사용) + Draft 생성 ----
        return self._finish_succeeded(
            run,
            attempt_no=attempt_no,
            structured=structured,
            provider=response.provider_id,
            model=response.model,
            system_hash=system_hash,
            user_hash=user_hash,
            prompt_hash=prompt_hash,
            payload_hash=payload_hash,
            response_hash=response_hash,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            latency_ms=response.latency_ms,
            actor=actor,
        )

    def _finish_succeeded(
        self,
        run: StrategyDraftGenerationRunEntity,
        *,
        attempt_no: int,
        structured: Any,
        provider: str,
        model: str,
        system_hash: str,
        user_hash: str,
        prompt_hash: str,
        payload_hash: str,
        response_hash: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        latency_ms: float,
        actor: str,
    ) -> dict[str, Any]:
        safe_result = structured.model_dump()
        try:
            draft_svc = StrategyDraftService(self._session)
            draft = draft_svc.create(
                strategy_request_id=int(run.strategy_request_id),
                actor=actor,
                title=structured.title,
                timeframe=structured.timeframe,
                market_type=structured.market_type,
                summary=structured.summary,
                entry_rule=json.dumps(
                    [r.model_dump() for r in structured.entry_rules],
                    ensure_ascii=False,
                ),
                exit_rule=json.dumps(
                    [r.model_dump() for r in structured.exit_rules],
                    ensure_ascii=False,
                ),
                stop_loss_rule=json.dumps(
                    structured.stop_loss_rule.model_dump(), ensure_ascii=False
                ),
                take_profit_rule=json.dumps(
                    structured.take_profit_rule.model_dump(), ensure_ascii=False
                ),
                position_sizing_rule=json.dumps(
                    structured.position_sizing_rule.model_dump(), ensure_ascii=False
                ),
                risk_parameters=structured.risk_parameters,
                indicator_configuration={"indicators": structured.indicators},
                llm_provider=provider,
                llm_model=model,
                prompt_version=str(run.prompt_version_id or "v1"),
            )
        except StrategyDraftError as exc:
            # AI 호출 도중 Candidate가 revoke/expire/supersede된 경우 등 —
            # StrategyDraftService.create()의 재검증이 여기서 실패로 잡아준다.
            return self._finish_failed(
                run,
                attempt_no=attempt_no,
                provider=provider,
                model=model,
                system_hash=system_hash,
                user_hash=user_hash,
                prompt_hash=prompt_hash,
                payload_hash=payload_hash,
                response_hash=response_hash,
                structured_response=safe_result,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                error_code=exc.code,
                error_message=exc.message,
                run_status="FAILED",
                actor=actor,
            )

        locked_run = self._session.scalar(
            select(StrategyDraftGenerationRunEntity)
            .where(
                StrategyDraftGenerationRunEntity.generation_run_id
                == run.generation_run_id
            )
            .with_for_update()
        )
        locked_run.status = "SUCCEEDED"
        locked_run.draft_id = int(draft["draft_id"])
        locked_run.completed_at = _utcnow()
        self._session.add(
            StrategyDraftGenerationAttemptEntity(
                generation_run_id=locked_run.generation_run_id,
                attempt_no=attempt_no,
                provider=provider,
                model=model,
                system_prompt_hash=system_hash,
                user_prompt_hash=user_hash,
                prompt_hash=prompt_hash,
                request_payload_hash=payload_hash,
                response_hash=response_hash,
                structured_response=safe_result,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                status="SUCCEEDED",
                started_at=run.started_at,
                completed_at=_utcnow(),
            )
        )
        self._session.commit()
        self._session.refresh(locked_run)
        return {"run": _to_dict(locked_run), "draft": draft}

    def _finish_failed(
        self,
        run: StrategyDraftGenerationRunEntity,
        *,
        attempt_no: int,
        provider: str,
        model: str,
        system_hash: str | None,
        user_hash: str | None,
        prompt_hash: str | None,
        payload_hash: str | None,
        response_hash: str | None,
        structured_response: Any,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        latency_ms: float | None,
        error_code: str,
        error_message: str,
        run_status: str,
        actor: str,
    ) -> dict[str, Any]:
        locked_run = self._session.scalar(
            select(StrategyDraftGenerationRunEntity)
            .where(
                StrategyDraftGenerationRunEntity.generation_run_id
                == run.generation_run_id
            )
            .with_for_update()
        )
        locked_run.status = run_status
        locked_run.completed_at = _utcnow()
        locked_run.error_code = error_code
        locked_run.error_message = (error_message or "")[:500]
        self._session.add(
            StrategyDraftGenerationAttemptEntity(
                generation_run_id=locked_run.generation_run_id,
                attempt_no=attempt_no,
                provider=provider,
                model=model,
                system_prompt_hash=system_hash,
                user_prompt_hash=user_hash,
                prompt_hash=prompt_hash,
                request_payload_hash=payload_hash,
                response_hash=response_hash,
                structured_response=structured_response,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                status=run_status,
                error_code=error_code,
                error_message=(error_message or "")[:500],
                started_at=run.started_at,
                completed_at=_utcnow(),
            )
        )
        self._session.commit()
        self._session.refresh(locked_run)
        return {"run": _to_dict(locked_run), "draft": None}

    # ------------------------------------------------------------------
    # 단일 진입점 — API 레이어가 사용
    # ------------------------------------------------------------------
    async def generate_strategy_draft(
        self,
        *,
        strategy_request_id: int,
        actor: str,
        idempotency_key: str | None = None,
        provider_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        created = self.create_generation_run(
            strategy_request_id=strategy_request_id,
            actor=actor,
            idempotency_key=idempotency_key,
            provider_id=provider_id,
            model=model,
        )
        if created.get("idempotent_replay") and created["status"] != "PENDING":
            # 이미 종결된(또는 진행 중인) 동일 idempotency_key 재요청 —
            # 새로 generate()를 실행하지 않고 기존 결과를 그대로 반환한다.
            run = self._require(created["generation_run_id"])
            return {"run": _to_dict(run), "draft": None, "idempotent_replay": True}
        result = await self.generate(created["generation_run_id"], actor=actor)
        result["idempotent_replay"] = False
        return result

    def retry_generation(self, generation_run_id: int, *, actor: str) -> dict[str, Any]:
        """종결(FAILED/TIMED_OUT/CANCELLED) Run에 대해 새 Run을 생성한다.

        기존 Run을 되살리지 않고 retry_of_run_id로 연결된 새 Run(PENDING)을
        반환한다 — 실제 AI 호출은 이 Run에 대해 별도로 generate()를
        호출해야 한다(API 레이어에서 이어서 수행).
        """
        old = self._require(generation_run_id)
        if old.status == "SUCCEEDED":
            raise StrategyDraftGenerationError(
                "INVALID_STATE_TRANSITION",
                "SUCCEEDED Run은 재시도할 수 없습니다(이미 Draft가 생성됨).",
            )
        if old.status not in TERMINAL_GENERATION_RUN_STATUSES:
            raise StrategyDraftGenerationError(
                "INVALID_STATE_TRANSITION",
                f"{old.status} 상태의 Run은 재시도할 수 없습니다(종결 상태만 가능).",
            )
        return self.create_generation_run(
            strategy_request_id=int(old.strategy_request_id),
            actor=actor,
            idempotency_key=uuid.uuid4().hex,
            provider_id=old.provider,
            model=old.model,
            retry_of_run_id=int(old.generation_run_id),
            retry_number=int(old.retry_number) + 1,
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def get_generation_run(self, generation_run_id: int) -> dict[str, Any]:
        run = self._require(generation_run_id)
        attempts = list(
            self._session.scalars(
                select(StrategyDraftGenerationAttemptEntity)
                .where(
                    StrategyDraftGenerationAttemptEntity.generation_run_id
                    == generation_run_id
                )
                .order_by(StrategyDraftGenerationAttemptEntity.attempt_no.asc())
            )
        )
        return {**_to_dict(run), "attempts": [_attempt_to_dict(a) for a in attempts]}

    def list_attempts(self, generation_run_id: int) -> dict[str, Any]:
        """STEP12-2-3 — Attempt 목록 전용 조회(§12)."""
        self._require(generation_run_id)
        attempts = list(
            self._session.scalars(
                select(StrategyDraftGenerationAttemptEntity)
                .where(
                    StrategyDraftGenerationAttemptEntity.generation_run_id
                    == generation_run_id
                )
                .order_by(StrategyDraftGenerationAttemptEntity.attempt_no.asc())
            )
        )
        return {"items": [_attempt_to_dict(a) for a in attempts]}

    def get_latest_attempt_for_draft(self, draft_id: int) -> dict[str, Any] | None:
        """STEP12-2-3 — 비교(comparison)용 정확한 연결 체인:

        draft_id -> 그 draft_id를 만든 generation_run(정확히 그 Run, 요청
        기준 최신 Run이나 전역 최신 Run이 아님) -> 그 Run의 SUCCEEDED
        Attempt(그 Run에 실패 Attempt가 더 있어도 실패 Attempt는 절대
        반환하지 않는다). 수동 생성 Draft이거나 연결된 Run/Attempt가 없으면
        None을 반환한다. 재시도(retry)는 항상 새 Run(retry_of_run_id로
        연결)을 만들 뿐 기존 Run.draft_id는 바꾸지 않으므로, 이미 성공한
        Draft의 비교 기준은 그 이후의 재시도 Run과 무관하게 고정된다.
        """
        run = self._session.scalar(
            select(StrategyDraftGenerationRunEntity).where(
                StrategyDraftGenerationRunEntity.draft_id == int(draft_id)
            )
        )
        if run is None:
            return None
        attempt = self._session.scalar(
            select(StrategyDraftGenerationAttemptEntity)
            .where(
                StrategyDraftGenerationAttemptEntity.generation_run_id
                == run.generation_run_id,
                StrategyDraftGenerationAttemptEntity.status == "SUCCEEDED",
            )
            .order_by(StrategyDraftGenerationAttemptEntity.attempt_no.desc())
            .limit(1)
        )
        return _attempt_to_dict(attempt) if attempt else None

    def list_generation_runs(
        self,
        *,
        strategy_request_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(StrategyDraftGenerationRunEntity)
        if strategy_request_id is not None:
            stmt = stmt.where(
                StrategyDraftGenerationRunEntity.strategy_request_id
                == int(strategy_request_id)
            )
        if status is not None:
            stmt = stmt.where(StrategyDraftGenerationRunEntity.status == status)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self._session.scalar(count_stmt) or 0)
        rows = list(
            self._session.scalars(
                stmt.order_by(StrategyDraftGenerationRunEntity.generation_run_id.desc())
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 200))
            )
        )
        return {"items": [_to_dict(r) for r in rows], "total": total}

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _require(self, generation_run_id: int) -> StrategyDraftGenerationRunEntity:
        row = self._session.get(
            StrategyDraftGenerationRunEntity, int(generation_run_id)
        )
        if row is None:
            raise StrategyDraftGenerationError(
                "NOT_FOUND", f"Generation Run not found: {generation_run_id}"
            )
        return row

    def _build_variables(
        self, run: StrategyDraftGenerationRunEntity
    ) -> dict[str, Any]:
        request = self._session.get(
            StrategyRequestEntity, int(run.strategy_request_id)
        )
        row = self._session.execute(
            text(
                "SELECT symbol, exchange_code, total_score, rule_result, "
                "score_breakdown FROM strategy.candidate_result WHERE result_id = :cid"
            ),
            {"cid": int(run.candidate_id)},
        ).mappings().first()

        symbol = row["symbol"] if row else "UNKNOWN"
        market_type = "CRYPTO" if row and row["exchange_code"] == "UPBIT" else "KR_STOCK"
        candidate_evidence = {
            "candidate_id": int(run.candidate_id),
            "exchange_code": row["exchange_code"] if row else None,
            "total_score": float(row["total_score"]) if row and row["total_score"] is not None else None,
            "rule_result": row["rule_result"] if row else None,
        }
        signals_and_scores = {
            "score_breakdown": row["score_breakdown"] if row else None,
        }
        candidate_provenance = {
            "candidate_lifecycle_status_at_request": run.candidate_lifecycle_status_at_request,
            "candidate_fingerprint_at_request": run.candidate_fingerprint_at_request,
            "provenance_fingerprint": run.candidate_provenance_fingerprint,
            "provenance_schema_version": run.candidate_provenance_schema_version,
        }
        risk_limits = {
            "max_stop_loss_percent": 30.0,
            "max_take_profit_percent": 200.0,
            "max_position_size_fraction": 1.0,
        }
        return build_prompt_variables(
            candidate_id=int(run.candidate_id),
            market_type=market_type,
            symbol=symbol,
            timeframe_hint="1D",
            candidate_evidence=candidate_evidence,
            signals_and_scores=signals_and_scores,
            candidate_provenance=candidate_provenance,
            risk_limits=risk_limits,
        )
