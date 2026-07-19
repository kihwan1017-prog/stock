from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stock_platform.api.exception_handlers import register_exception_handlers
from stock_platform.api.lifecycle import application_lifecycle
from stock_platform.api.middleware import RequestContextMiddleware
from stock_platform.api.router import api_router
from stock_platform.common.logger import configure_logging

# 관리자 Next.js(dev) Origin — 운영에서는 환경별 allow_origins로 제한할 것
ADMIN_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await application_lifecycle.startup()

    try:
        yield
    finally:
        await application_lifecycle.shutdown()


app = FastAPI(
    title="Stock Platform API",
    description="AI 기반 주식·암호화폐 자동매매 플랫폼",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "service": "stock-platform",
        "status": "running",
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=ADMIN_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
app.include_router(api_router)
register_exception_handlers(app)
