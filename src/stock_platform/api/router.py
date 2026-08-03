from __future__ import annotations

from collections import Counter

from fastapi import APIRouter

from stock_platform.api.v1.ai_analysis import router as ai_analysis_router
from stock_platform.api.v1.audit import router as audit_router
from stock_platform.api.v1.auth import router as auth_router
from stock_platform.api.v1.roles import router as roles_router
from stock_platform.api.v1.users import router as users_router
from stock_platform.api.v1.user_accounts import router as user_accounts_router
from stock_platform.api.v1.user_broker_credentials import (
    router as user_broker_credentials_router,
)
from stock_platform.api.v1.admin_broker_credentials import (
    router as admin_broker_credentials_router,
)
from stock_platform.api.v1.admin_broker_accounts import (
    router as admin_broker_accounts_router,
)
from stock_platform.api.v1.admin_live_ops_readiness import (
    router as admin_live_ops_readiness_router,
)
from stock_platform.api.v1.admin_runtime_preflight import (
    router as admin_runtime_preflight_router,
)
from stock_platform.api.v1.admin_operations_dashboard import (
    router as admin_operations_dashboard_router,
)
from stock_platform.api.v1.admin_dashboard_ops import (
    router as admin_dashboard_ops_router,
)
from stock_platform.api.v1.admin_ai_providers import (
    router as admin_ai_providers_router,
)
from stock_platform.api.v1.admin_ai_provider_configurations import (
    router as admin_ai_provider_configurations_router,
)
from stock_platform.api.v1.admin_ai_prompt_policy import (
    router as admin_ai_prompt_policy_router,
)
from stock_platform.api.v1.admin_ai_executions import (
    costs_router as admin_ai_costs_router,
    router as admin_ai_executions_router,
)
from stock_platform.api.v1.admin_ai_document_analyses import (
    router as admin_ai_document_analyses_router,
)
from stock_platform.api.v1.admin_ai_market_analyses import (
    router as admin_ai_market_analyses_router,
)
from stock_platform.api.v1.admin_ai_candidate_assessments import (
    router as admin_ai_candidate_assessments_router,
)
from stock_platform.api.v1.admin_ai_candidate_consensuses import (
    router as admin_ai_candidate_consensuses_router,
)
from stock_platform.api.v1.admin_ai_candidate_recommendation_queues import (
    router as admin_ai_candidate_recommendation_queues_router,
)
from stock_platform.api.v1.admin_ai_candidate_promotions import (
    router as admin_ai_candidate_promotions_router,
)
from stock_platform.api.v1.admin_ai_candidate_lifecycle import (
    candidates_router as admin_ai_candidate_lifecycle_candidates_router,
    dashboard_router as admin_ai_candidate_lifecycle_dashboard_router,
    router as admin_ai_candidate_lifecycle_router,
)
from stock_platform.api.v1.admin_strategy_requests import (
    router as admin_strategy_requests_router,
)
from stock_platform.api.v1.admin_strategy_drafts import (
    router as admin_strategy_drafts_router,
)
from stock_platform.api.v1.admin_strategy_draft_generations import (
    router as admin_strategy_draft_generations_router,
)
from stock_platform.api.v1.admin_strategy_draft_approvals import (
    router as admin_strategy_draft_approvals_router,
)
from stock_platform.api.v1.admin_ai_reviews import (
    assignments_router as admin_ai_review_assignments_router,
    decisions_router as admin_ai_review_decisions_router,
    reviews_router as admin_ai_reviews_router,
)
from stock_platform.api.v1.admin_ai_evaluation_datasets import (
    router as admin_ai_evaluation_datasets_router,
)
from stock_platform.api.v1.admin_ai_benchmarks import (
    benchmarks_router as admin_ai_benchmarks_router,
    scorecards_router as admin_ai_scorecards_router,
)
from stock_platform.api.v1.user_risk_settings import (
    router as user_risk_settings_router,
)
from stock_platform.api.v1.admin_risk_settings import (
    router as admin_risk_settings_router,
)
from stock_platform.api.v1.live_order_safety import (
    admin_router as admin_live_order_router,
    user_router as user_live_order_router,
)
from stock_platform.api.v1.upbit_live_validation import (
    admin_router as admin_upbit_live_validation_router,
    user_router as user_upbit_live_validation_router,
)
from stock_platform.api.v1.user_live_order_smoke import (
    router as user_live_order_smoke_router,
)
from stock_platform.api.v1.user_portfolio import router as user_portfolio_router
from stock_platform.api.v1.user_watchlist import router as user_watchlist_router
from stock_platform.api.v1.user_news import router as user_news_router
from stock_platform.api.v1.user_disclosures import router as user_disclosures_router
from stock_platform.api.v1.user_ai import router as user_ai_router
from stock_platform.api.v1.user_ai_candidate_lifecycle import (
    router as user_ai_candidate_lifecycle_router,
)
from stock_platform.api.v1.user_strategy_requests import (
    router as user_strategy_requests_router,
)
from stock_platform.api.v1.user_strategy_drafts import (
    router as user_strategy_drafts_router,
)
from stock_platform.api.v1.user_notifications import (
    router as user_notifications_router,
)
from stock_platform.api.v1.user_settings import router as user_settings_router
from stock_platform.api.v1.user_profile import router as user_profile_router
from stock_platform.api.v1.user_market import router as user_market_router
from stock_platform.api.v1.user_candidates import (
    router as user_candidates_router,
)
from stock_platform.api.v1.user_strategies import (
    router as user_strategies_router,
)
from stock_platform.api.v1.user_strategy_ownership import (
    router as user_strategy_ownership_router,
)
from stock_platform.api.v1.user_account_strategies import (
    router as user_account_strategies_router,
)
from stock_platform.api.v1.user_account_strategy_performance import (
    router as user_account_strategy_performance_router,
)
from stock_platform.api.v1.admin_indicator_parameters import (
    router as admin_indicator_parameters_router,
)
from stock_platform.api.v1.admin_member_cleanup import (
    router as admin_member_cleanup_router,
)
from stock_platform.api.v1.admin_strategies import (
    router as admin_strategies_router,
)
from stock_platform.api.v1.admin_portfolio_validations import (
    router as admin_portfolio_validations_router,
)
from stock_platform.api.v1.admin_recovery import (
    router as admin_recovery_router,
)
from stock_platform.api.v1.admin_recovery_scheduler import (
    router as admin_recovery_scheduler_router,
)
from stock_platform.api.v1.admin_trading_scheduler import (
    admin_router as admin_trading_scheduler_router,
)
from stock_platform.api.v1.admin_recovery_conflicts import (
    router as admin_recovery_conflicts_router,
)
from stock_platform.api.v1.admin_runtimes import (
    router as admin_runtimes_router,
)
from stock_platform.api.v1.user_runtimes import (
    router as user_runtimes_router,
)
from stock_platform.api.v1.user_backtests import (
    router as user_backtests_router,
)
from stock_platform.api.v1.ai_candidates import router as ai_candidates_router
from stock_platform.api.v1.ai_orchestration import router as ai_orchestration_router
from stock_platform.api.v1.backtest_grid import router as backtest_grid_router
from stock_platform.api.v1.backtest_performance import (
    router as backtest_performance_router,
)
from stock_platform.api.v1.backtest_runs import router as backtest_runs_router
from stock_platform.api.v1.backtests import router as backtests_router
from stock_platform.api.v1.broker_orders import router as broker_orders_router
from stock_platform.api.v1.broker_recovery import router as broker_recovery_router
from stock_platform.api.v1.candidate_runs import router as candidate_runs_router
from stock_platform.api.v1.candidates import router as candidates_router
from stock_platform.api.v1.daily_loss_monitor import (
    router as daily_loss_monitor_router,
)
from stock_platform.api.v1.daily_reports import router as daily_reports_router
from stock_platform.api.v1.dart import router as dart_router
from stock_platform.api.v1.deployment_performance_monitor import (
    router as deployment_performance_monitor_router,
)
from stock_platform.api.v1.executions import router as executions_router
from stock_platform.api.v1.guarded_pipeline import router as guarded_pipeline_router
from stock_platform.api.v1.health import router as health_router
from stock_platform.api.v1.monitoring import router as monitoring_router
from stock_platform.api.v1.indicators import router as indicators_router
from stock_platform.api.v1.jobs import router as jobs_router
from stock_platform.api.v1.kill_switch import router as kill_switch_router
from stock_platform.api.v1.kiwoom import router as kiwoom_router
from stock_platform.api.v1.kiwoom_account_sync import (
    router as kiwoom_account_sync_router,
)
from stock_platform.api.v1.kiwoom_account_state_sync import (
    router as kiwoom_account_state_sync_router,
)
from stock_platform.api.v1.upbit_account import (
    router as upbit_account_router,
)
from stock_platform.api.v1.kiwoom_order_websocket import (
    router as kiwoom_order_websocket_router,
)
from stock_platform.api.v1.kiwoom_pending_orders import (
    router as kiwoom_pending_orders_router,
)
from stock_platform.api.v1.live_trading_transition import (
    router as live_trading_transition_router,
)
from stock_platform.api.v1.market_data_router import router as market_data_router
from stock_platform.api.v1.market_quality import (
    router as market_quality_router,
)
from stock_platform.api.v1.news import router as news_router
from stock_platform.api.v1.notifications import router as notifications_router
from stock_platform.api.v1.telegram_ops import (
    router as telegram_ops_router,
)
from stock_platform.api.v1.order_cancel_replace import (
    router as order_cancel_replace_router,
)
from stock_platform.api.v1.order_dispatch import router as order_dispatch_router
from stock_platform.api.v1.order_execution import (
    router as order_execution_router,
)
from stock_platform.api.v1.order_outbox import router as order_outbox_router
from stock_platform.api.v1.order_states import router as order_states_router
from stock_platform.api.v1.orders import router as orders_router
from stock_platform.api.v1.paper_accounts import router as paper_accounts_router
from stock_platform.api.v1.paper_executions import router as paper_executions_router
from stock_platform.api.v1.paper_orders import router as paper_orders_router
from stock_platform.api.v1.paper_simulation import router as paper_simulation_router
from stock_platform.api.v1.pipelines import router as pipelines_router
from stock_platform.api.v1.portfolio_backtests import (
    router as portfolio_backtests_router,
)
from stock_platform.api.v1.portfolio_rebalancing_backtests import (
    router as portfolio_rebalancing_backtests_router,
)
from stock_platform.api.v1.position_candidates import (
    router as position_candidates_router,
)
from stock_platform.api.v1.position_limits import router as position_limits_router
from stock_platform.api.v1.prices import router as prices_router
from stock_platform.api.v1.realtime_ai import router as realtime_ai_router
from stock_platform.api.v1.realtime_execution import (
    router as realtime_execution_router,
)
from stock_platform.api.v1.realtime_quotes import router as realtime_quotes_router
from stock_platform.api.v1.realtime_risk_account import (
    router as realtime_risk_account_router,
)
from stock_platform.api.v1.realtime_risk_engine import (
    router as realtime_risk_engine_router,
)
from stock_platform.api.v1.realtime_safety import router as realtime_safety_router
from stock_platform.api.v1.realtime_sessions import router as realtime_sessions_router
from stock_platform.api.v1.realtime_strategy import router as realtime_strategy_router
from stock_platform.api.v1.risk import router as risk_router
from stock_platform.api.v1.risk_dashboard import router as risk_dashboard_router
from stock_platform.api.v1.risk_policies import router as risk_policies_router
from stock_platform.api.v1.scheduler_admin import router as scheduler_admin_router
from stock_platform.api.v1.strategy_approval_policy import (
    router as strategy_approval_policy_router,
)
from stock_platform.api.v1.strategy_deployment import router as strategy_deployment_router
from stock_platform.api.v1.strategy_deployment_pipeline import (
    router as strategy_deployment_pipeline_router,
)
from stock_platform.api.v1.strategy_leaderboard import (
    router as strategy_leaderboard_router,
)
from stock_platform.api.v1.strategy_operations_dashboard import (
    router as strategy_operations_dashboard_router,
)
from stock_platform.api.v1.strategy_performance import (
    router as strategy_performance_router,
)
from stock_platform.api.v1.strategy_performance_dashboard import (
    router as strategy_performance_dashboard_router,
)
from stock_platform.api.v1.strategy_ranking import router as strategy_ranking_router
from stock_platform.api.v1.strategy_runtime import router as strategy_runtime_router
from stock_platform.api.v1.strategy_runtime_switch import (
    router as strategy_runtime_switch_router,
)
from stock_platform.api.v1.strategy_selector import router as strategy_selector_router
from stock_platform.api.v1.sync import router as sync_router
from stock_platform.api.v1.system_dashboard import router as system_dashboard_router
from stock_platform.api.v1.admin_dashboard_summary import (
    router as admin_dashboard_summary_router,
)
from stock_platform.api.v1.settings import (
    ollama_router,
    router as settings_router,
)
from stock_platform.api.v1.ops_db import router as ops_db_router
from stock_platform.api.v1.docs_cms import router as docs_cms_router
from stock_platform.api.v1.trading_calendar import router as trading_calendar_router
from stock_platform.api.v1.admin_market_calendar import (
    admin_router as admin_market_calendar_router,
    user_router as user_market_calendar_router,
)
from stock_platform.api.v1.admin_upbit_rate_limits import (
    admin_router as admin_upbit_rate_limits_router,
    user_router as user_upbit_rate_limits_router,
)
from stock_platform.api.v1.admin_upbit_ambiguous_orders import (
    admin_router as admin_upbit_ambiguous_orders_router,
)
from stock_platform.api.v1.admin_upbit_ambiguous_resolver import (
    admin_router as admin_upbit_ambiguous_resolver_router,
)
from stock_platform.api.v1.admin_market_session_jobs import (
    admin_router as admin_market_session_jobs_router,
)
from stock_platform.api.v1.admin_settlements import (
    admin_router as admin_settlements_router,
)
from stock_platform.api.v1.admin_broker_snapshots import (
    admin_router as admin_broker_snapshots_router,
    uba_router as admin_uba_snapshots_router,
)
from stock_platform.api.v1.user_settlements import (
    user_router as user_settlements_router,
)
from stock_platform.api.v1.user_broker_snapshots import (
    user_router as user_broker_snapshots_router,
)
from stock_platform.api.v1.admin_realtime_hub import (
    admin_router as admin_realtime_hub_router,
    user_router as user_realtime_hub_router,
)
from stock_platform.api.v1.upbit import router as upbit_router
from stock_platform.api.v1.version import router as version_router
from stock_platform.api.v1.walk_forward import router as walk_forward_router
from stock_platform.api.v1.walk_forward_performance import (
    router as walk_forward_performance_router,
)


