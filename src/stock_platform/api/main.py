from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from stock_platform.api.router import api_router
from stock_platform.common.logger import configure_logging, logger
from stock_platform.realtime.manager import realtime_manager


await realtime_manager.stop_all()

configure_logging()
logger.info("Stock Platform starting...")

app = FastAPI(
    title="Stock Platform API",
    description="AI 기반 주식·암호화폐 자동매매 플랫폼",
    version="0.1.0",
    default_response_class=ORJSONResponse,
)


@app.get("/")
def root():
    return {
        "service": "stock-platform",
        "status": "running",
    }


app.include_router(api_router)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from stock_platform.api.router import api_router
from stock_platform.common.logger import configure_logging, logger
from stock_platform.realtime.manager import realtime_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Stock Platform starting...")

    # 시작 시
    yield

    # 종료 시
    logger.info("Stopping realtime services...")
    await realtime_manager.stop_all()
    logger.info("Stock Platform stopped.")


app = FastAPI(
    title="Stock Platform API",
    description="AI 기반 주식·암호화폐 자동매매 플랫폼",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "service": "stock-platform",
        "status": "running",
    }


app.include_router(api_router)