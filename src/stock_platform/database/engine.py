from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from stock_platform.common.settings import get_settings


def create_database_engine() -> Engine:
    settings = get_settings()

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )
