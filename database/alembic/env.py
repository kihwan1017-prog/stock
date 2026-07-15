from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool



PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_platform.common.settings import get_settings
from stock_platform.database.base import Base
from stock_platform.markets import models as market_models  # noqa: F401
from stock_platform.screener import persistence_models as screener_models  # noqa: F401
from stock_platform.ai import analysis_models as ai_analysis_models  # noqa: F401
from stock_platform.disclosure import models as disclosure_models  # noqa: F401
from stock_platform.news import models as news_models  # noqa: F401
from stock_platform.risk import persistence_models as risk_models  # noqa: F401
from stock_platform.trading import models as trading_models  # noqa: F401
from stock_platform.trading import account_models as trading_account_models  # noqa: F401
from stock_platform.operation import job_models as operation_job_models  # noqa: F401
from stock_platform.operation import pipeline_models as operation_pipeline_models  # noqa: F401
from stock_platform.operation import calendar_models as operation_calendar_models  # noqa: F401
from stock_platform.operation import report_models as operation_report_models  # noqa: F401
from stock_platform.backtest import persistence_models as backtest_models  # noqa: F401
from stock_platform.broker import account_models as broker_account_models  # noqa: F401
from stock_platform.broker import pending_entities as broker_pending_entities  # noqa: F401
from stock_platform.broker import recovery_entities as broker_recovery_entities  # noqa: F401
from stock_platform.broker import live_transition_entities as live_transition_entities  # noqa: F401
from stock_platform.risk_engine import kill_switch_entities as kill_switch_entities  # noqa: F401
from stock_platform.risk_engine import risk_event_entities as risk_event_entities  # noqa: F401
from stock_platform.risk_engine import position_limit_entities as position_limit_entities  # noqa: F401
from stock_platform.performance import entities as performance_entities  # noqa: F401
from stock_platform.performance import walk_forward_entities as walk_forward_entities  # noqa: F401
from stock_platform.performance import leaderboard_entities as leaderboard_entities  # noqa: F401
from stock_platform.performance import selector_entities as selector_entities  # noqa: F401
from stock_platform.strategy_deployment import entities as strategy_deployment_entities  # noqa: F401
from stock_platform.strategy_deployment import switch_entities as strategy_switch_entities  # noqa: F401
from stock_platform.strategy_deployment import policy_entities as strategy_policy_entities  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("%", "%%"),
)

target_metadata = Base.metadata


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """
    Ignore existing database tables that are not managed by SQLAlchemy ORM.

    This prevents Alembic from generating DROP TABLE statements for legacy
    or manually managed tables.
    """

    if type_ == "table" and reflected and compare_to is None:
        return False

    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="operation",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            include_object=include_object,
            version_table="alembic_version",
            version_table_schema="operation",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()