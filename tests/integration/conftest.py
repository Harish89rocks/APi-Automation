import pytest

from services.config import ConfigurationError, PostgresSettings
from services.postgres import check_connection, connect_to_schema, isolated_schema


@pytest.fixture(scope="session")
def postgres_settings() -> PostgresSettings:
    settings = PostgresSettings.from_env()
    if settings is None:
        pytest.skip(
            "PostgreSQL not configured (set POSTGRES_DSN or POSTGRES_HOST)"
        )
    try:
        settings.require_dedicated_test_database()
        check_connection(settings)
    except ConfigurationError as error:
        # Configured but unusable is a failure, never a silent skip.
        pytest.fail(str(error), pytrace=False)
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
