import pytest

from services.config import PostgresSettings
from services.postgres import connect_to_schema, isolated_schema


@pytest.fixture(scope="session")
def postgres_settings() -> PostgresSettings:
    settings = PostgresSettings.from_env()
    if settings is None:
        pytest.skip(
            "PostgreSQL not configured (set POSTGRES_DSN or POSTGRES_HOST)"
        )
    return settings


@pytest.fixture(scope="session")
def pg_schema(postgres_settings):
    """A throwaway schema containing the users table, dropped at session end."""
    with isolated_schema(postgres_settings) as schema:
        yield schema


@pytest.fixture
def db(postgres_settings, pg_schema):
    """Per-test connection inside one always-rolled-back transaction.

    Test code may use ``db.transaction()``; it becomes a savepoint here.
    """
    connection = connect_to_schema(postgres_settings, pg_schema)
    try:
        with connection.transaction(force_rollback=True):
            yield connection
    finally:
        connection.close()
