from fastapi import APIRouter

from stock_platform.operation.runtime_info import (
    build_system_identity,
)


router = APIRouter(
    prefix="/version",
    tags=["Version"],
)


@router.get("")
def version():
    identity = build_system_identity()
    return {
        "version": identity["version"],
        "build_version": identity["build_version"],
        "git_commit": identity["git_commit"],
        "environment": identity["environment"],
        "app_name": identity["app_name"],
        "uptime_seconds": identity["uptime_seconds"],
        "started_at": identity["started_at"],
    }
