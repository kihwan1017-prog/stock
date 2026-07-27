"""STEP 11-5 — Execution Runner (DRY_RUN / MOCK / EXTERNAL).

외부 API 호출 중 DB Transaction을 길게 유지하지 않는다.
각 Provider 호출 = execution_run 1건.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.execution.constants import (
    MAX_TOTAL_PROVIDER_CALLS,
    ExecutionMode,
    RequestStatus,
    RunStatus,
)
from stock_platform.ai.execution.cost_service import calculate_cost
from stock_platform.ai.execution.entities import (
    AIExecutionRequestEntity,
    AIExecutionResultEntity,
    AIExecutionRunEntity,
)
from stock_platform.ai.execution.service import AIExecutionError, AIExecutionService
from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPolicyDefinitionEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)
from stock_platform.ai.prompt.injection import inspect_text_security
from stock_platform.ai.prompt.input_validator import (
    AIInputValidationError,
    validate_variables,
)
from stock_platform.ai.prompt.output_validator import validate_ai_output
from stock_platform.ai.prompt.preview_service import AIExecutionPreviewService
from stock_platform.ai.prompt.renderer import PromptRenderError, render_template
from stock_platform.ai.providers.dto import AIChatRequest, ChatMessage
from stock_platform.ai.providers.manager import get_ai_manager
from stock_platform.ai.providers.security import sanitize_for_log


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AIExecutionRunner:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AIExecutionService(session)

    def dry_run(self, request_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIExecutionRequestEntity, request_id)
        if row is None:
            raise AIExecutionError("NOT_FOUND", "Execution not found")
        if row.status not in {
            RequestStatus.READY.value,
            RequestStatus.DRAFT.value,
        }:
            raise AIExecutionError(
                "INVALID_STATE", "Dry-run only from READY/DRAFT"
            )

        self._svc._event(
            request_id,
            event_type="AI_EXECUTION_DRY_RUN_STARTED",
            actor=actor,
            previous=row.status,
            new=row.status,
            correlation_id=row.correlation_id,
        )

        prepared = self._prepare(row)
        if not prepared["ok"]:
            self._svc._event(
                request_id,
                event_type="AI_EXECUTION_DRY_RUN_COMPLETED",
                actor=actor,
                detail={"ok": False, "code": prepared.get("code")},
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            return {**prepared, "external_ai_called": False}

        # 예상 비용 (pricing 기반, 호출 0)
        est = calculate_cost(
            self._session,
            provider_code=row.provider_code or "mock",
            model=row.requested_model or "mock-v1",
            input_tokens=row.max_tokens,
            output_tokens=row.max_tokens,
        )
        row.estimated_max_cost = est.get("estimated_cost")
        row.rendered_prompt_hash = prepared.get("rendered_prompt_hash")
        self._svc._event(
            request_id,
            event_type="AI_EXECUTION_DRY_RUN_COMPLETED",
            actor=actor,
            detail={
                "ok": True,
                "provider": row.provider_code,
                "estimated_max_cost": row.estimated_max_cost,
                "external_ai_called": False,
            },
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {
            "ok": True,
            "request": self._svc._public_request(row),
            "provider_candidate": row.provider_code,
            "capabilities_ok": True,
            "rendered_prompt_hash": row.rendered_prompt_hash,
            "estimated_max_tokens": row.max_tokens * 2,
            "estimated_max_cost": row.estimated_max_cost,
            "cost_status": est.get("cost_calculation_status"),
            "warnings": prepared.get("warnings") or [],
            "external_ai_called": False,
        }

    async def execute(
        self,
        request_id: int,
        *,
        actor: str,
        confirm: bool = False,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        row = self._session.get(AIExecutionRequestEntity, request_id)
        if row is None:
            raise AIExecutionError("NOT_FOUND", "Execution not found")
        if expected_version is not None and row.lock_version != expected_version:
            raise AIExecutionError("VERSION_CONFLICT", "Optimistic lock conflict")
        if row.status not in {
            RequestStatus.READY.value,
            RequestStatus.QUEUED.value,
        }:
            raise AIExecutionError(
                "INVALID_STATE",
                f"Cannot execute from status {row.status}",
            )

        mode = ExecutionMode(row.execution_mode)
        if mode == ExecutionMode.DRY_RUN:
            raise AIExecutionError(
                "INVALID_MODE", "Use dry-run endpoint for DRY_RUN mode"
            )
        if mode == ExecutionMode.EXTERNAL and not confirm:
            raise AIExecutionError(
                "CONFIRM_REQUIRED",
                "EXTERNAL execution requires confirm=true",
            )

        # Budget guard (요청 한도)
        if row.budget_limit is not None and row.estimated_max_cost is not None:
            if row.estimated_max_cost > row.budget_limit:
                self._svc._event(
                    request_id,
                    event_type="AI_EXECUTION_BUDGET_BLOCKED",
                    actor=actor,
                    detail={"budget_limit": row.budget_limit},
                    correlation_id=row.correlation_id,
                )
                self._session.commit()
                raise AIExecutionError("BUDGET_BLOCKED", "Estimated cost exceeds budget")

        # 일일 한도 (간단: system estimated cost sum)
        if not self._budget_ok(row):
            self._svc._event(
                request_id,
                event_type="AI_EXECUTION_BUDGET_BLOCKED",
                actor=actor,
                detail={"scope": "daily"},
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AIExecutionError("BUDGET_BLOCKED", "Daily budget exceeded")

        owner = f"{actor}:{uuid4().hex[:8]}"
        if not self._svc.acquire_lease(row, owner=owner):
            raise AIExecutionError("LEASE_HELD", "Another execute is in progress")

        self._svc._transition(
            row,
            RequestStatus.RUNNING.value,
            actor=actor,
            event_type="AI_EXECUTION_STARTED",
            detail={"mode": mode.value, "provider": row.provider_code},
        )
        row.started_at = _now()
        if mode == ExecutionMode.EXTERNAL:
            row.approved_by = actor
        self._session.commit()  # 외부 호출 전 커밋

        prepared = self._prepare(row)
        if not prepared["ok"]:
            return self._fail(
                row,
                actor=actor,
                code=prepared.get("code") or "PREPARE_FAILED",
                message=prepared.get("message") or "prepare failed",
                blocked=prepared.get("blocked", False),
            )

        row.rendered_prompt_hash = prepared.get("rendered_prompt_hash")
        self._session.commit()

        # Provider 체인
        providers = self._resolve_providers(row, mode)
        attempt = 0
        last_error: dict[str, Any] | None = None
        total_calls = 0

        for provider_code in providers:
            retries = int(row.retry_max) if provider_code == providers[0] else 0
            for retry_i in range(retries + 1):
                if self._svc.is_cancel_requested(request_id):
                    return self._finalize_cancel(row, actor=actor)

                if total_calls >= MAX_TOTAL_PROVIDER_CALLS:
                    break

                attempt += 1
                total_calls += 1
                run = AIExecutionRunEntity(
                    execution_request_id=request_id,
                    attempt_no=attempt,
                    provider_code=provider_code,
                    model=row.requested_model or "",
                    status=RunStatus.STARTED.value,
                    started_at=_now(),
                    retry_reason=(
                        f"retry#{retry_i}" if retry_i else None
                    ),
                    fallback_reason=(
                        "fallback"
                        if provider_code != providers[0]
                        else None
                    ),
                )
                self._session.add(run)
                self._session.flush()
                self._svc._event(
                    request_id,
                    event_type="AI_EXECUTION_RUN_STARTED",
                    actor=actor,
                    run_id=run.execution_run_id,
                    detail={"provider": provider_code, "attempt": attempt},
                    correlation_id=row.correlation_id,
                )
                self._session.commit()

                # 실제 호출 (트랜잭션 밖)
                call = await self._call_provider(
                    provider_code=provider_code,
                    model=row.requested_model,
                    messages=prepared["messages"],
                    max_tokens=row.max_tokens,
                    temperature=row.temperature,
                    timeout_sec=row.timeout_sec,
                )

                # 결과 기록
                self._session.refresh(row)
                if self._svc.is_cancel_requested(request_id):
                    # 늦은 성공이어도 CANCELLED 덮어쓰기 금지
                    run.status = RunStatus.CANCELLED.value
                    run.completed_at = _now()
                    run.sanitized_error = "cancelled_after_call"
                    run.latency_ms = call.get("latency_ms")
                    self._session.commit()
                    return self._finalize_cancel(row, actor=actor)

                run.latency_ms = call.get("latency_ms")
                run.input_tokens = call.get("input_tokens")
                run.output_tokens = call.get("output_tokens")
                run.total_tokens = call.get("total_tokens")
                run.finish_reason = call.get("finish_reason")
                run.model = call.get("model") or run.model
                run.circuit_state = call.get("circuit_state")
                cost = calculate_cost(
                    self._session,
                    provider_code=provider_code,
                    model=run.model,
                    input_tokens=run.input_tokens,
                    output_tokens=run.output_tokens,
                )
                run.estimated_cost = cost.get("estimated_cost")
                run.currency = cost.get("currency") or "USD"
                run.cost_calculation_status = cost[
                    "cost_calculation_status"
                ]
                run.pricing_version = cost.get("pricing_version")
                run.completed_at = _now()

                if not call.get("ok"):
                    run.status = (
                        RunStatus.TIMED_OUT.value
                        if call.get("timed_out")
                        else RunStatus.PROVIDER_FAILED.value
                    )
                    run.error_code = call.get("error_code")
                    run.sanitized_error = (call.get("error_message") or "")[:500]
                    last_error = call
                    self._svc._event(
                        request_id,
                        event_type="AI_EXECUTION_RUN_FAILED",
                        actor=actor,
                        run_id=run.execution_run_id,
                        detail={
                            "error_code": run.error_code,
                            "retryable": call.get("retryable"),
                        },
                        correlation_id=row.correlation_id,
                    )
                    self._session.commit()
                    if not call.get("retryable"):
                        break  # 다음 provider (fallback)로
                    continue

                run.status = RunStatus.PROVIDER_SUCCEEDED.value
                self._svc._event(
                    request_id,
                    event_type="AI_EXECUTION_RUN_SUCCEEDED",
                    actor=actor,
                    run_id=run.execution_run_id,
                    detail={"tokens": run.total_tokens},
                    correlation_id=row.correlation_id,
                )
                self._session.commit()

                # Validation
                validation = self._validate_response(row, call.get("content") or "")
                if validation["status"] in {"INVALID", "BLOCKED"}:
                    run.status = RunStatus.VALIDATION_FAILED.value
                    self._svc._event(
                        request_id,
                        event_type=(
                            "AI_EXECUTION_POLICY_BLOCKED"
                            if validation["status"] == "BLOCKED"
                            else "AI_EXECUTION_VALIDATION_FAILED"
                        ),
                        actor=actor,
                        run_id=run.execution_run_id,
                        detail={
                            "code": validation.get("code"),
                            "status": validation["status"],
                        },
                        correlation_id=row.correlation_id,
                    )
                    self._session.commit()
                    # Schema/Policy 실패는 자동 재호출 금지
                    return self._complete_validation_failure(
                        row,
                        run,
                        actor=actor,
                        validation=validation,
                    )

                run.status = RunStatus.VALIDATION_SUCCEEDED.value
                run.status = RunStatus.COMPLETED.value
                self._save_result(row, run, validation)
                target = (
                    RequestStatus.SUCCEEDED_WITH_WARNINGS.value
                    if validation["status"] == "VALID_WITH_WARNINGS"
                    else RequestStatus.SUCCEEDED.value
                )
                self._svc._transition(
                    row,
                    target,
                    actor=actor,
                    event_type="AI_EXECUTION_COMPLETED",
                    detail={"validation": validation["status"]},
                )
                row.completed_at = _now()
                row.lease_owner = None
                row.lease_expires_at = None
                self._svc._event(
                    request_id,
                    event_type="AI_EXECUTION_VALIDATION_SUCCEEDED",
                    actor=actor,
                    run_id=run.execution_run_id,
                    detail={"status": validation["status"]},
                    correlation_id=row.correlation_id,
                )
                self._svc._event(
                    request_id,
                    event_type="AI_EXECUTION_COST_CALCULATED",
                    actor=actor,
                    run_id=run.execution_run_id,
                    detail={
                        "estimated_cost": run.estimated_cost,
                        "cost_status": run.cost_calculation_status,
                    },
                    correlation_id=row.correlation_id,
                )
                self._session.commit()
                return {
                    "ok": True,
                    "request": self._svc._public_request(row),
                    "result": self._svc.get_result(request_id),
                    "runs": self._svc.list_runs(request_id),
                    "external_ai_called": mode == ExecutionMode.EXTERNAL,
                    "mock_called": mode == ExecutionMode.MOCK,
                }

            # non-retryable failed → try fallback if enabled
            if not row.fallback_enabled:
                break

        # 모든 시도 실패
        return self._fail(
            row,
            actor=actor,
            code=(last_error or {}).get("error_code") or "ALL_ATTEMPTS_FAILED",
            message=(last_error or {}).get("error_message") or "all attempts failed",
            timed_out=bool((last_error or {}).get("timed_out")),
        )

    def _prepare(self, row: AIExecutionRequestEntity) -> dict[str, Any]:
        variables = dict(row.input_payload_sanitized or {})
        warnings: list[str] = []

        # Prompt version (optional for CHAT plain)
        system = (
            "You are a helpful assistant. Respond with JSON only. "
            "Never execute trades, change LIVE/ARM, or request secrets."
        )
        user_tmpl = "{{text}}"
        var_schema: dict[str, Any] | None = {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        }
        capabilities: list[str] = ["JSON"]

        if row.prompt_version_id:
            ver = self._session.get(
                AIPromptTemplateVersionEntity, row.prompt_version_id
            )
            if ver is None:
                return {
                    "ok": False,
                    "code": "PROMPT_VERSION_NOT_FOUND",
                    "message": "prompt version missing",
                }
            tmpl = self._session.get(
                AIPromptTemplateEntity, ver.prompt_template_id
            )
            if tmpl is None or tmpl.status != "ACTIVE":
                # DRAFT prompt 차단 (ACTIVE template 필요)
                if tmpl is None or tmpl.status == "DRAFT":
                    return {
                        "ok": False,
                        "code": "PROMPT_NOT_ACTIVE",
                        "message": "Prompt template must be ACTIVE",
                        "blocked": True,
                    }
            if row.task_type != tmpl.task_type and tmpl.task_type:
                # allow CHAT with SUMMARIZE template mismatch? require match
                if tmpl.task_type != row.task_type:
                    return {
                        "ok": False,
                        "code": "TASK_TYPE_MISMATCH",
                        "message": "template task_type mismatch",
                    }
            system = ver.system_template
            user_tmpl = ver.user_template
            var_schema = ver.variable_schema
            capabilities = list(ver.required_capabilities or ["JSON"])
            if not row.output_schema_id and ver.output_schema_id:
                row.output_schema_id = ver.output_schema_id

        # Schema / Policy ACTIVE 검사
        if row.output_schema_id:
            schema = self._session.get(
                AIOutputSchemaEntity, row.output_schema_id
            )
            if schema is None or schema.status != "ACTIVE":
                return {
                    "ok": False,
                    "code": "SCHEMA_NOT_ACTIVE",
                    "message": "Output schema must be ACTIVE",
                    "blocked": True,
                }

        for pid in row.policy_ids or []:
            pol = self._session.get(AIPolicyDefinitionEntity, int(pid))
            if pol is None or pol.status != "ACTIVE":
                return {
                    "ok": False,
                    "code": "POLICY_NOT_ACTIVE",
                    "message": f"Policy {pid} not ACTIVE",
                    "blocked": True,
                }

        # CHAT 기본 입력 매핑
        if "text" not in variables and "content" in variables:
            variables["text"] = variables["content"]
        if row.task_type == "SUMMARIZE" and "text" not in variables:
            variables["text"] = str(variables.get("content") or "")

        try:
            if var_schema:
                validate_variables(variables, var_schema)
            allowed = set((var_schema or {}).get("properties", {}).keys()) or set(
                variables.keys()
            )
            system_r = render_template(
                system, variables, allowed_keys=allowed, field="system"
            )
            user_r = render_template(
                user_tmpl, variables, allowed_keys=allowed, field="user"
            )
        except (AIInputValidationError, PromptRenderError) as exc:
            return {
                "ok": False,
                "code": getattr(exc, "code", "PREPARE_FAILED"),
                "message": str(exc),
            }

        full = f"[SYSTEM]\n{system_r}\n\n[USER]\n{user_r}"
        sec = inspect_text_security(full)
        if sec["blocked"]:
            return {
                "ok": False,
                "code": "PROMPT_INJECTION_OR_SAFETY",
                "message": "Rendered prompt blocked by core safety",
                "blocked": True,
            }

        # Provider capability (CHAT)
        manager = get_ai_manager()
        provider_code = row.provider_code or "mock"
        provider = manager.get_provider(provider_code)
        if provider is None:
            return {
                "ok": False,
                "code": "PROVIDER_NOT_LOADED",
                "message": f"Provider {provider_code} not in runtime",
                "blocked": True,
            }
        cfg = manager.registry.get_config(provider_code)
        if cfg and not cfg.enabled and provider_code != "mock":
            return {
                "ok": False,
                "code": "PROVIDER_DISABLED",
                "message": "Provider disabled",
                "blocked": True,
            }

        # EXTERNAL: credential VERIFIED 필요 (mock/ollama 제외)
        if ExecutionMode(row.execution_mode) == ExecutionMode.EXTERNAL:
            if provider_code not in {"mock", "ollama"}:
                from stock_platform.ai.providers.management_entities import (
                    AIProviderConfigurationEntity,
                    AIProviderCredentialEntity,
                    NO_SECRET_PROVIDERS,
                )

                conf = self._session.scalar(
                    select(AIProviderConfigurationEntity).where(
                        AIProviderConfigurationEntity.provider_code
                        == provider_code
                    )
                )
                if conf is None or not conf.enabled:
                    return {
                        "ok": False,
                        "code": "PROVIDER_DISABLED",
                        "message": "DB provider not enabled",
                        "blocked": True,
                    }
                if provider_code not in NO_SECRET_PROVIDERS:
                    cred = self._session.scalar(
                        select(AIProviderCredentialEntity).where(
                            AIProviderCredentialEntity.provider_configuration_id
                            == conf.provider_configuration_id,
                            AIProviderCredentialEntity.is_active.is_(True),
                        )
                    )
                    if cred is None or cred.status != "VERIFIED":
                        return {
                            "ok": False,
                            "code": "CREDENTIAL_NOT_VERIFIED",
                            "message": "VERIFIED credential required",
                            "blocked": True,
                        }

        rendered_hash = hashlib.sha256(full.encode("utf-8")).hexdigest()
        return {
            "ok": True,
            "messages": [
                {"role": "system", "content": system_r},
                {"role": "user", "content": user_r},
            ],
            "rendered_prompt_hash": rendered_hash,
            "warnings": warnings,
            "capabilities": capabilities,
        }

    def _resolve_providers(
        self, row: AIExecutionRequestEntity, mode: ExecutionMode
    ) -> list[str]:
        primary = row.provider_code or "mock"
        if mode == ExecutionMode.MOCK:
            return ["mock"]
        chain = [primary]
        if row.fallback_enabled and primary != "mock":
            chain.append("mock")  # 외부→외부 fallback은 이번 STEP 기본 금지
        return chain

    async def _call_provider(
        self,
        *,
        provider_code: str,
        model: str | None,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout_sec: float,
    ) -> dict[str, Any]:
        manager = get_ai_manager()
        provider = manager.get_provider(provider_code)
        if provider is None:
            return {
                "ok": False,
                "error_code": "PROVIDER_MISSING",
                "error_message": "provider not loaded",
                "retryable": False,
            }

        # attempt당 1회 — Manager 내부 retry 우회
        req = AIChatRequest(
            messages=[
                ChatMessage(role=m["role"], content=m["content"]) for m in messages
            ],
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
        )
        started = time.perf_counter()
        try:
            # circuit 체크
            circuit = manager._circuit_for(provider_code)
            if not circuit.allow():
                return {
                    "ok": False,
                    "error_code": "CIRCUIT_OPEN",
                    "error_message": "circuit open",
                    "retryable": False,
                    "circuit_state": circuit.state.value,
                    "latency_ms": 0,
                }
            response = await asyncio.wait_for(
                provider.chat(req),
                timeout=max(1.0, float(timeout_sec)),
            )
            latency = (time.perf_counter() - started) * 1000.0
            if response.ok:
                circuit.record_success()
                manager._metrics[provider_code].record(
                    ok=True,
                    latency_ms=latency,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                )
                manager.external_call_counter += (
                    0 if provider_code == "mock" else 1
                )
                return {
                    "ok": True,
                    "content": response.content,
                    "model": response.model,
                    "latency_ms": round(latency, 3),
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "finish_reason": (
                        response.finish_reason.value
                        if response.finish_reason
                        else None
                    ),
                    "circuit_state": circuit.state.value,
                }
            circuit.record_failure()
            code = response.error.code if response.error else "ERROR"
            retryable = bool(response.error and response.error.retryable)
            return {
                "ok": False,
                "error_code": code,
                "error_message": (
                    response.error.message if response.error else "error"
                )[:300],
                "retryable": retryable and code not in {"UNAUTHORIZED", "FORBIDDEN"},
                "latency_ms": round(latency, 3),
                "circuit_state": circuit.state.value,
            }
        except TimeoutError:
            manager._circuit_for(provider_code).record_failure()
            return {
                "ok": False,
                "error_code": "TIMEOUT",
                "error_message": "provider timeout",
                "retryable": True,
                "timed_out": True,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        except Exception as exc:  # noqa: BLE001
            manager._circuit_for(provider_code).record_failure()
            return {
                "ok": False,
                "error_code": type(exc).__name__,
                "error_message": str(exc)[:300],
                "retryable": False,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }

    def _validate_response(
        self, row: AIExecutionRequestEntity, content: str
    ) -> dict[str, Any]:
        json_schema = None
        schema_version = None
        expected_task = row.task_type
        if row.output_schema_id:
            schema = self._session.get(
                AIOutputSchemaEntity, row.output_schema_id
            )
            if schema:
                json_schema = schema.json_schema
                schema_version = schema.schema_version
                expected_task = schema.task_type

        policy_rules = None
        enforcement = "BLOCK"
        if row.policy_ids:
            pol = self._session.get(
                AIPolicyDefinitionEntity, int(row.policy_ids[0])
            )
            if pol:
                policy_rules = pol.rules
                enforcement = pol.enforcement_mode

        # Mock/비구조화 응답 → Safe Envelope로 정규화
        text = (content or "").strip()
        needs_wrap = True
        if text.startswith("{") and '"task_type"' in text:
            needs_wrap = False
        if needs_wrap:
            if expected_task == "SUMMARIZE":
                result_body: dict[str, Any] = {
                    "summary": text[:4000],
                    "key_points": [],
                }
            elif expected_task == "NEWS_ANALYSIS":
                result_body = {
                    "sentiment": "NEUTRAL",
                    "importance": "LOW",
                    "market_relevance": "UNKNOWN",
                    "summary": text[:4000],
                    "event_summary": text[:500],
                    "key_facts": [],
                    "risks": [],
                    "related_symbols": [],
                    "topics": [],
                }
            elif expected_task == "DISCLOSURE_ANALYSIS":
                result_body = {
                    "event_importance": "UNKNOWN",
                    "disclosure_category": "OTHER",
                    "correction_status": "UNKNOWN",
                    "executive_summary": text[:4000],
                    "key_changes": [],
                    "financial_impacts": [],
                    "risks": [],
                    "related_symbols": [],
                }
            elif expected_task == "CHART_ANALYSIS":
                result_body = {
                    "trend": "UNCERTAIN",
                    "trend_strength": "UNKNOWN",
                    "momentum": "UNKNOWN",
                    "volatility": "UNKNOWN",
                    "volume_condition": "UNKNOWN",
                    "summary": text[:4000],
                    "support_levels": [],
                    "resistance_levels": [],
                    "notable_patterns": [],
                    "indicator_interpretations": [],
                    "bullish_factors": [],
                    "bearish_factors": [],
                    "uncertainty_factors": [],
                    "indicators_used": [],
                }
            elif expected_task == "MARKET_ANALYSIS":
                result_body = {
                    "market_regime": "UNKNOWN",
                    "breadth": "UNKNOWN",
                    "volatility_environment": "UNKNOWN",
                    "liquidity_condition": "UNKNOWN",
                    "volume_condition": "UNKNOWN",
                    "executive_summary": text[:4000],
                    "major_drivers": [],
                    "leading_groups": [],
                    "lagging_groups": [],
                    "risk_factors": [],
                    "positive_factors": [],
                    "uncertainty_factors": [],
                }
            else:
                result_body = {"message": text[:4000]}
            wrapped = {
                "schema_version": schema_version or "1.0",
                "task_type": expected_task,
                "confidence": 0.5,
                "reasoning_summary": "normalized response",
                "result": result_body,
                "warnings": ["normalized_for_validation"],
                "citations": [],
            }
            if expected_task == "CHAT" or json_schema is None:
                return {
                    "status": "VALID_WITH_WARNINGS",
                    "code": "OK",
                    "message": "normalized",
                    "warnings": ["normalized_for_validation"],
                    "data": wrapped,
                }
            text = json.dumps(wrapped, ensure_ascii=False)

        return validate_ai_output(
            raw=text,
            json_schema=json_schema if expected_task != "CHAT" else None,
            expected_task_type=expected_task,
            expected_schema_version=(
                schema_version if expected_task != "CHAT" else None
            ),
            policy_rules=policy_rules,
            enforcement_mode=enforcement,
        )

    def _save_result(
        self,
        row: AIExecutionRequestEntity,
        run: AIExecutionRunEntity,
        validation: dict[str, Any],
    ) -> None:
        data = validation.get("data") or {}
        payload = sanitize_for_log(data) if isinstance(data, dict) else {}
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        existing = self._session.scalar(
            select(AIExecutionResultEntity).where(
                AIExecutionResultEntity.execution_request_id
                == row.execution_request_id
            )
        )
        if existing:
            return
        self._session.add(
            AIExecutionResultEntity(
                execution_request_id=row.execution_request_id,
                execution_run_id=run.execution_run_id,
                validation_status=validation["status"],
                schema_version=str(data.get("schema_version") or "")
                if isinstance(data, dict)
                else None,
                result_payload=payload,
                result_hash=hashlib.sha256(raw.encode()).hexdigest(),
                confidence=(
                    float(data["confidence"])
                    if isinstance(data, dict) and data.get("confidence") is not None
                    else None
                ),
                reasoning_summary=(
                    str(data.get("reasoning_summary") or "")[:2000]
                    if isinstance(data, dict)
                    else None
                ),
                warnings=list(data.get("warnings") or [])
                if isinstance(data, dict)
                else validation.get("warnings"),
                citations=list(data.get("citations") or [])
                if isinstance(data, dict)
                else [],
                policy_findings=list(validation.get("hits") or []),
                raw_response_retained=False,
            )
        )

    def _complete_validation_failure(
        self,
        row: AIExecutionRequestEntity,
        run: AIExecutionRunEntity,
        *,
        actor: str,
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        target = (
            RequestStatus.BLOCKED.value
            if validation.get("status") == "BLOCKED"
            else RequestStatus.FAILED.value
        )
        # CANCEL_REQUESTED면 덮어쓰지 않음
        if row.status == RequestStatus.CANCEL_REQUESTED.value:
            return self._finalize_cancel(row, actor=actor)
        self._svc._transition(
            row,
            target,
            actor=actor,
            event_type="AI_EXECUTION_COMPLETED",
            detail={
                "validation": validation.get("status"),
                "code": validation.get("code"),
            },
        )
        row.completed_at = _now()
        row.sanitized_error = (validation.get("message") or "")[:500]
        row.lease_owner = None
        row.lease_expires_at = None
        # INVALID/BLOCKED는 업무 결과로 저장하지 않음 (메타만)
        self._session.commit()
        return {
            "ok": False,
            "request": self._svc._public_request(row),
            "validation": {
                "status": validation.get("status"),
                "code": validation.get("code"),
            },
            "result": None,
            "business_deliverable": False,
        }

    def _fail(
        self,
        row: AIExecutionRequestEntity,
        *,
        actor: str,
        code: str,
        message: str,
        blocked: bool = False,
        timed_out: bool = False,
    ) -> dict[str, Any]:
        if row.status == RequestStatus.CANCEL_REQUESTED.value:
            return self._finalize_cancel(row, actor=actor)
        if row.status in {
            RequestStatus.SUCCEEDED.value,
            RequestStatus.SUCCEEDED_WITH_WARNINGS.value,
            RequestStatus.CANCELLED.value,
        }:
            return {"ok": False, "request": self._svc._public_request(row)}

        if timed_out:
            target = RequestStatus.TIMED_OUT.value
            event = "AI_EXECUTION_TIMED_OUT"
        elif blocked:
            target = RequestStatus.BLOCKED.value
            event = "AI_EXECUTION_POLICY_BLOCKED"
        else:
            target = RequestStatus.FAILED.value
            event = "AI_EXECUTION_COMPLETED"

        if row.status != RequestStatus.RUNNING.value and row.status not in {
            RequestStatus.READY.value,
            RequestStatus.QUEUED.value,
        }:
            # already terminal-ish
            pass
        else:
            if row.status != RequestStatus.RUNNING.value:
                # READY에서 바로 fail 가능하도록 RUNNING 경유 없이 전이 허용 확장
                try:
                    self._svc._transition(
                        row,
                        target,
                        actor=actor,
                        event_type=event,
                        detail={"code": code},
                    )
                except AIExecutionError:
                    # READY→FAILED는 state machine에 있음
                    raise
            else:
                self._svc._transition(
                    row,
                    target,
                    actor=actor,
                    event_type=event,
                    detail={"code": code},
                )
        row.completed_at = _now()
        row.sanitized_error = f"{code}: {message}"[:500]
        row.lease_owner = None
        row.lease_expires_at = None
        self._session.commit()
        return {
            "ok": False,
            "request": self._svc._public_request(row),
            "code": code,
            "message": message,
            "business_deliverable": False,
        }

    def _finalize_cancel(
        self, row: AIExecutionRequestEntity, *, actor: str
    ) -> dict[str, Any]:
        if row.status != RequestStatus.CANCELLED.value:
            if row.status == RequestStatus.CANCEL_REQUESTED.value:
                prev = row.status
                row.status = RequestStatus.CANCELLED.value
                row.lock_version = int(row.lock_version) + 1
                row.cancelled_at = _now()
                row.completed_at = _now()
                row.lease_owner = None
                row.lease_expires_at = None
                self._svc._event(
                    row.execution_request_id,
                    event_type="AI_EXECUTION_CANCELLED",
                    actor=actor,
                    previous=prev,
                    new=row.status,
                    detail={"cost_refund": False},
                    correlation_id=row.correlation_id,
                )
            elif row.status == RequestStatus.RUNNING.value:
                self._svc._transition(
                    row,
                    RequestStatus.CANCELLED.value,
                    actor=actor,
                    event_type="AI_EXECUTION_CANCELLED",
                    detail={"cost_refund": False},
                )
                row.cancelled_at = _now()
                row.completed_at = _now()
                row.lease_owner = None
        self._session.commit()
        return {
            "ok": False,
            "cancelled": True,
            "request": self._svc._public_request(row),
            "cost_refund_guaranteed": False,
        }

    def _budget_ok(self, row: AIExecutionRequestEntity) -> bool:
        """간단 일일 한도 — settings 없으면 통과."""

        try:
            from stock_platform.common.settings import get_settings

            settings = get_settings()
            daily = float(
                getattr(settings, "ai_execution_daily_budget_usd", 0) or 0
            )
        except Exception:  # noqa: BLE001
            daily = 0.0
        if daily <= 0:
            return True
        today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = self._session.scalar(
            select(
                func.coalesce(func.sum(AIExecutionRunEntity.estimated_cost), 0)
            ).where(AIExecutionRunEntity.created_at >= today)
        )
        return float(spent or 0) < daily
