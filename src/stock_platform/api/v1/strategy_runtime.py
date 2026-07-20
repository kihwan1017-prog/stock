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
    market_code: str = Query(
        default="KRX",
        min_length=1,
    ),
    symbol: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    try:
        return await (
            dynamic_strategy_runtime_manager.reload(
                market_code=market_code,
                symbol=symbol,
                force=force,
            )
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        ValueError,
        TypeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/clear")
async def clear_strategy_runtime():
    await dynamic_strategy_runtime_manager.clear()
    return {"cleared": True}


@router.get("/status")
def get_strategy_runtime_status():
    return dynamic_strategy_runtime_manager.status()
