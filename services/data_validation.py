"""Warehouse-agnostic SQL data validation.

``DataValidator`` only needs a ``query(sql) -> list[tuple]`` callable, so the
same checks run on Snowflake, ClickHouse, PostgreSQL or SQLite. Identifiers are
validated against a strict pattern because they are interpolated into SQL;
values are never interpolated.
"""

import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")

QueryFn = Callable[[str], Sequence[Sequence]]


def safe_identifier(name: str) -> str:
    if not isinstance(name, str) or not IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


class DataValidator:
    def __init__(self, query: QueryFn):
        self._query = query

    def _scalar(self, sql: str):
        rows = self._query(sql)
        return rows[0][0] if rows else None

    def row_count(self, table: str) -> int:
        return int(self._scalar(f"SELECT COUNT(*) FROM {safe_identifier(table)}"))

    def null_count(self, table: str, column: str) -> int:
        return int(
            self._scalar(
                f"SELECT COUNT(*) FROM {safe_identifier(table)} "
                f"WHERE {safe_identifier(column)} IS NULL"
            )
        )

    def duplicate_key_count(self, table: str, columns: Sequence[str]) -> int:
        """Number of key values that appear more than once."""
        cols = ", ".join(safe_identifier(c) for c in columns)
        return int(
            self._scalar(
                f"SELECT COUNT(*) FROM (SELECT {cols} FROM {safe_identifier(table)} "
                f"GROUP BY {cols} HAVING COUNT(*) > 1) d"
            )
        )

    def out_of_range_count(
        self, table: str, column: str, minimum=None, maximum=None
    ) -> int:
        if minimum is None and maximum is None:
            raise ValueError("Provide minimum and/or maximum")
        col = safe_identifier(column)
        clauses = []
        if minimum is not None:
            clauses.append(f"{col} < {float(minimum)!r}")
        if maximum is not None:
            clauses.append(f"{col} > {float(maximum)!r}")
        return int(
            self._scalar(
                f"SELECT COUNT(*) FROM {safe_identifier(table)} "
                f"WHERE {' OR '.join(clauses)}"
            )
        )

    def latest_timestamp(self, table: str, column: str) -> datetime | None:
        value = self._scalar(
            f"SELECT MAX({safe_identifier(column)}) FROM {safe_identifier(table)}"
        )
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def age(self, table: str, column: str, now: datetime | None = None):
        latest = self.latest_timestamp(table, column)
        if latest is None:
            return None
        return (now or datetime.now(timezone.utc)) - latest


def reconcile(
    source: DataValidator,
    target: DataValidator,
    source_table: str,
    target_table: str,
    tolerance: float = 0.0,
) -> list[str]:
    """Compare row counts across systems; ``tolerance`` is a fraction (0.01 = 1%)."""
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")

    src, dst = source.row_count(source_table), target.row_count(target_table)
    allowed = src * tolerance
    if abs(src - dst) > allowed:
        return [
            f"row count mismatch: {source_table}={src} vs {target_table}={dst}"
            f" (tolerance {tolerance:.2%})"
        ]
    return []


def run_table_checks(validator: DataValidator, spec: dict) -> list[str]:
    """Run the checks described by ``spec``; return human-readable failures.

    spec keys (all optional except ``name``): ``min_rows``, ``max_rows``,
    ``not_null`` [cols], ``unique`` [[cols], ...], ``ranges``
    [{column, min, max}], ``freshness`` {column, max_age_hours}.
    """
    table = spec["name"]
    failures = []

    count = validator.row_count(table)
    if "min_rows" in spec and count < spec["min_rows"]:
        failures.append(f"{table}: {count} rows < min_rows {spec['min_rows']}")
    if "max_rows" in spec and count > spec["max_rows"]:
        failures.append(f"{table}: {count} rows > max_rows {spec['max_rows']}")

    for column in spec.get("not_null", []):
        nulls = validator.null_count(table, column)
        if nulls:
            failures.append(f"{table}.{column}: {nulls} NULL value(s)")

    for key in spec.get("unique", []):
        dupes = validator.duplicate_key_count(table, key)
        if dupes:
            failures.append(f"{table}({', '.join(key)}): {dupes} duplicated key(s)")

    for rule in spec.get("ranges", []):
        bad = validator.out_of_range_count(
            table, rule["column"], rule.get("min"), rule.get("max")
        )
        if bad:
            failures.append(f"{table}.{rule['column']}: {bad} value(s) out of range")

    freshness = spec.get("freshness")
    if freshness:
        age = validator.age(table, freshness["column"])
        limit = timedelta(hours=freshness["max_age_hours"])
        if age is None:
            failures.append(f"{table}.{freshness['column']}: no timestamps found")
        elif age > limit:
            failures.append(
                f"{table}.{freshness['column']}: data is {age} old (limit {limit})"
            )

    return failures
