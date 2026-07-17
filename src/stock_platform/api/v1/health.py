from fastapi import APIRouter

from stock_platform.operation.health_service import (
    check_database,
    check_ollama,
)
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.persistence import (
    market_data_persistence_worker,
)

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("")
async def health():
    database = check_database()
    ollama = check_ollama()
    realtime = await realtime_manager.status()
    persistence = market_data_persistence_worker.status()

    status_code = "UP"

    if database["status"] != "UP":
        status_code = "DEGRADED"

    if ollama["status"] != "UP":
        status_code = "DEGRADED"

    if persistence.get("failed", 0) > 0 and persistence.get(
        "last_error"
    ):
        status_code = "DEGRADED"

    return {
        "status": status_code,
        "components": {
            "database": database,
            "ollama": ollama,
            "realtime": realtime,
            "market_data_persistence": persistence,
        },
    }
