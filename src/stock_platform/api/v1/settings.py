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
    OllamaRoleModelUpdateRequest,
    SettingBatchUpdateRequest,
    SettingCategoryResponse,
    SettingHistoryResponse,
    SettingItemResponse,
)
from stock_platform.operation.setting_service import (
    AppSettingService,
    SettingError,
)
from stock_platform.common.settings import get_settings
from stock_platform.common.ttl_cache import process_ttl_cache
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    analysis_config,
    runtime_stats,
    teacher_config,
    trading_config,
)


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


def _installed_model_names(base_url: str) -> tuple[list[dict], list[str]]:
    """설치된 모델 목록 — tags 캐시 재사용. inference 호출 없음."""

    cache_key = f"ollama:tags:{base_url}"

    def _fetch_tags() -> dict:
        response = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        response.raise_for_status()
        return response.json()

    payload = process_ttl_cache.get_or_set(
        cache_key,
        _fetch_tags,
        ttl_seconds=45.0,
    )
    models = [
        {
            "name": item.get("name"),
            "size": item.get("size"),
            "modified_at": item.get("modified_at"),
        }
        for item in (payload.get("models") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    names = [str(m["name"]) for m in models]
    return models, names


def _role_config_payload(
    service: AppSettingService,
    *,
    installed: list[dict],
    installed_names: list[str],
) -> dict:
    """역할별 DB/ENV/RUNTIME resolve — 코드 fallback semantics 그대로."""

    s = get_settings()
    a_cfg = analysis_config()
    t_cfg = trading_config()
    te_cfg = teacher_config()
    stats = runtime_stats()

    def _db(key: str) -> str:
        try:
            return str(service.get_raw_value(key) or "")
        except Exception:  # noqa: BLE001
            return ""

    analysis_db = _db("analysis_llm_model")
    trading_db = _db("trading_llm_model")
    teacher_db = _db("teacher_llm_model")
    fallback_db = _db("ollama_model")

    analysis_env = str(s.analysis_llm_model or "")
    trading_env = str(s.trading_llm_model or "")
    teacher_env = str(s.teacher_llm_model or "")
    fallback_env = str(s.ollama_model or "")

    analysis_rt = a_cfg.model
    trading_rt = t_cfg.model
    teacher_rt = te_cfg.model
    fallback_rt = fallback_env

    def _installed_flag(model: str) -> bool:
        return bool(model) and model in installed_names

    def _roles_for(model: str) -> list[str]:
        roles: list[str] = []
        if model == analysis_rt:
            roles.append("분석")
        if model == trading_rt:
            roles.append("매매 판단")
        if model == teacher_rt:
            roles.append("Teacher")
        if model == fallback_rt:
            roles.append("Fallback")
        return roles

    installed_friendly = [
        {
            "name": m["name"],
            "size_bytes": m.get("size"),
            "size_gb": (
                round(float(m["size"]) / (1024**3), 2)
                if isinstance(m.get("size"), (int, float))
                else None
            ),
            "modified_at": m.get("modified_at"),
            "roles": _roles_for(str(m["name"])),
            "installed": True,
        }
        for m in installed
    ]

    return {
        "schema": "ollama_role_models_v1",
        "ROLE_SETTINGS_SOT": "ENV_SETTINGS_WITH_DB_OVERLAY_ON_SAVE",
        "TRADING_LLM_MODE": "SHADOW",
        "TRADING_LLM_REAL_GATE": False,
        "base_url": str(
            service.get_typed_value("ollama_base_url")
        ).rstrip("/"),
        "ollama_timeout_seconds": {
            "DB_VALUE": _db("ollama_timeout_seconds"),
            "ENV_VALUE": s.ollama_timeout_seconds,
            "RUNTIME_RESOLVED_VALUE": s.ollama_timeout_seconds,
        },
        "ollama_temperature": {
            "DB_VALUE": _db("ollama_temperature"),
            "ENV_VALUE": s.ollama_temperature,
            "RUNTIME_RESOLVED_VALUE": s.ollama_temperature,
        },
        "ollama_keep_alive": {
            "DB_VALUE": _db("ollama_keep_alive"),
            "ENV_VALUE": s.ollama_keep_alive,
            "RUNTIME_RESOLVED_VALUE": s.ollama_keep_alive,
        },
        "roles": {
            "analysis": {
                "label": "분석 모델",
                "purpose": "시장/후보 분석",
                "description": (
                    "시장·기술지표·후보 정보를 빠르게 분석합니다."
                ),
                "SETTING": "analysis_llm_model",
                "DB_VALUE": analysis_db,
                "ENV_VALUE": analysis_env,
                "RUNTIME_RESOLVED_VALUE": analysis_rt,
                "FALLBACK_RULE": (
                    "empty → hardcoded 'qwen3:1.7b' "
                    "(not ollama_model)"
                ),
                "installed": _installed_flag(analysis_rt),
                "health": {
                    "calls": stats.get("analysis_calls"),
                    "ok": stats.get("analysis_ok"),
                    "timeouts": stats.get("analysis_timeout"),
                    "errors": stats.get("analysis_error"),
                    "median_latency_ms": stats.get(
                        "analysis_median_latency_ms"
                    ),
                },
            },
            "trading": {
                "label": "매매 판단 모델",
                "purpose": "BUY/HOLD/REDUCE 등 Trading 판단",
                "description": (
                    "분석 결과를 바탕으로 매수/보류/축소 판단을 생성합니다."
                ),
                "SETTING": "trading_llm_model",
                "DB_VALUE": trading_db,
                "ENV_VALUE": trading_env,
                "RUNTIME_RESOLVED_VALUE": trading_rt,
                "FALLBACK_RULE": (
                    "empty → hardcoded 'qwen3.5:2b' "
                    "(not ollama_model)"
                ),
                "mode": "SHADOW",
                "real_gate": False,
                "installed": _installed_flag(trading_rt),
                "health": {
                    "calls": stats.get("trading_shadow_calls"),
                    "ok": stats.get("trading_shadow_ok"),
                    "timeouts": stats.get("trading_shadow_timeout"),
                    "errors": stats.get("trading_shadow_error"),
                    "median_latency_ms": stats.get(
                        "trading_median_latency_ms"
                    ),
                },
            },
            "teacher": {
                "label": "Teacher 모델",
                "purpose": "conflict/low-confidence/오판 사례 검토",
                "description": (
                    "판단 충돌·낮은 신뢰도·오판 사례를 검토하여 "
                    "향후 학습 데이터를 만듭니다."
                ),
                "SETTING": "teacher_llm_model",
                "DB_VALUE": teacher_db,
                "ENV_VALUE": teacher_env,
                "RUNTIME_RESOLVED_VALUE": teacher_rt,
                "FALLBACK_RULE": "empty → ollama_model",
                "installed": _installed_flag(teacher_rt),
                "health": {
                    "calls": stats.get("teacher_calls"),
                    "ok": stats.get("teacher_ok"),
                    "timeouts": stats.get("teacher_timeout"),
                    "errors": stats.get("teacher_error"),
                    "median_latency_ms": stats.get(
                        "teacher_median_latency_ms"
                    ),
                },
            },
            "fallback": {
                "label": "기본/Fallback 모델",
                "purpose": "역할별 모델 미설정 시 fallback (Teacher)",
                "description": (
                    "역할별 모델을 사용할 수 없을 때 사용하는 기본 모델입니다. "
                    "Teacher 빈값 fallback 및 reference(ollama_model)."
                ),
                "SETTING": "ollama_model",
                "DB_VALUE": fallback_db,
                "ENV_VALUE": fallback_env,
                "RUNTIME_RESOLVED_VALUE": fallback_rt,
                "FALLBACK_RULE": "reference / Teacher empty fallback",
                "installed": _installed_flag(fallback_rt),
            },
        },
        "installed_models": installed_friendly,
        "installed_model_count": len(installed_friendly),
        "installed_model_names": installed_names,
    }


@ollama_router.get("/role-models")
def get_ollama_role_models(
    _: AuthenticatedUser = Depends(
        require_permission("settings:read")
    ),
    service: AppSettingService = Depends(get_setting_service),
    session: Session = Depends(get_db_session),
):
    """역할별 모델 + 설치 목록 + runtime telemetry (inference 없음)."""

    try:
        # 카탈로그 키 시드만 — 역할 값 변경 아님
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
        installed, names = _installed_model_names(base_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama 연결 실패: {exc}",
        ) from exc

    return _role_config_payload(
        service,
        installed=installed,
        installed_names=names,
    )


@ollama_router.put("/role-models")
def update_ollama_role_models(
    request: OllamaRoleModelUpdateRequest,
    actor: AuthenticatedUser = Depends(
        require_permission("settings:write")
    ),
    session: Session = Depends(get_db_session),
    service: AppSettingService = Depends(get_setting_service),
    audit: AuditLogService = Depends(get_audit_service),
):
    """역할별 모델 저장 — 설치 모델∈검증 후 DB+env 동기화. REAL gate 변경 없음."""

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
        _, installed_names = _installed_model_names(base_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama 연결 실패: {exc}",
        ) from exc

    selected = {
        "analysis_llm_model": request.analysis_llm_model.strip(),
        "trading_llm_model": request.trading_llm_model.strip(),
        "teacher_llm_model": (request.teacher_llm_model or "").strip(),
        "ollama_model": request.ollama_model.strip(),
    }
    # Teacher는 빈값 허용(→ ollama_model). 그 외는 설치 목록 필수.
    for key, model in selected.items():
        if key == "teacher_llm_model" and not model:
            continue
        if model not in installed_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{key}='{model}' 은 설치되지 않은 모델입니다. "
                    f"설치됨: {installed_names}"
                ),
            )

    try:
        changed = service.update_settings(
            [{"key": k, "value": v} for k, v in selected.items()],
            actor=actor.username,
            change_reason=request.change_reason
            or "ollama role model update",
        )
        audit.record(
            event_type="OLLAMA_ROLE_MODELS_UPDATE",
            actor=actor.username,
            detail={
                "changed_keys": [item["key"] for item in changed],
                "selected": selected,
                "TRADING_LLM_REAL_GATE": False,
            },
        )
        session.commit()
    except SettingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    installed, names = _installed_model_names(base_url)
    payload = _role_config_payload(
        service,
        installed=installed,
        installed_names=names,
    )
    payload["changed_keys"] = [item["key"] for item in changed]
    return payload
