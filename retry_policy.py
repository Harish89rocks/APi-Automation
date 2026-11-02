import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    """Authenticated caller lacks permission (HTTP 403)."""


class ClientRequestError(Exception):
    """Non-retryable 4xx response (bad request, not found, validation)."""

    def __init__(self, message: str, status_code: int, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ResponseSchemaError(ValueError):
    """Response body does not match the expected schema."""


class TransientAPIError(Exception):
    pass


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()

        except AuthenticationError:
            # Authentication failures need a different recovery strategy.
            raise

        except TransientAPIError:
            if attempt == max_attempts:
                raise

            delay = base_delay * (2 ** (attempt - 1))
            await asyncio.sleep(delay)

    raise RuntimeError("Unreachable retry state")
