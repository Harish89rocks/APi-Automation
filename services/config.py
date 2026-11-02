"""Service-specific settings, read from the environment only.

Credentials are never stored in the repository: supply them through
environment variables locally or the CI secret store.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str = field(repr=False)

    @classmethod
    def from_env(cls) -> "PostgresSettings | None":
        """Return settings, or None when no database is configured.

        ``POSTGRES_DSN`` wins; otherwise ``POSTGRES_HOST`` (+ optional
        ``POSTGRES_PORT``, ``POSTGRES_DB``, ``POSTGRES_USER``,
        ``POSTGRES_PASSWORD``) is used.
        """
        dsn = os.getenv("POSTGRES_DSN")
        if dsn:
            return cls(dsn=dsn)

        host = os.getenv("POSTGRES_HOST")
        if not host:
            return None

        parts = {
            "host": host,
            "port": os.getenv("POSTGRES_PORT", "5432"),
            "dbname": os.getenv("POSTGRES_DB", "postgres"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
        }
        password = os.getenv("POSTGRES_PASSWORD")
        if password:
            parts["password"] = password

        return cls(dsn=" ".join(f"{k}={v}" for k, v in parts.items()))
