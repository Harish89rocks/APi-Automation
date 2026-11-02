"""Snowflake and ClickHouse connectors, configured from the environment only.

Each ``*_query`` context manager yields a ``query(sql) -> list[tuple]``
callable for ``services.data_validation.DataValidator``. Heavy client
libraries are imported lazily so the rest of the suite works without them.
"""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field


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
        account, user = os.getenv("SNOWFLAKE_ACCOUNT"), os.getenv("SNOWFLAKE_USER")
        if not (account and user):
            return None
        password = os.getenv("SNOWFLAKE_PASSWORD")
        key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
        if not (password or key_path):
            return None
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
        host = os.getenv("CLICKHOUSE_HOST")
        if not host:
            return None
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
                cursor.execute(sql)
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
        yield lambda sql: client.query(sql).result_rows
    finally:
        client.close()
