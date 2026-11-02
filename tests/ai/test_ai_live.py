"""Live AI/ML API checks. Skipped unless AI_API_URL is set.

AI_API_URL, AI_API_KEY (optional bearer), AI_ENDPOINT, AI_PROMPT_FIELD,
AI_TEXT_PATH, AI_EVAL_CASES_FILE and the AI_* thresholds configure the run.
"""
import os

import pytest
import pytest_asyncio

from ai_client import AIClient
from ai_eval import Thresholds, evaluate, load_cases, percentile
from async_api_client import AsyncAPIClient

pytestmark = [pytest.mark.ai, pytest.mark.external]


@pytest.fixture
def thresholds():
    return Thresholds.load()


@pytest_asyncio.fixture
async def ai():
    url = os.getenv("AI_API_URL")
    if not url:
        pytest.skip("AI_API_URL not set")
    async with AsyncAPIClient(url, bearer_token=os.getenv("AI_API_KEY"), max_attempts=2) as api:
        yield AIClient.from_env(api)


@pytest.fixture
def cases():
    path = os.getenv("AI_EVAL_CASES_FILE")
    if not path:
        pytest.skip("AI_EVAL_CASES_FILE not set")
    return load_cases(path)


@pytest.mark.asyncio
async def test_single_call_is_within_latency_budget(ai, thresholds):
    reply = await ai.ask("ping")

    assert reply.text
    assert reply.latency_s <= thresholds.max_latency_s


@pytest.mark.asyncio
async def test_eval_cases_meet_pass_rate_and_p95_latency(ai, cases, thresholds):
    failures, latencies = {}, []
    for case in cases:
        reply = await ai.ask(case.prompt)
        latencies.append(reply.latency_s)
        problems = evaluate(case, reply.text, thresholds)
        if problems:
            failures[case.id] = problems

    pass_rate = 1 - len(failures) / len(cases)
    assert pass_rate >= thresholds.min_pass_rate, failures
    assert percentile(latencies, 95) <= thresholds.p95_latency_s
