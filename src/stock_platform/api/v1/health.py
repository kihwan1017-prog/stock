from datetime import datetime, timezone

from fastapi import APIRouter, Response

from stock_platform.common.settings import get_settings
from stock_platform.operation.db_pool_monitor import (
    measure_db_latency_ms,
)
from stock_platform.operation.health_service import (
    SystemHealthService,
)
from stock_platform.operation.runtime_info import (
    build_system_identity,
)


router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("/live")
async def health_live():
    """Liveness — 프로세스만 살아 있으면 200 (의존성 미검사)."""

    identity = build_system_identity()
    return {
        "status": "UP",
        "check": "live",
        "uptime_seconds": identity["uptime_seconds"],
    }


@router.get("/ready")
async def health_ready(response: Response):
    """Readiness — DB 연결 가능 여부 (빠른 검사)."""

    status, latency_ms, error = measure_db_latency_ms()
    payload = {
        "status": status,
        "check": "ready",
        "database": {
            "status": status,
            "response_time_ms": latency_ms,
        },
    }
    if error:
        payload["database"]["message"] = error
        response.status_code = 503
    return payload


@router.get("")
async def health():
    """상세 컴포넌트 헬스.

    운영에서는 최소 정보만 공개 (DB status).
    상세는 Admin monitoring overview 사용.
    """

    settings = get_settings()
    if settings.is_production_env:
        status, latency_ms, error = measure_db_latency_ms()
        payload = {
            "status": status if status == "UP" else "DEGRADED",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": {
                "database": {
                    "status": status,
                    "response_time_ms": latency_ms,
                }
            },
        }
        if error:
            payload["components"]["database"]["message"] = "unavailable"
        return payload
    return await SystemHealthService().build()
