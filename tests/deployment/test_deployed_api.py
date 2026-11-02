"""Black-box tests for a *deployed* instance of the API.

Works against anything reachable over HTTP: a local process, a Docker
container, Docker Compose, or a Kubernetes Service (e.g. via
``kubectl port-forward``).

Configuration (placeholders only; never put credentials in the URL):
  DEPLOYED_API_URL          http(s) base URL. Unset -> tests skip; invalid -> tests fail.
  DEPLOYED_API_ENV          label shown in the report (e.g. local, ci-container, staging).
                            "prod"/"production" is refused.
  DEPLOYED_API_ALLOW_WRITES 1 to run tests that POST. Off by default so a real
                            service is only ever read from.
  DEPLOYED_API_WAIT / DEPLOYED_API_MAX_LATENCY_S  readiness wait and latency budget.
"""

import os
import time

import pytest
import requests

from api_client import APIClient
from contract_utils import validate_response
from services.config import ConfigurationError, env_flag, validate_base_url

pytestmark = [pytest.mark.deployment]

TIMEOUT = 10
FORBIDDEN_ENVIRONMENTS = {"prod", "production"}


def target_environment() -> str:
    return os.getenv("DEPLOYED_API_ENV", "unspecified")


@pytest.fixture(scope="module")
def base_url() -> str:
    url = os.getenv("DEPLOYED_API_URL")
    if not url:
        pytest.skip("DEPLOYED_API_URL not set")
    if target_environment().lower() in FORBIDDEN_ENVIRONMENTS:
        pytest.fail(
            "DEPLOYED_API_ENV names a production environment; deployment tests "
            "must target a disposable or staging instance",
            pytrace=False,
        )
    try:
        return validate_base_url(url, "DEPLOYED_API_URL")
    except ConfigurationError as error:
        pytest.fail(str(error), pytrace=False)


@pytest.fixture(scope="module")
def allow_writes() -> None:
    if not env_flag("DEPLOYED_API_ALLOW_WRITES"):
        pytest.skip(
            "write test skipped: set DEPLOYED_API_ALLOW_WRITES=1 for a "
            "disposable target (it sends POST requests)"
        )


@pytest.fixture(scope="module")
def http(base_url):
    deadline = time.monotonic() + float(os.getenv("DEPLOYED_API_WAIT", "30"))
    last_error = None
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base_url}/health", timeout=3).ok:
                break
        except requests.RequestException as error:
            last_error = error
        time.sleep(1)
    else:
        pytest.fail(f"{base_url} not healthy before timeout: {last_error}")

    session = requests.Session()
    yield session
    session.close()


@pytest.mark.smoke
def test_health_endpoint(http, base_url):
    response = APIClient(base_url).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.smoke
def test_create_user_round_trip(http, base_url, allow_writes):
    response = http.post(
        f"{base_url}/users",
        json={"name": "Harish", "email": "harish@example.com"},
        timeout=TIMEOUT,
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "harish@example.com"


@pytest.mark.smoke
def test_invalid_user_is_rejected(http, base_url, allow_writes):
    response = http.post(
        f"{base_url}/users",
        json={"name": "", "email": "nope"},
        timeout=TIMEOUT,
    )

    assert response.status_code == 422


def test_deployed_openapi_matches_live_behaviour(http, base_url, allow_writes):
    spec = http.get(f"{base_url}/openapi.json", timeout=TIMEOUT).json()
    response = http.post(
        f"{base_url}/users",
        json={"name": "Harish", "email": "harish@example.com"},
        timeout=TIMEOUT,
    )

    validate_response(spec, "/users", "post", 201, response.json())


def test_response_time_is_within_budget(http, base_url):
    budget = float(os.getenv("DEPLOYED_API_MAX_LATENCY_S", "1.0"))

    response = http.get(f"{base_url}/health", timeout=TIMEOUT)

    assert response.elapsed.total_seconds() < budget


def test_unknown_route_is_404_not_500(http, base_url):
    assert http.get(f"{base_url}/nope", timeout=TIMEOUT).status_code == 404
