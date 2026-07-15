from fastapi import APIRouter

from stock_platform.api.v1.ai_analysis import router as ai_analysis_router
from stock_platform.api.v1.ai_candidates import router as ai_candidates_router
from stock_platform.api.v1.ai_orchestration import router as ai_orchestration_router
from stock_platform.api.v1.backtest_grid import router as backtest_grid_router
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
from stock_platform.api.v1.walk_forward import router as walk_forward_router
from stock_platform.api.v1.portfolio_backtests import router as portfolio_backtests_router
from stock_platform.api.v1.portfolio_rebalancing_backtests import (router as portfolio_rebalancing_backtests_router,)
from stock_platform.api.v1.realtime_quotes import (router as realtime_quotes_router,)
from stock_platform.api.v1.realtime_strategy import (router as realtime_strategy_router,)
from stock_platform.api.v1.realtime_execution import (router as realtime_execution_router,)
from stock_platform.api.v1.realtime_safety import (router as realtime_safety_router,)
from stock_platform.api.v1.realtime_sessions import (router as realtime_sessions_router,)
from stock_platform.api.v1.realtime_ai import (router as realtime_ai_router,)
from stock_platform.api.v1.system_dashboard import (router as system_dashboard_router,)
from stock_platform.api.v1.broker_orders import (router as broker_orders_router,)
from stock_platform.api.v1.kiwoom_account_sync import (router as kiwoom_account_sync_router,)
from stock_platform.api.v1.kiwoom_pending_orders import (router as kiwoom_pending_orders_router,)
from stock_platform.api.v1.kiwoom_order_websocket import (router as kiwoom_order_websocket_router,)
from stock_platform.api.v1.broker_recovery import (router as broker_recovery_router,)
from stock_platform.api.v1.live_trading_transition import (router as live_trading_transition_router,)
from stock_platform.api.v1.realtime_risk_engine import (router as realtime_risk_engine_router,)
from stock_platform.api.v1.realtime_risk_account import (router as realtime_risk_account_router,)
from stock_platform.api.v1.kill_switch import (router as kill_switch_router,)
from stock_platform.api.v1.daily_loss_monitor import (router as daily_loss_monitor_router,)
from stock_platform.api.v1.position_limits import (router as position_limits_router,)
from stock_platform.api.v1.notifications import (router as notifications_router,)

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
api_router.include_router(backtest_grid_router)
api_router.include_router(walk_forward_router)
api_router.include_router(portfolio_backtests_router)
api_router.include_router(portfolio_rebalancing_backtests_router)
api_router.include_router(realtime_quotes_router)
api_router.include_router(realtime_strategy_router)
api_router.include_router(realtime_execution_router)
api_router.include_router(realtime_safety_router)
api_router.include_router(realtime_sessions_router)
api_router.include_router(realtime_ai_router)
api_router.include_router(system_dashboard_router)
api_router.include_router(broker_orders_router)
api_router.include_router(kiwoom_account_sync_router)
api_router.include_router(kiwoom_pending_orders_router)
api_router.include_router(kiwoom_order_websocket_router)
api_router.include_router(broker_recovery_router)
api_router.include_router(live_trading_transition_router)
api_router.include_router(realtime_risk_engine_router)
api_router.include_router(realtime_risk_account_router)
api_router.include_router(kill_switch_router)
api_router.include_router(daily_loss_monitor_router)
api_router.include_router(position_limits_router)
api_router.include_router(notifications_router)