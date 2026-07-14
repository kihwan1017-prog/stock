from fastapi import APIRouter

from stock_platform.api.v1.ai_analysis import router as ai_analysis_router
from stock_platform.api.v1.ai_candidates import router as ai_candidates_router
from stock_platform.api.v1.ai_orchestration import router as ai_orchestration_router
from stock_platform.api.v1.backtest_runs import router as backtest_runs_router
from stock_platform.api.v1.backtests import router as backtests_router
from stock_platform.api.v1.candidate_runs import router as candidate_runs_router
from stock_platform.api.v1.candidates import router as candidates_router
from stock_platform.api.v1.daily_reports import router as daily_reports_router
from stock_platform.api.v1.dart import router as dart_router
from stock_platform.api.v1.guarded_pipeline import router as guarded_pipeline_router
from stock_platform.api.v1.health import router as health_router
from stock_platform.api.v1.indicators import router as indicators_router
from stock_platform.api.v1.jobs import router as jobs_router
from stock_platform.api.v1.kiwoom import router as kiwoom_router
from stock_platform.api.v1.news import router as news_router
from stock_platform.api.v1.paper_accounts import router as paper_accounts_router
from stock_platform.api.v1.paper_executions import router as paper_executions_router
from stock_platform.api.v1.paper_orders import router as paper_orders_router
from stock_platform.api.v1.paper_simulation import router as paper_simulation_router
from stock_platform.api.v1.pipelines import router as pipelines_router
from stock_platform.api.v1.position_candidates import router as position_candidates_router
from stock_platform.api.v1.prices import router as prices_router
from stock_platform.api.v1.risk import router as risk_router
from stock_platform.api.v1.risk_policies import router as risk_policies_router
from stock_platform.api.v1.scheduler_admin import router as scheduler_admin_router
from stock_platform.api.v1.sync import router as sync_router
from stock_platform.api.v1.trading_calendar import router as trading_calendar_router
from stock_platform.api.v1.upbit import router as upbit_router
from stock_platform.api.v1.version import router as version_router


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
api_router.include_router(dart_router)
api_router.include_router(news_router)
api_router.include_router(ai_orchestration_router)
api_router.include_router(risk_router)
api_router.include_router(risk_policies_router)
api_router.include_router(position_candidates_router)
api_router.include_router(paper_orders_router)
api_router.include_router(paper_accounts_router)
api_router.include_router(paper_executions_router)
api_router.include_router(paper_simulation_router)
api_router.include_router(jobs_router)
api_router.include_router(scheduler_admin_router)
api_router.include_router(pipelines_router)
api_router.include_router(trading_calendar_router)
api_router.include_router(guarded_pipeline_router)
api_router.include_router(daily_reports_router)
api_router.include_router(backtests_router)
api_router.include_router(backtest_runs_router)
