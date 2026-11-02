"""Service-specific settings, read from the environment only.

Credentials are never stored in the repository: supply them through
environment variables locally or the CI secret store.
"""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class ConfigurationError(RuntimeError):
    """An integration is configured, but the configuration is unusable.

    Tests turn this into a failure (never a skip): absent configuration means
    "not requested", whereas present-but-broken configuration is a defect.
    """


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


def validate_base_url(value: str, variable: str) -> str:
    """Return ``value`` without a trailing slash, or raise ConfigurationError."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigurationError(
            f"{variable} must be an http(s) URL such as https://host:8000, "
            f"got a value with scheme {parts.scheme!r}"
        )
    if parts.username or parts.password:
        raise ConfigurationError(
            f"{variable} must not embed credentials; pass them via dedicated variables"
        )
    if parts.query or parts.fragment:
        raise ConfigurationError(f"{variable} must not contain a query string or fragment")
    return value.strip().rstrip("/")


def require_complete(group: str, names: list[str], required: list[str]) -> bool:
    """True when ``required`` are all set; False when none of ``names`` is set.

    Raises ConfigurationError when the group is only partly configured, so a
    typo in one variable cannot silently disable a live suite.
    """
    present = [n for n in names if os.getenv(n)]
    if not present:
        return False
    missing = [n for n in required if not os.getenv(n)]
    if missing:
        raise ConfigurationError(
            f"{group} is partly configured ({', '.join(present)} set) but "
            f"missing: {', '.join(missing)}"
        )
    return True


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str = field(repr=False)

    def database_name(self) -> str:
        """Database named by the DSN. Never echoes the DSN (it may hold a password)."""
        from psycopg.conninfo import conninfo_to_dict

        try:
            return conninfo_to_dict(self.dsn).get("dbname") or ""
        except Exception:
            raise ConfigurationError(
                "POSTGRES_DSN / POSTGRES_* do not form a valid PostgreSQL "
                "connection string (value hidden to protect credentials)"
            ) from None

    def require_dedicated_test_database(self) -> None:
        """Refuse databases that do not look dedicated to testing.

        The name must contain "test" or start with "qa" (for example
        ``qa_test``, ``app_test``, ``qa``). Set POSTGRES_ALLOW_NON_TEST_DB=1 to
        override deliberately.
        """
        name = self.database_name()
        looks_dedicated = "test" in name.lower() or name.lower().startswith("qa")
        if not looks_dedicated and not env_flag("POSTGRES_ALLOW_NON_TEST_DB"):
            raise ConfigurationError(
                f"Refusing to run against database {name or '<unspecified>'!r}: "
                "use a dedicated test database (name containing 'test' or "
                "starting with 'qa'), or set POSTGRES_ALLOW_NON_TEST_DB=1"
            )

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
