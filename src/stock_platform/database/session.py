from collections.abc import Generator
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from stock_platform.database.engine import create_database_engine


@lru_cache
def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine."""
    return create_database_engine()


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the shared SQLAlchemy session factory."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency that opens and safely closes a DB session."""
    session = get_session_factory()()

    try:
        yield session
    finally:
        session.close()
