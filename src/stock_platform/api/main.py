from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stock_platform.api.exception_handlers import register_exception_handlers
from stock_platform.api.lifecycle import application_lifecycle
from stock_platform.api.middleware import RequestContextMiddleware
from stock_platform.api.router import api_router
from stock_platform.api.security_middleware import SecurityHeadersMiddleware
from stock_platform.common.logger import configure_logging
from stock_platform.common.settings import get_settings


def _cors_allow_origins() -> list[str]:
    """CORS Allow-Origin 목록 (쉼표 구분 env)."""

    settings = get_settings()
    raw = settings.cors_allow_origins.strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    # 로컬 기본값
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def _cors_allow_methods() -> list[str]:
    return ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _cors_allow_headers() -> list[str]:
    return [
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Request-ID",
        "X-Admin-API-Key",
        "X-Telegram-Bot-Api-Secret-Token",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await application_lifecycle.startup()

    try:
        yield
    finally:
        await application_lifecycle.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    hide_docs = settings.is_production_env

    application = FastAPI(
        title="Stock Platform API",
        description="AI 기반 주식·암호화폐 자동매매 플랫폼",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if hide_docs else "/docs",
        redoc_url=None if hide_docs else "/redoc",
        openapi_url=None if hide_docs else "/openapi.json",
    )

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        from fastapi.openapi.utils import get_openapi

        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        schema.setdefault("components", {}).setdefault(
            "securitySchemes",
            {},
        ).update(
            {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                },
                "AdminApiKey": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Admin-API-Key",
                },
            }
        )
        # 전역 security 힌트 (엔드포인트별 Depends가 실제 강제)
        schema["security"] = [
            {"BearerAuth": []},
            {"AdminApiKey": []},
        ]
        # operationId 중복 검사
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for path, methods in (schema.get("paths") or {}).items():
            for method, op in methods.items():
                if not isinstance(op, dict):
                    continue
                op_id = op.get("operationId")
                if not op_id:
                    continue
                if op_id in seen:
                    duplicates.append(op_id)
                else:
                    seen[op_id] = f"{method.upper()} {path}"
        if duplicates:
            schema.setdefault("x-operation-id-duplicates", sorted(set(duplicates)))
        application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore[method-assign]

    @application.get("/")
    def root():
        return {
            "service": "stock-platform",
            "status": "running",
            "version": settings.app_version,
            "env": settings.app_env,
        }

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_credentials=True,
        allow_methods=_cors_allow_methods(),
        allow_headers=_cors_allow_headers(),
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.include_router(api_router)
    register_exception_handlers(application)
    return application


app = create_app()
