import httpx
import pytest
from logging_utils import configure_logging

configure_logging()
from async_api_client import AsyncAPIClient
from retry_policy import AuthenticationError

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_successful_response():
    async def handler(request):
        return httpx.Response(
            200,
            json={"id": 1, "name": "Harish"},
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.com",
    ) as http:
        async with AsyncAPIClient(
            "https://example.com",
            client=http,
        ) as api:
            result = await api.get_json("/users/1")

    assert result["id"] == 1
    assert result["name"] == "Harish"


@pytest.mark.asyncio
async def test_retries_503_then_succeeds(monkeypatch):
    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            return httpx.Response(503)

        return httpx.Response(200, json={"status": "ok"})

    async def no_wait(_delay):
        pass

    monkeypatch.setattr("retry_policy.asyncio.sleep", no_wait)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.com",
    ) as http:
        async with AsyncAPIClient(
            "https://example.com",
            client=http,
        ) as api:
            result = await api.get_json("/health")

    assert result == {"status": "ok"}
    assert attempts == 3


@pytest.mark.asyncio
async def test_does_not_retry_401(monkeypatch):
    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(401)

    async def no_wait(_delay):
        pass

    monkeypatch.setattr("retry_policy.asyncio.sleep", no_wait)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.com",
    ) as http:
        async with AsyncAPIClient(
            "https://example.com",
            client=http,
        ) as api:
            with pytest.raises(AuthenticationError):
                await api.get_json("/protected")

    assert attempts == 1
