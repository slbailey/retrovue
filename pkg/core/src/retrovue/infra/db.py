from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.schema import MetaData

from retrovue.infra.settings import settings

# Deterministic constraint/index names (prevents Alembic churn)
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine = create_engine(
    settings.database_url,
    echo=settings.echo_sql,
    pool_pre_ping=True,
    future=True,
    pool_size=settings.pool_size,
    max_overflow=settings.max_overflow,
    pool_timeout=settings.pool_timeout,
    connect_args={"connect_timeout": settings.connect_timeout}
    if "postgresql" in settings.database_url
    else {},
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_conn, _):
    with dbapi_conn.cursor() as cur:
        cur.execute("SET search_path TO public")


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


# Additional functions for bootstrap infrastructure
def get_engine(db_url: str | None = None, for_test: bool = False) -> Engine:
    """Get or create a database engine.

    If ``for_test`` is True and ``settings.test_database_url`` is set, that URL is used.
    Otherwise falls back to the provided ``db_url`` or the default ``settings.database_url``.
    Returns the global engine when using the default, to avoid unnecessary engine creation.
    """
    # Decide which URL to use
    if for_test and settings.test_database_url:
        chosen_url = settings.test_database_url
    else:
        chosen_url = db_url or settings.database_url

    # If we're using the default app engine URL and not forcing test, reuse global engine
    if not db_url and not for_test and chosen_url == settings.database_url:
        return engine

    connect_args: dict[str, object] = {}
    if "sqlite" in chosen_url:
        connect_args["check_same_thread"] = False
    elif "postgresql" in chosen_url:
        connect_args["connect_timeout"] = settings.connect_timeout

    return create_engine(
        chosen_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
        connect_args=connect_args,
    )


def get_sessionmaker(for_test: bool = False) -> sessionmaker:
    """Get a session factory.

    Returns the global sessionmaker for default usage. When ``for_test`` is True,
    returns a temporary sessionmaker bound to a test engine.
    """
    if not for_test:
        return SessionLocal
    test_engine = get_engine(for_test=True)
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


def get_session(for_test: bool = False) -> Generator[Session, None, None]:
    """Get a database session for dependency injection.

    When ``for_test`` is True, binds a session to the test database if configured.
    """
    if for_test:
        SessionForContext = get_sessionmaker(for_test=True)
        db = SessionForContext()
    else:
        db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
