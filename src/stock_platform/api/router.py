from fastapi import APIRouter

from stock_platform.api.v1.ai_analysis import (
    router as ai_analysis_router,
)
from stock_platform.api.v1.ai_candidates import (
    router as ai_candidates_router,
)
from stock_platform.api.v1.candidate_runs import (
    router as candidate_runs_router,
)
from stock_platform.api.v1.candidates import (
    router as candidates_router,
)
from stock_platform.api.v1.health import (
    router as health_router,
)
from stock_platform.api.v1.indicators import (
    router as indicators_router,
)
from stock_platform.api.v1.kiwoom import (
    router as kiwoom_router,
)
from stock_platform.api.v1.prices import (
    router as prices_router,
)
from stock_platform.api.v1.sync import (
    router as sync_router,
)
from stock_platform.api.v1.upbit import (
    router as upbit_router,
)
from stock_platform.api.v1.version import (
    router as version_router,
)


api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(version_router)
api_router.include_router(prices_router)
api_router.include_router(kiwoom_router)
api_router.include_router(sync_router)
api_router.include_router(upbit_router)
api_router.include_router(indicators_router)
api_router.include_router(candidates_router)
api_router.include_router(candidate_runs_router)
api_router.include_router(ai_candidates_router)
api_router.include_router(ai_analysis_router)
