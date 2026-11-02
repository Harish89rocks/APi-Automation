"""PostgreSQL helpers: isolated per-session schema and per-test transactions."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql

from services.config import ConfigurationError, PostgresSettings

SCHEMA_FILE = Path(__file__).parent / "sql" / "users_schema.sql"
CONNECT_TIMEOUT_SECONDS = 5


@contextmanager
def isolated_schema(settings: PostgresSettings) -> Iterator[str]:
    """Create a uniquely named schema holding the users table; drop on exit.

    Only the schema created here is ever dropped, so a shared database is safe.
    """
    schema = f"qa_{uuid.uuid4().hex[:12]}"
    name = sql.Identifier(schema)

    with psycopg.connect(
        settings.dsn,
        autocommit=True,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    ) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(name))
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(name))
            admin.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
            yield schema
        finally:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(name)
            )


def connect_to_schema(
    settings: PostgresSettings, schema: str
) -> psycopg.Connection:
    """Open a transactional connection whose search_path is ``schema``."""
    return psycopg.connect(
        settings.dsn,
        options=f"-c search_path={schema}",
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


def check_connection(settings: PostgresSettings) -> None:
    """Raise ConfigurationError with an actionable message if the DB is unreachable."""
    try:
        with psycopg.connect(settings.dsn, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as error:
        detail = (str(error).strip().splitlines() or [type(error).__name__])[0]
        raise ConfigurationError(
            "PostgreSQL is configured but the connection failed "
            f"({type(error).__name__}: {detail}). Check POSTGRES_DSN/POSTGRES_HOST, "
            "credentials and that the test database is running."
        ) from None
