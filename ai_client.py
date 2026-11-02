"""Thin client for an AI/ML inference API built on AsyncAPIClient."""
import os
import time
from dataclasses import dataclass

from async_api_client import AsyncAPIClient
from retry_policy import ResponseSchemaError


@dataclass(frozen=True)
class ModelReply:
    text: str
    latency_s: float
    raw: dict


def extract(payload: dict, path: str):
    """Follow a dotted path such as ``choices.0.message.content``."""
    node = payload
    for part in path.split("."):
        try:
            node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, ValueError, TypeError):
            raise ResponseSchemaError(f"Response has no field {path!r}") from None
    return node


class AIClient:
    def __init__(
        self,
        api: AsyncAPIClient,
        endpoint: str = "/predict",
        prompt_field: str = "prompt",
        text_path: str = "text",
        extra_payload: dict | None = None,
    ):
        self.api = api
        self.endpoint = endpoint
        self.prompt_field = prompt_field
        self.text_path = text_path
        self.extra_payload = extra_payload or {}

    @classmethod
    def from_env(cls, api: AsyncAPIClient) -> "AIClient":
        return cls(
            api,
            endpoint=os.getenv("AI_ENDPOINT", "/predict"),
            prompt_field=os.getenv("AI_PROMPT_FIELD", "prompt"),
            text_path=os.getenv("AI_TEXT_PATH", "text"),
        )

    async def ask(self, prompt: str) -> ModelReply:
        payload = {**self.extra_payload, self.prompt_field: prompt}
        started = time.perf_counter()
        raw = await self.api.post_json(self.endpoint, payload)
        latency = time.perf_counter() - started
        text = extract(raw, self.text_path)
        if not isinstance(text, str):
            raise ResponseSchemaError(f"{self.text_path!r} is {type(text).__name__}, expected str")
        return ModelReply(text=text, latency_s=latency, raw=raw)
