import logging
import time
import uuid
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from retry_policy import (
    AuthenticationError,
    AuthorizationError,
    ClientRequestError,
    ResponseSchemaError,
    TransientAPIError,
    retry_async,
)

logger = logging.getLogger("api_client")


def _safe_body(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return response.text


class AsyncAPIClient:
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        bearer_token: str | None = None,
        max_attempts: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._max_attempts = max_attempts
        self._owns_client = client is None
        self.client = (
            client
            if client is not None
            else httpx.AsyncClient(
                base_url=self.base_url,
                timeout=5.0,
            )
        )

    def _build_headers(self, headers: dict | None) -> dict:
        merged = dict(headers or {})
        if self._bearer_token and "Authorization" not in merged:
            merged["Authorization"] = f"Bearer {self._bearer_token}"
        return merged

    async def get_json(
        self,
        path: str,
        correlation_id: str | None = None,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> dict | BaseModel:
        return await self.request_json(
            "GET",
            path,
            correlation_id=correlation_id,
            headers=headers,
            params=params,
            response_model=response_model,
        )

    async def post_json(
        self,
        path: str,
        payload: dict,
        correlation_id: str | None = None,
        *,
        headers: dict | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> dict | BaseModel:
        return await self.request_json(
            "POST",
            path,
            json=payload,
            correlation_id=correlation_id,
            headers=headers,
            response_model=response_model,
        )

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        response_model: type[BaseModel] | None = None,
        correlation_id: str | None = None,
    ) -> dict | BaseModel:
        """Send a request and return the JSON object, or a validated
        ``response_model`` instance when one is supplied."""
        operation_id = correlation_id or str(uuid.uuid4())
        request_headers = self._build_headers(headers)
        endpoint = urlsplit(path).path or "/"
        attempt_number = 0

        async def operation() -> dict:
            nonlocal attempt_number
            attempt_number += 1
            started = time.perf_counter()
            status_code = None

            logger.info(
                "API request started",
                extra={
                    "correlation_id": operation_id,
                    "attempt": attempt_number,
                    "method": method,
                    "endpoint": endpoint,
                    "outcome": "started",
                },
            )

            try:
                response = await self.client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=request_headers,
                )
                status_code = response.status_code

                if status_code == 401:
                    raise AuthenticationError(
                        "API authentication failed"
                    )

                if status_code == 403:
                    raise AuthorizationError(
                        "API authorization failed"
                    )

                if status_code in (429, 500, 502, 503, 504):
                    raise TransientAPIError(
                        f"Retryable HTTP status: {status_code}"
                    )

                if 400 <= status_code < 500:
                    raise ClientRequestError(
                        f"HTTP {status_code} returned by {endpoint}",
                        status_code,
                        _safe_body(response),
                    )

                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as error:
                    raise ResponseSchemaError(
                        "Response was not valid JSON"
                    ) from error

                if not isinstance(data, dict):
                    raise ResponseSchemaError("Expected a JSON object")

                if response_model is not None:
                    try:
                        data = response_model.model_validate(data)
                    except ValidationError as error:
                        raise ResponseSchemaError(
                            f"Response failed {response_model.__name__}"
                            f" validation: {error.error_count()} error(s)"
                        ) from error

                duration_ms = round(
                    (time.perf_counter() - started) * 1000,
                    2,
                )

                logger.info(
                    "API request succeeded",
                    extra={
                        "correlation_id": operation_id,
                        "attempt": attempt_number,
                        "method": method,
                        "endpoint": endpoint,
                        "duration_ms": duration_ms,
                        "status_code": status_code,
                        "outcome": "success",
                    },
                )
                return data

            except httpx.TimeoutException as error:
                raise TransientAPIError(
                    "API request timed out"
                ) from error

            except httpx.TransportError as error:
                raise TransientAPIError(
                    "API transport failure"
                ) from error

            except Exception as error:
                duration_ms = round(
                    (time.perf_counter() - started) * 1000,
                    2,
                )

                logger.warning(
                    "API request attempt failed",
                    extra={
                        "correlation_id": operation_id,
                        "attempt": attempt_number,
                        "method": method,
                        "endpoint": endpoint,
                        "duration_ms": duration_ms,
                        "status_code": status_code,
                        "outcome": "failed",
                        "error_type": type(error).__name__,
                    },
                )
                raise

        try:
            return await retry_async(
                operation, max_attempts=self._max_attempts
            )
        except Exception as error:
            logger.error(
                "API operation failed",
                extra={
                    "correlation_id": operation_id,
                    "method": method,
                    "endpoint": endpoint,
                    "outcome": "failed",
                    "error_type": type(error).__name__,
                },
            )
            raise

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.close()
