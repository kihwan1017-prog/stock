"""레거시 /strategy-runtime — Scope Registry 상태·전체 Reload만 유지."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from stock_platform.api.deps_admin import require_admin
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


router = APIRouter(
    prefix="/api/v1/strategy-runtime",
    tags=["Strategy Runtime"],
    dependencies=[Depends(require_admin)],
)


@router.post("/reload")
async def reload_strategy_runtime(
    force: bool = Query(default=False),
    scope_key: str | None = Query(default=None),
    strategy_id: int | None = Query(default=None),
    # 하위 호환: market_code 기본 KRX 단일 로드는 제거됨
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
):
    _ = (market_code, symbol)
    try:
        if scope_key:
            return await dynamic_strategy_runtime_manager.reload(
                scope_key=scope_key, force=force
            )
        if strategy_id is not None:
            return await dynamic_strategy_runtime_manager.reload(
                strategy_id=strategy_id, force=force
            )
        return await dynamic_strategy_runtime_manager.reload_all_scopes(
            force=force
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/clear")
async def clear_strategy_runtime(
    scope_key: str | None = Query(default=None),
):
    await dynamic_strategy_runtime_manager.clear(scope_key=scope_key)
    return {"cleared": True, "scope_key": scope_key}


@router.get("/status")
def get_strategy_runtime_status():
    return dynamic_strategy_runtime_manager.status()
