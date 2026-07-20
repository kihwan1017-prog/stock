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
