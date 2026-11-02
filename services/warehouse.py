"""Snowflake and ClickHouse connectors, configured from the environment only.

Each ``*_query`` context manager yields a ``query(sql) -> list[tuple]``
callable for ``services.data_validation.DataValidator``. Heavy client
libraries are imported lazily so the rest of the suite works without them.
"""

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field

from services.config import require_complete

_READ_ONLY = re.compile(r"^\s*(select|with|show|describe|desc|explain)\b", re.IGNORECASE)


def ensure_read_only(sql: str) -> str:
    """Reject anything but a single read-only statement (client-side safety net).

    Use a read-only database role as the real control; this guards mistakes.
    """
    statement = sql.strip().rstrip(";")
    if ";" in statement or not _READ_ONLY.match(statement):
        raise ValueError("Only a single read-only statement is allowed in warehouse tests")
    return sql


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    warehouse: str
    database: str
    password: str | None = field(default=None, repr=False)
    private_key_path: str | None = None
    schema: str = "PUBLIC"
    role: str | None = None

    @classmethod
    def from_env(cls) -> "SnowflakeSettings | None":
        names = [n for n in os.environ if n.startswith("SNOWFLAKE_")]
        if not require_complete("Snowflake", names, ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"]):
            return None
        account, user = os.getenv("SNOWFLAKE_ACCOUNT"), os.getenv("SNOWFLAKE_USER")
        password = os.getenv("SNOWFLAKE_PASSWORD")
        key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
        if not (password or key_path):
            from services.config import ConfigurationError

            raise ConfigurationError(
                "Snowflake is partly configured: set SNOWFLAKE_PASSWORD or "
                "SNOWFLAKE_PRIVATE_KEY_PATH"
            )
        return cls(
            account=account,
            user=user,
            password=password,
            private_key_path=key_path,
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
            database=os.getenv("SNOWFLAKE_DATABASE", ""),
            schema=os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
            role=os.getenv("SNOWFLAKE_ROLE"),
        )


@dataclass(frozen=True)
class ClickHouseSettings:
    host: str
    port: int = 8123
    username: str = "default"
    password: str = field(default="", repr=False)
    database: str = "default"
    secure: bool = False

    @classmethod
    def from_env(cls) -> "ClickHouseSettings | None":
        names = [n for n in os.environ if n.startswith("CLICKHOUSE_")]
        if not require_complete("ClickHouse", names, ["CLICKHOUSE_HOST"]):
            return None
        host = os.getenv("CLICKHOUSE_HOST")
        secure = os.getenv("CLICKHOUSE_SECURE", "").lower() in ("1", "true", "yes")
        return cls(
            host=host,
            port=int(os.getenv("CLICKHOUSE_PORT", "8443" if secure else "8123")),
            username=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("CLICKHOUSE_DATABASE", "default"),
            secure=secure,
        )


@contextmanager
def snowflake_query(settings: SnowflakeSettings):
    import snowflake.connector

    options = dict(
        account=settings.account,
        user=settings.user,
        warehouse=settings.warehouse,
        schema=settings.schema,
        login_timeout=30,
        network_timeout=60,
    )
    if settings.database:
        options["database"] = settings.database
    if settings.role:
        options["role"] = settings.role
    if settings.password:
        options["password"] = settings.password
    else:
        options["private_key_file"] = settings.private_key_path

    connection = snowflake.connector.connect(**options)
    try:

        def query(sql: str):
            cursor = connection.cursor()
            try:
                cursor.execute(ensure_read_only(sql))
                return cursor.fetchall()
            finally:
                cursor.close()

        yield query
    finally:
        connection.close()


@contextmanager
def clickhouse_query(settings: ClickHouseSettings):
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=settings.host,
        port=settings.port,
        username=settings.username,
        password=settings.password,
        database=settings.database,
        secure=settings.secure,
        connect_timeout=15,
        send_receive_timeout=60,
    )
    try:
        yield lambda sql: client.query(ensure_read_only(sql)).result_rows
    finally:
        client.close()
