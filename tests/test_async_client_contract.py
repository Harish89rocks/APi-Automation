import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from async_api_client import AsyncAPIClient
from retry_policy import (
    AuthenticationError,
    AuthorizationError,
    ClientRequestError,
    ResponseSchemaError,
    TransientAPIError,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "https://example.com"


class UserOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def instant(_delay):
        pass

    monkeypatch.setattr("retry_policy.asyncio.sleep", instant)


def make_client(handler, **kwargs) -> AsyncAPIClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=BASE_URL,
    )
    return AsyncAPIClient(BASE_URL, client=http, **kwargs)


async def call(handler, method="get", *args, client_kwargs=None, **kwargs):
    api = make_client(handler, **(client_kwargs or {}))
    async with api:
        try:
            return await getattr(api, method)(*args, **kwargs)
        finally:
            await api.client.aclose()


# ---- schema validation -------------------------------------------------


async def test_response_model_returns_validated_object():
    def handler(request):
        return httpx.Response(200, json={"id": 1, "name": "Harish"})

    user = await call(handler, "get_json", "/users/1", response_model=UserOut)

    assert isinstance(user, UserOut)
    assert user.id == 1


@pytest.mark.parametrize(
    "body",
    [
        {"id": "not-an-int", "name": "Harish"},
        {"name": "Harish"},
        {"id": 1, "name": "Harish", "unexpected": True},
    ],
    ids=["wrong-type", "missing-field", "extra-field"],
)
async def test_response_schema_violation_is_reported(body):
    def handler(request):
        return httpx.Response(200, json=body)

    with pytest.raises(ResponseSchemaError, match="UserOut"):
        await call(handler, "get_json", "/users/1", response_model=UserOut)


async def test_non_object_json_is_schema_error():
    def handler(request):
        return httpx.Response(200, json=["a", "list"])

    with pytest.raises(ResponseSchemaError, match="JSON object"):
        await call(handler, "get_json", "/users")


async def test_invalid_json_body_is_schema_error():
    def handler(request):
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(ResponseSchemaError, match="valid JSON"):
        await call(handler, "get_json", "/users")


# ---- authentication / authorization -------------------------------------


async def test_bearer_token_is_sent():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True})

    await call(
        handler, "get_json", "/me", client_kwargs={"bearer_token": "abc123"}
    )

    assert seen["auth"] == "Bearer abc123"


async def test_per_request_header_overrides_client_token():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True})

    await call(
        handler,
        "get_json",
        "/me",
        headers={"Authorization": "Bearer override"},
        client_kwargs={"bearer_token": "default"},
    )

    assert seen["auth"] == "Bearer override"


async def test_no_authorization_header_without_token():
    seen = {}

    def handler(request):
        seen["has_auth"] = "authorization" in request.headers
        return httpx.Response(200, json={"ok": True})

    await call(handler, "get_json", "/public")

    assert seen["has_auth"] is False


@pytest.mark.parametrize(
    "status, error",
    [(401, AuthenticationError), (403, AuthorizationError)],
)
async def test_auth_failures_are_not_retried(status, error):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(status)

    with pytest.raises(error):
        await call(handler, "get_json", "/admin")

    assert attempts == 1


async def test_403_is_distinct_from_401():
    def handler(request):
        return httpx.Response(403)

    with pytest.raises(AuthorizationError) as excinfo:
        await call(handler, "get_json", "/admin")

    assert not isinstance(excinfo.value, AuthenticationError)


# ---- negative / boundary ------------------------------------------------


@pytest.mark.parametrize("status", [400, 404, 409, 422])
async def test_client_errors_are_not_retried_and_keep_status(status):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, json={"detail": "nope"})

    with pytest.raises(ClientRequestError) as excinfo:
        await call(handler, "get_json", "/users/999")

    assert excinfo.value.status_code == status
    assert excinfo.value.body == {"detail": "nope"}
    assert attempts == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retryable_statuses_exhaust_attempts(status):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(status)

    with pytest.raises(TransientAPIError):
        await call(handler, "get_json", "/flaky")

    assert attempts == 3


@pytest.mark.parametrize("max_attempts", [1, 2, 5])
async def test_max_attempts_boundary(max_attempts):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    with pytest.raises(TransientAPIError):
        await call(
            handler,
            "get_json",
            "/flaky",
            client_kwargs={"max_attempts": max_attempts},
        )

    assert attempts == max_attempts


async def test_timeout_is_retried_then_raised():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TransientAPIError, match="timed out"):
        await call(handler, "get_json", "/slow")

    assert attempts == 3


async def test_connection_error_is_retried_then_raised():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TransientAPIError, match="transport"):
        await call(handler, "get_json", "/down")


async def test_empty_object_is_valid_json_object():
    def handler(request):
        return httpx.Response(200, json={})

    assert await call(handler, "get_json", "/empty") == {}


# ---- POST ----------------------------------------------------------------


async def test_post_json_sends_payload_and_method():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = request.read()
        return httpx.Response(201, json={"id": 7, "name": "Harish"})

    user = await call(
        handler,
        "post_json",
        "/users",
        {"name": "Harish"},
        response_model=UserOut,
    )

    assert seen["method"] == "POST"
    assert b"Harish" in seen["body"]
    assert user.id == 7


async def test_post_422_surfaces_validation_detail():
    detail = [{"loc": ["body", "email"], "msg": "bad"}]

    def handler(request):
        return httpx.Response(422, json={"detail": detail})

    with pytest.raises(ClientRequestError) as excinfo:
        await call(handler, "post_json", "/users", {"name": "x"})

    assert excinfo.value.status_code == 422
    assert excinfo.value.body["detail"] == detail


async def test_correlation_id_is_logged(caplog):
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    with caplog.at_level("INFO", logger="api_client"):
        await call(
            handler, "get_json", "/health", correlation_id="trace-42"
        )

    assert any(
        getattr(r, "correlation_id", None) == "trace-42"
        for r in caplog.records
    )


async def test_bearer_token_is_never_logged(caplog):
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    with caplog.at_level("DEBUG"):
        await call(
            handler,
            "get_json",
            "/me",
            client_kwargs={"bearer_token": "super-secret-token"},
        )

    assert "super-secret-token" not in caplog.text
