from fastapi import APIRouter

from stock_platform.operation.health_service import (
    check_database,
    check_ollama,
)

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("")
def health():

    database = check_database()

    ollama = check_ollama()

    status = "UP"

    if database["status"] != "UP":
        status = "DEGRADED"

    if ollama["status"] != "UP":
        status = "DEGRADED"

    return {
        "status": status,
        "components": {
            "database": database,
            "ollama": ollama,
        },
    }