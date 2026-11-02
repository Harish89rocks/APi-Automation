from unittest.mock import AsyncMock

import pytest

import retry_policy
from retry_policy import (
    AuthenticationError,
    TransientAPIError,
    retry_async,
)

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_retries_transient_failure_then_succeeds(monkeypatch):
    operation = AsyncMock(
        side_effect=[
            TransientAPIError("Temporary failure"),
            TransientAPIError("Temporary failure"),
            {"status": "success"},
        ]
    )
    fake_sleep = AsyncMock()
    monkeypatch.setattr(retry_policy.asyncio, "sleep", fake_sleep)

    result = await retry_async(
        operation,
        max_attempts=3,
        base_delay=0.5,
    )

    assert result == {"status": "success"}
    assert operation.await_count == 3
    assert [call.args[0] for call in fake_sleep.await_args_list] == [
        0.5,
        1.0,
    ]


@pytest.mark.asyncio
async def test_does_not_retry_authentication_failure(monkeypatch):
    operation = AsyncMock(
        side_effect=AuthenticationError("Invalid credentials")
    )
    fake_sleep = AsyncMock()
    monkeypatch.setattr(retry_policy.asyncio, "sleep", fake_sleep)

    with pytest.raises(AuthenticationError):
        await retry_async(operation, max_attempts=3)

    assert operation.await_count == 1
    fake_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_raises_after_max_attempts(monkeypatch):
    operation = AsyncMock(
        side_effect=TransientAPIError("Service unavailable")
    )
    fake_sleep = AsyncMock()
    monkeypatch.setattr(retry_policy.asyncio, "sleep", fake_sleep)

    with pytest.raises(TransientAPIError):
        await retry_async(
            operation,
            max_attempts=3,
            base_delay=0.5,
        )

    assert operation.await_count == 3
    assert fake_sleep.await_count == 2
