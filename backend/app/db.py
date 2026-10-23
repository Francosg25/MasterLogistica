from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def build_engine(settings: Settings):
    if make_url(settings.database_url.get_secret_value()).drivername == "sqlite+pysqlite":
        if settings.auth_mode != "development" or settings.app_env == "production":
            raise ValueError("SQLite is restricted to local development")
        engine = create_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 15},
            hide_parameters=True,
        )
        from app.local_schema import configure_connection

        event.listen(engine, "connect", lambda connection, _: configure_connection(connection))
        # SQLite has no row locks. Serialize complete local transactions, including
        # reference generation, reconciliation and rollback, rather than ignoring locks.
        event.listen(
            engine, "begin", lambda connection: connection.exec_driver_sql("BEGIN IMMEDIATE")
        )
        return engine
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )


def build_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
