from datetime import datetime, timezone
from functools import lru_cache

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
        "promotion_load_proof": _promotion_load_proof(),
    }


@lru_cache(maxsize=1)
def _promotion_load_proof() -> dict:
    """프로세스당 1회 — inspect.getsource 반복 비용 제거."""

    import inspect

    import stock_platform.ai.candidate_promotion.eligibility as eligibility
    from stock_platform.ai.candidate_recommendation_queue.expiration import is_expired

    validate_source = inspect.getsource(
        eligibility.AICandidatePromotionEligibilityService.validate_queue
    )
    return {
        "eligibility_file": eligibility.__file__,
        "is_expired_signature": str(inspect.signature(is_expired)),
        "caller_keyword": "is_expired(expires_at=queue.expires_at)"
        in validate_source,
        "caller_positional": "is_expired(queue.expires_at)" in validate_source,
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


@router.get("/ops")
async def health_ops():
    """운영 Health — Runtime/Scheduler/Recovery/Outbox/WS 등."""

    from stock_platform.operation.release_operation_readiness import (
        build_operation_health,
        get_last_startup_validation,
    )

    payload = build_operation_health()
    payload["startup_validation"] = get_last_startup_validation()
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
    base = await SystemHealthService().build()
    try:
        from stock_platform.operation.release_operation_readiness import (
            build_operation_health,
        )

        ops = build_operation_health()
        comps = dict(base.get("components") or {})
        for key, value in (ops.get("components") or {}).items():
            comps.setdefault(key, value)
        base["components"] = comps
        base["operation_health"] = {
            "status": ops.get("status"),
            "checked_at": ops.get("checked_at"),
        }
    except Exception:  # noqa: BLE001
        pass
    return base
