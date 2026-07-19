from __future__ import annotations

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.operation.setting_repository import (
    AppSettingRepository,
)
from stock_platform.operation.setting_schemas import (
    SettingBatchUpdateRequest,
    SettingCategoryResponse,
    SettingHistoryResponse,
    SettingItemResponse,
)
from stock_platform.operation.setting_service import (
    AppSettingService,
    SettingError,
)
from stock_platform.common.ttl_cache import process_ttl_cache


router = APIRouter(
    prefix="/api/v1/settings",
    tags=["Settings"],
)


def get_setting_service(
    session: Session = Depends(get_db_session),
) -> AppSettingService:
    return AppSettingService(AppSettingRepository(session))


@router.get("/categories", response_model=list[SettingCategoryResponse])
def list_categories(
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
):
    return [
        SettingCategoryResponse(**item)
        for item in service.categories()
    ]


@router.get("", response_model=list[SettingItemResponse])
def list_settings(
    category: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
):
    try:
        items = service.list_settings(category=category)
        session.commit()
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return [SettingItemResponse(**item) for item in items]


@router.get("/history", response_model=list[SettingHistoryResponse])
def list_setting_history(
    setting_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
):
    rows = service.list_history(
        setting_key=setting_key,
        limit=limit,
    )
    return [SettingHistoryResponse(**row) for row in rows]


@router.get("/{key}", response_model=SettingItemResponse)
def get_setting(
    key: str,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
):
    try:
        item = service.get_setting(key)
        session.commit()
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return SettingItemResponse(**item)


@router.put("", response_model=list[SettingItemResponse])
def update_settings(
    request: SettingBatchUpdateRequest,
    actor: AuthenticatedUser = Depends(
        require_permission("settings:write")
    ),
    session: Session = Depends(get_db_session),
    service: AppSettingService = Depends(get_setting_service),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        changed = service.update_settings(
            [item.model_dump() for item in request.items],
            actor=actor.username,
            change_reason=request.change_reason,
        )
        audit.record(
            event_type="SETTINGS_UPDATE",
            actor=actor.username,
            detail={
                "changed_keys": [
                    item["key"] for item in changed
                ],
                "change_reason": request.change_reason,
            },
        )
        session.commit()
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return [SettingItemResponse(**item) for item in changed]


# ---- Ollama helpers (AI 설정 연계) ----

ollama_router = APIRouter(
    prefix="/api/v1/ollama",
    tags=["Ollama"],
)


@ollama_router.get("/models")
def list_ollama_models(
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
    session: Session = Depends(get_db_session),
):
    try:
        service.ensure_seeded()
        session.commit()
        base_url = str(
            service.get_typed_value("ollama_base_url")
        ).rstrip("/")
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    try:
        cache_key = f"ollama:tags:{base_url}"

        def _fetch_tags() -> dict:
            response = httpx.get(
                f"{base_url}/api/tags",
                timeout=5.0,
            )
            response.raise_for_status()
            return response.json()

        payload = process_ttl_cache.get_or_set(
            cache_key,
            _fetch_tags,
            ttl_seconds=45.0,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama 연결 실패: {exc}",
        ) from exc

    models = payload.get("models") or []
    return {
        "base_url": base_url,
        "models": [
            {
                "name": item.get("name"),
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
            }
            for item in models
            if isinstance(item, dict)
        ],
    }


@ollama_router.get("/status")
def get_ollama_status(
    _: AuthenticatedUser = Depends(
        require_permission("system:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
    session: Session = Depends(get_db_session),
):
    """Ollama 연결 상태 + 기본 모델 설정 (모니터링용)."""

    try:
        service.ensure_seeded()
        session.commit()
        base_url = str(
            service.get_typed_value("ollama_base_url")
        ).rstrip("/")
        model = str(service.get_typed_value("ollama_model"))
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    try:
        cache_key = f"ollama:tags:{base_url}"

        def _fetch_tags() -> dict:
            response = httpx.get(
                f"{base_url}/api/tags",
                timeout=3.0,
            )
            response.raise_for_status()
            return response.json()

        payload = process_ttl_cache.get_or_set(
            cache_key,
            _fetch_tags,
            ttl_seconds=45.0,
        )
        models = payload.get("models") or []
        return {
            "status": "UP",
            "base_url": base_url,
            "configured_model": model,
            "model_count": len(models),
        }
    except Exception as exc:
        return {
            "status": "DOWN",
            "base_url": base_url,
            "configured_model": model,
            "model_count": 0,
            "message": str(exc),
        }


@ollama_router.get("/settings", response_model=list[SettingItemResponse])
def get_ollama_settings(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
):
    try:
        items = service.list_settings(category="ai")
        session.commit()
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return [SettingItemResponse(**item) for item in items]
