"""Synchronous SQLAlchemy engine and session factory."""

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def get_database_url(settings: Settings) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        get_database_url(settings),
        pool_pre_ping=True,
        hide_parameters=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
