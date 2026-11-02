"""Offline tests for the shared integration-configuration guards."""

import pytest

import optional_deps
from services.aws import assert_expected_account, require_test_owned
from services.config import (
    ConfigurationError,
    PostgresSettings,
    require_complete,
    validate_base_url,
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "value, expected",
    [("http://localhost:8000", "http://localhost:8000"),
     ("https://api.example.test/", "https://api.example.test"),
     ("  https://api.example.test/v1/  ", "https://api.example.test/v1")],
)
def test_valid_base_urls(value, expected):
    assert validate_base_url(value, "X") == expected


@pytest.mark.parametrize(
    "value, message",
    [("", "http\\(s\\) URL"), ("localhost:8000", "http\\(s\\) URL"), ("ftp://host", "http\\(s\\) URL"),
     ("http://", "http\\(s\\) URL"), ("http://u:p@host", "must not embed credentials"),
     ("http://host?token=1", "query string"), ("http://host#frag", "query string")],
)
def test_invalid_base_urls(value, message):
    with pytest.raises(ConfigurationError, match=message):
        validate_base_url(value, "DEPLOYED_API_URL")


def test_url_error_names_the_variable_but_not_the_credentials():
    with pytest.raises(ConfigurationError) as error:
        validate_base_url("http://user:hunter2@host", "DEPLOYED_API_URL")

    assert "DEPLOYED_API_URL" in str(error.value) and "hunter2" not in str(error.value)


def test_require_complete_states(monkeypatch):
    for name in ("G_A", "G_B"):
        monkeypatch.delenv(name, raising=False)
    assert require_complete("g", ["G_A", "G_B"], ["G_A"]) is False

    monkeypatch.setenv("G_B", "x")
    with pytest.raises(ConfigurationError, match="missing: G_A"):
        require_complete("g", ["G_A", "G_B"], ["G_A"])

    monkeypatch.setenv("G_A", "x")
    assert require_complete("g", ["G_A", "G_B"], ["G_A"]) is True


@pytest.mark.parametrize("dbname", ["qa", "qa_test", "app_test", "TestDB", "qa_orders"])
def test_dedicated_test_databases_are_accepted(dbname):
    PostgresSettings(dsn=f"postgresql://u:p@h/{dbname}").require_dedicated_test_database()


@pytest.mark.parametrize("dbname", ["postgres", "prod", "orders"])
def test_other_databases_are_refused(monkeypatch, dbname):
    monkeypatch.delenv("POSTGRES_ALLOW_NON_TEST_DB", raising=False)

    with pytest.raises(ConfigurationError, match="dedicated test database"):
        PostgresSettings(dsn=f"postgresql://u:p@h/{dbname}").require_dedicated_test_database()


def test_explicit_override_allows_other_databases(monkeypatch):
    monkeypatch.setenv("POSTGRES_ALLOW_NON_TEST_DB", "1")

    PostgresSettings(dsn="postgresql://u:p@h/orders").require_dedicated_test_database()


def test_invalid_dsn_error_does_not_leak_the_password():
    with pytest.raises(ConfigurationError) as error:
        PostgresSettings(dsn="host=h password=hunter2 bogus").database_name()

    assert "hunter2" not in str(error.value)


def test_settings_repr_hides_the_dsn():
    assert "hunter2" not in repr(PostgresSettings(dsn="postgresql://u:hunter2@h/qa"))


def test_host_based_configuration(monkeypatch):
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_DB", "qa_test")

    assert PostgresSettings.from_env().database_name() == "qa_test"


def test_unconfigured_postgres_is_none(monkeypatch):
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)

    assert PostgresSettings.from_env() is None


@pytest.mark.parametrize("bucket", ["qa-abc123", "qa-"])
def test_test_owned_buckets_pass_the_cleanup_guard(monkeypatch, bucket):
    monkeypatch.delenv("AWS_TEST_BUCKET_PREFIX", raising=False)

    require_test_owned(bucket)


@pytest.mark.parametrize("bucket", ["prod-data", "my-company-logs", ""])
def test_foreign_buckets_are_refused(monkeypatch, bucket):
    monkeypatch.delenv("AWS_TEST_BUCKET_PREFIX", raising=False)

    with pytest.raises(RuntimeError, match="Refusing to modify bucket"):
        require_test_owned(bucket)


def test_too_short_custom_prefix_is_refused(monkeypatch):
    monkeypatch.setenv("AWS_TEST_BUCKET_PREFIX", "a")

    with pytest.raises(RuntimeError):
        require_test_owned("a-bucket")


class FakeSTS:
    def __init__(self, account):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account}


def test_account_allow_list(monkeypatch):
    assert assert_expected_account(FakeSTS("111111111111"), "111111111111") == "111111111111"
    with pytest.raises(ConfigurationError, match="refusing to run"):
        assert_expected_account(FakeSTS("222222222222"), "111111111111")
    with pytest.raises(ConfigurationError, match="AWS_TEST_ALLOWED_ACCOUNT_ID"):
        assert_expected_account(FakeSTS("111111111111"), None)


def test_missing_optional_package_skips_locally(monkeypatch):
    monkeypatch.delenv("REQUIRE_OPTIONAL_DEPS", raising=False)

    with pytest.raises(pytest.skip.Exception):
        optional_deps.require_module("definitely_not_installed_pkg")


def test_missing_optional_package_fails_when_required(monkeypatch):
    monkeypatch.setenv("REQUIRE_OPTIONAL_DEPS", "1")

    with pytest.raises(pytest.fail.Exception, match="requirements-cloud.txt"):
        optional_deps.require_module("definitely_not_installed_pkg")


def test_installed_package_is_returned():
    assert optional_deps.require_module("json").__name__ == "json"
