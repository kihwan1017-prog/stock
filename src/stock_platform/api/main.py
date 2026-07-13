from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from stock_platform.api.router import api_router
from stock_platform.common.logger import configure_logging, logger

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