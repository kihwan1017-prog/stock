from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.performance.selector_repository import (
    StrategySelectionRepository,
)
from stock_platform.performance.selector_runtime import (
    build_strategy_selector_llm,
)
from stock_platform.performance.selector_service import (
    LlmStrategySelectionService,
)


router = APIRouter(
    prefix="/api/v1/strategy-selector",
    tags=["Strategy Selector"],
)


class StrategySelectionRequest(BaseModel):
    market_code: str = Field(
        min_length=1,
        max_length=30,
    )
    symbol: str | None = Field(
        default=None,
        max_length=30,
    )
    run_type: str | None = Field(
        default="WALK_FORWARD",
        max_length=30,
    )
    minimum_trade_count: int = Field(
        default=20,
        ge=0,
    )
    candidate_limit: int = Field(
        default=5,
        ge=1,
        le=20,
    )
    market_context: dict[str, Any] = {}
    risk_context: dict[str, Any] = {}


@router.post("/select")
async def select_strategy(
    request: StrategySelectionRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return await LlmStrategySelectionService(
            session=session,
            llm_client=build_strategy_selector_llm(),
        ).select(
            market_code=request.market_code,
            symbol=request.symbol,
            run_type=request.run_type,
            minimum_trade_count=(
                request.minimum_trade_count
            ),
            candidate_limit=request.candidate_limit,
            market_context=request.market_context,
            risk_context=request.risk_context,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/latest")
def get_latest_strategy_selection(
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
):
    return StrategySelectionRepository(
        session
    ).latest(
        market_code=market_code,
        symbol=symbol,
    )
