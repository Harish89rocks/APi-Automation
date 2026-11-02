"""Black-box tests for a *deployed* instance of the API.

Works against anything reachable over HTTP: a local process, a Docker
container, Docker Compose, or a Kubernetes Service (e.g. via
``kubectl port-forward``). Set DEPLOYED_API_URL to enable; skipped otherwise.
"""

import os
import time

import pytest
import requests

from contract_utils import validate_response

pytestmark = [pytest.mark.deployment]

TIMEOUT = 10


@pytest.fixture(scope="module")
def base_url() -> str:
    url = os.getenv("DEPLOYED_API_URL")
    if not url:
        pytest.skip("DEPLOYED_API_URL not set")
    return url.rstrip("/")


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
    response = http.get(f"{base_url}/health", timeout=TIMEOUT)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.smoke
def test_create_user_round_trip(http, base_url):
    response = http.post(
        f"{base_url}/users",
        json={"name": "Harish", "email": "harish@example.com"},
        timeout=TIMEOUT,
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "harish@example.com"


@pytest.mark.smoke
def test_invalid_user_is_rejected(http, base_url):
    response = http.post(
        f"{base_url}/users",
        json={"name": "", "email": "nope"},
        timeout=TIMEOUT,
    )

    assert response.status_code == 422


def test_deployed_openapi_matches_live_behaviour(http, base_url):
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