api_router = APIRouter()


def register_api_routers(router: APIRouter) -> None:
    """도메인별 v1 Router를 단일 진입점에 등록한다."""

    for item in _ROUTER_GROUPS:
        router.include_router(item)


def collect_duplicate_operation_ids(router: APIRouter) -> list[str]:
    """OpenAPI operation_id 중복을 검사한다."""

    operation_ids = [
        route.operation_id
        for route in router.routes
        if getattr(route, "operation_id", None)
    ]
    duplicates = [
        operation_id
        for operation_id, count in Counter(operation_ids).items()
        if count > 1
    ]
    return sorted(duplicates)


_ROUTER_GROUPS = (
    health_router,
    monitoring_router,
    auth_router,
    users_router,
    user_accounts_router,
    user_live_order_smoke_router,
    user_broker_credentials_router,
    user_risk_settings_router,
    admin_risk_settings_router,
    admin_live_order_router,
    user_live_order_router,
    admin_upbit_live_validation_router,
    user_upbit_live_validation_router,
    admin_broker_credentials_router,
    admin_broker_accounts_router,
    admin_live_ops_readiness_router,
    admin_runtime_preflight_router,
    admin_operations_dashboard_router,
    admin_dashboard_ops_router,
    admin_ai_providers_router,
    admin_ai_provider_configurations_router,
    admin_ai_prompt_policy_router,
    admin_ai_executions_router,
    admin_ai_document_analyses_router,
    admin_ai_market_analyses_router,
    admin_ai_candidate_assessments_router,
    admin_ai_candidate_consensuses_router,
    admin_ai_candidate_recommendation_queues_router,
    admin_ai_candidate_promotions_router,
    admin_ai_candidate_lifecycle_router,
    admin_ai_candidate_lifecycle_candidates_router,
    admin_ai_candidate_lifecycle_dashboard_router,
    admin_strategy_requests_router,
    admin_strategy_drafts_router,
    admin_strategy_draft_generations_router,
    admin_strategy_draft_approvals_router,
    admin_ai_review_assignments_router,
    admin_ai_reviews_router,
    admin_ai_review_decisions_router,
    admin_ai_evaluation_datasets_router,
    admin_ai_benchmarks_router,
    admin_ai_scorecards_router,
    admin_ai_costs_router,
    admin_strategies_router,
    admin_portfolio_validations_router,
    admin_recovery_router,
    admin_recovery_scheduler_router,
    admin_trading_scheduler_router,
    admin_recovery_conflicts_router,
    admin_runtimes_router,
    user_runtimes_router,
    user_portfolio_router,
    user_watchlist_router,
    user_news_router,
    user_disclosures_router,
    user_ai_router,
    user_ai_candidate_lifecycle_router,
    user_strategy_requests_router,
    user_strategy_drafts_router,
    user_notifications_router,
    user_settings_router,
    user_profile_router,
    user_market_router,
    user_candidates_router,
    # 정적 경로(/ranking 등)를 path param 보다 먼저 등록
    user_strategies_router,
    user_strategy_ownership_router,
    user_account_strategies_router,
    user_account_strategy_performance_router,
    admin_indicator_parameters_router,
    admin_member_cleanup_router,
    user_backtests_router,
    roles_router,
    audit_router,
    version_router,
    system_dashboard_router,
    admin_dashboard_summary_router,
    settings_router,
    ollama_router,
    ops_db_router,
    docs_cms_router,
    prices_router,
    market_data_router,
    market_quality_router,
    kiwoom_router,
    upbit_router,
    sync_router,
    indicators_router,
    candidates_router,
    candidate_runs_router,
    ai_candidates_router,
    ai_analysis_router,
    ai_orchestration_router,
    dart_router,
    news_router,
    backtests_router,
    backtest_runs_router,
    backtest_grid_router,
    backtest_performance_router,
    walk_forward_router,
    walk_forward_performance_router,
    portfolio_backtests_router,
    portfolio_rebalancing_backtests_router,
    strategy_performance_router,
    strategy_ranking_router,
    strategy_leaderboard_router,
    strategy_selector_router,
    strategy_performance_dashboard_router,
    strategy_deployment_router,
    strategy_runtime_router,
    strategy_runtime_switch_router,
    strategy_approval_policy_router,
    strategy_deployment_pipeline_router,
    deployment_performance_monitor_router,
    strategy_operations_dashboard_router,
    risk_router,
    risk_policies_router,
    risk_dashboard_router,
    position_candidates_router,
    position_limits_router,
    kill_switch_router,
    daily_loss_monitor_router,
    realtime_quotes_router,
    realtime_strategy_router,
    realtime_execution_router,
    realtime_safety_router,
    realtime_sessions_router,
    realtime_ai_router,
    realtime_risk_engine_router,
    realtime_risk_account_router,
    broker_orders_router,
    kiwoom_account_sync_router,
    kiwoom_account_state_sync_router,
    upbit_account_router,
    kiwoom_pending_orders_router,
    kiwoom_order_websocket_router,
    broker_recovery_router,
    live_trading_transition_router,
    orders_router,
    order_states_router,
    order_execution_router,
    order_dispatch_router,
    order_cancel_replace_router,
    order_outbox_router,
    executions_router,
    paper_orders_router,
    paper_accounts_router,
    paper_executions_router,
    paper_simulation_router,
    # step32_router: deprecated 무인증 paper fill 우회 — 등록 해제 (P0)
    jobs_router,
    scheduler_admin_router,
    pipelines_router,
    trading_calendar_router,
    admin_market_calendar_router,
    user_market_calendar_router,
    admin_upbit_rate_limits_router,
    admin_upbit_ambiguous_orders_router,
    admin_upbit_ambiguous_resolver_router,
    admin_market_session_jobs_router,
    admin_settlements_router,
    admin_broker_snapshots_router,
    admin_uba_snapshots_router,
    user_settlements_router,
    user_broker_snapshots_router,
    user_upbit_rate_limits_router,
    admin_realtime_hub_router,
    user_realtime_hub_router,
    guarded_pipeline_router,
    daily_reports_router,
    notifications_router,
    telegram_ops_router,
)


register_api_routers(api_router)
