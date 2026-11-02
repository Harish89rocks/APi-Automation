import json
import os
from pathlib import Path

import pytest

from services.data_validation import DataValidator, run_table_checks
from services.warehouse import (
    ClickHouseSettings,
    SnowflakeSettings,
    clickhouse_query,
    snowflake_query,
)

pytestmark = [pytest.mark.warehouse]


def load_specs(warehouse: str) -> list[dict]:
    """Table specs for ``warehouse`` from the file named by WAREHOUSE_CHECKS_FILE."""
    path = os.getenv("WAREHOUSE_CHECKS_FILE")
    if not path:
        return []
    return json.loads(Path(path).read_text(encoding="utf-8")).get(warehouse, {}).get(
        "tables", []
    )


@pytest.fixture
def snowflake():
    settings = SnowflakeSettings.from_env()
    if settings is None:
        pytest.skip(
            "Snowflake not configured (SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER and "
            "SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH)"
        )
    pytest.importorskip("snowflake.connector")
    with snowflake_query(settings) as query:
        yield DataValidator(query), query


@pytest.fixture
def clickhouse():
    settings = ClickHouseSettings.from_env()
    if settings is None:
        pytest.skip("ClickHouse not configured (CLICKHOUSE_HOST)")
    pytest.importorskip("clickhouse_connect")
    with clickhouse_query(settings) as query:
        yield DataValidator(query), query


# ---- connectivity -----------------------------------------------------------------


def test_snowflake_is_reachable(snowflake):
    _, query = snowflake

    assert query("SELECT 1")[0][0] == 1


def test_clickhouse_is_reachable(clickhouse):
    _, query = clickhouse

    assert query("SELECT 1")[0][0] == 1


# ---- configured table checks -------------------------------------------------------


def test_snowflake_tables_meet_expectations(snowflake):
    specs = load_specs("snowflake")
    if not specs:
        pytest.skip("No snowflake tables in WAREHOUSE_CHECKS_FILE")
    validator, _ = snowflake

    failures = [f for spec in specs for f in run_table_checks(validator, spec)]

    assert failures == [], "\n".join(failures)


def test_clickhouse_tables_meet_expectations(clickhouse):
    specs = load_specs("clickhouse")
    if not specs:
        pytest.skip("No clickhouse tables in WAREHOUSE_CHECKS_FILE")
    validator, _ = clickhouse

    failures = [f for spec in specs for f in run_table_checks(validator, spec)]

    assert failures == [], "\n".join(failures)


# ---- settings parsing (no network) ---------------------------------------------------


@pytest.mark.unit
def test_snowflake_settings_need_a_credential(monkeypatch):
    for name in ("SNOWFLAKE_PASSWORD", "SNOWFLAKE_PRIVATE_KEY_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct")
    monkeypatch.setenv("SNOWFLAKE_USER", "qa")

    assert SnowflakeSettings.from_env() is None

    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", "/keys/qa.p8")
    assert SnowflakeSettings.from_env().private_key_path == "/keys/qa.p8"


@pytest.mark.unit
def test_clickhouse_settings_defaults_and_secure_port(monkeypatch):
    for name in ("CLICKHOUSE_PORT", "CLICKHOUSE_SECURE", "CLICKHOUSE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch.internal")

    plain = ClickHouseSettings.from_env()
    monkeypatch.setenv("CLICKHOUSE_SECURE", "true")
    secure = ClickHouseSettings.from_env()

    assert (plain.port, plain.secure) == (8123, False)
    assert (secure.port, secure.secure) == (8443, True)


@pytest.mark.unit
def test_secrets_are_not_exposed_in_repr(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_HOST", "h")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "s3cret-value")

    assert "s3cret-value" not in repr(ClickHouseSettings.from_env())
