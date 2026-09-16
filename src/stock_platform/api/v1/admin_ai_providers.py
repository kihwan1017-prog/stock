"""STEP 11-2 — Admin AI Provider API (Read-only + 제한된 Test)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.errors import AIProviderError
from stock_platform.ai.providers.manager import get_ai_manager
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/providers",
    tags=["Admin AI Providers"],
    dependencies=[Depends(require_admin)],
)

MAX_PROMPT_LEN = 2000
MAX_TOKENS_CAP = 256
TEST_RATE_LIMIT = 10
TEST_RATE_WINDOW = 60.0


class ProviderTestRequest(BaseModel):
    prompt: str = Field(default="Return exactly: OK", max_length=MAX_PROMPT_LEN)
    model: str | None = Field(default=None, max_length=128)
    max_tokens: int = Field(default=32, ge=1, le=MAX_TOKENS_CAP)
    correlation_id: str | None = Field(default=None, max_length=64)


def _audit(
    session: Session,
    *,
    event_type: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


@router.get("")
def list_providers(
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    manager = get_ai_manager()
    return {
        "count": len(manager.list_providers()),
        "default_provider": (
            manager.registry.default_provider().provider_id
            if manager.registry.default_provider()
            else None
        ),
        "providers": manager.list_providers(),
        "metrics": manager.metrics_snapshot(),
    }


@router.get("/health")
async def providers_health(
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """캐시 우선 Health — 기본적으로 저비용/캐시."""

    manager = get_ai_manager()
    rows = await manager.health(use_cache=True, live_probe=False)
    return {
        "count": len(rows),
        "items": [row.to_dict() for row in rows],
        "from_cache": True,
    }


@router.get("/{provider_id}")
def get_provider(
    provider_id: str,
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    manager = get_ai_manager()
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_id}' not found",
        )
    cfg = manager.registry.get_config(provider_id)
    return {
        "provider": provider.describe(),
        "config": cfg.public_dict() if cfg else None,
        "metrics": manager.metrics_snapshot().get(provider_id),
        "circuit": manager._circuit_for(provider_id).snapshot(),
        "health_cache": manager._health_cache.get(provider_id),
    }


@router.post("/{provider_id}/initialize")
async def initialize_provider(
    provider_id: str,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    manager = get_ai_manager()
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    actor = admin_actor_label(user)
    _audit(
        session,
        event_type="AI_PROVIDER_INITIALIZE_REQUESTED",
        actor=actor,
        detail={"provider": provider_id},
    )
    try:
        await provider.initialize()
        _audit(
            session,
            event_type="AI_PROVIDER_INITIALIZED",
            actor=actor,
            detail={"provider": provider_id},
        )
        return {"ok": True, "provider_id": provider_id}
    except Exception as exc:  # noqa: BLE001
        _audit(
            session,
            event_type="AI_PROVIDER_INITIALIZE_FAILED",
            actor=actor,
            detail={"provider": provider_id, "error": type(exc).__name__},
        )
        raise HTTPException(status_code=500, detail="Initialize failed") from exc


@router.post("/{provider_id}/health-check")
async def health_check_provider(
    provider_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request,
        scope=f"ai-provider-health:{user.user_id}:{provider_id}",
        limit=TEST_RATE_LIMIT,
        window_seconds=TEST_RATE_WINDOW,
    )
    manager = get_ai_manager()
    if manager.get_provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    actor = admin_actor_label(user)
    rows = await manager.health(
        provider_id=provider_id,
        use_cache=False,
        live_probe=True,
    )
    row = rows[0] if rows else None
    _audit(
        session,
        event_type="AI_PROVIDER_HEALTH_CHECKED",
        actor=actor,
        detail={
            "provider": provider_id,
            "status": row.status.value if row else None,
            "latency_ms": row.latency_ms if row else None,
            "error_code": row.sanitized_error_code if row else None,
        },
    )
    return {"item": row.to_dict() if row else None}


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str,
    body: ProviderTestRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """수동 chat 테스트 — 전략 생성/주문 없음."""

    enforce_rate_limit(
        request,
        scope=f"ai-provider-test:{user.user_id}",
        limit=TEST_RATE_LIMIT,
        window_seconds=TEST_RATE_WINDOW,
    )
    enforce_rate_limit(
        request,
        scope=f"ai-provider-test-provider:{provider_id}",
        limit=TEST_RATE_LIMIT,
        window_seconds=TEST_RATE_WINDOW,
    )
    manager = get_ai_manager()
    if manager.get_provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    correlation_id = body.correlation_id or str(uuid4())
    actor = admin_actor_label(user)
    _audit(
        session,
        event_type="AI_PROVIDER_TEST_REQUESTED",
        actor=actor,
        detail={
            "provider": provider_id,
            "model": body.model,
            "max_tokens": body.max_tokens,
            "prompt_len": len(body.prompt),
            "correlation_id": correlation_id,
        },
    )
    try:
        result = await manager.test_provider(
            provider_id,
            prompt=body.prompt,
            model=body.model,
            max_tokens=body.max_tokens,
        )
    except AIProviderError as exc:
        _audit(
            session,
            event_type="AI_PROVIDER_TEST_FAILED",
            actor=actor,
            detail={
                "provider": provider_id,
                "correlation_id": correlation_id,
                "error_code": exc.code,
            },
        )
        if exc.code == "AUTH_FAILED":
            _audit(
                session,
                event_type="AI_PROVIDER_AUTH_FAILED",
                actor=actor,
                detail={"provider": provider_id},
            )
        raise HTTPException(status_code=400, detail=exc.code) from exc

    ok = bool((result.get("response") or {}).get("ok"))
    resp = result.get("response") or {}
    err = resp.get("error") or {}
    _audit(
        session,
        event_type=(
            "AI_PROVIDER_TEST_SUCCEEDED"
            if ok
            else "AI_PROVIDER_TEST_FAILED"
        ),
        actor=actor,
        detail={
            "provider": provider_id,
            "correlation_id": correlation_id,
            "latency_ms": resp.get("latency_ms"),
            "usage": resp.get("usage"),
            "error_code": err.get("code"),
            "success": ok,
        },
    )
    if err.get("code") == "RATE_LIMITED":
        _audit(
            session,
            event_type="AI_PROVIDER_RATE_LIMITED",
            actor=actor,
            detail={"provider": provider_id},
        )
    if err.get("code") == "CIRCUIT_OPEN":
        _audit(
            session,
            event_type="AI_PROVIDER_CIRCUIT_OPENED",
            actor=actor,
            detail={"provider": provider_id},
        )

    safe = sanitize_for_log(result)
    safe["correlation_id"] = correlation_id
    safe["limits"] = {
        "max_prompt_len": MAX_PROMPT_LEN,
        "max_tokens_cap": MAX_TOKENS_CAP,
        "estimated_cost": None,
    }
    return safe


# 하위 호환 — STEP 11-1 POST /test
@router.post("/test")
async def test_provider_legacy(
    body: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    provider_id = str(body.get("provider_id") or "mock")
    payload = ProviderTestRequest(
        prompt=str(body.get("prompt") or "Return exactly: OK")[:MAX_PROMPT_LEN],
        model=body.get("model"),
        max_tokens=int(body.get("max_tokens") or 32),
    )
    return await test_provider(
        provider_id=provider_id,
        body=payload,
        request=request,
        session=session,
        user=user,
    )
