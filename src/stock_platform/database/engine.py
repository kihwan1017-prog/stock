from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from stock_platform.common.settings import get_settings


def create_database_engine() -> Engine:
    """프로세스용 Engine — Pool 파라미터는 Settings(env)로 조정."""

    settings = get_settings()

    return create_engine(
        settings.database_url,
        pool_size=max(1, int(settings.db_pool_size)),
        max_overflow=max(0, int(settings.db_max_overflow)),
        pool_timeout=max(1.0, float(settings.db_pool_timeout)),
        pool_recycle=max(60, int(settings.db_pool_recycle)),
        pool_pre_ping=bool(settings.db_pool_pre_ping),
        echo=False,
    )
