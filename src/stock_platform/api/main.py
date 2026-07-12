from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

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


@app.get("/health")
def health():
    return {
        "status": "UP",
    }


@app.get("/version")
def version():
    return {
        "version": "0.1.0",
    }