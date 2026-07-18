from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from stock_platform.api.exception_handlers import register_exception_handlers
from stock_platform.api.lifecycle import application_lifecycle
from stock_platform.api.middleware import RequestContextMiddleware
from stock_platform.api.router import api_router
from stock_platform.common.logger import configure_logging


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
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "service": "stock-platform",
        "status": "running",
    }


app.add_middleware(RequestContextMiddleware)
app.include_router(api_router)
register_exception_handlers(app)
