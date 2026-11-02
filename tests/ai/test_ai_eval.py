import json

import httpx
import pytest

from ai_client import AIClient, extract
from ai_eval import (
    EvalCase,
    Thresholds,
    evaluate,
    f1_score,
    load_cases,
    percentile,
)
from async_api_client import AsyncAPIClient
from retry_policy import ResponseSchemaError

pytestmark = [pytest.mark.ai, pytest.mark.unit]
T = Thresholds()


def fake_model(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://model.test")
    return AsyncAPIClient("http://model.test", client=http, max_attempts=1)


# ---- evaluators (sync, no marker issue) ------------------------------------------------


def test_f1_identical_and_disjoint():
    assert f1_score("the cat sat", "The cat sat!") == 1.0
    assert f1_score("alpha", "beta") == 0.0


def test_f1_partial_overlap_value():
    # overlap 2, precision 2/2, recall 2/4 -> 2*1*.5/1.5
    assert f1_score("cat sat", "the cat sat down") == pytest.approx(2 / 3)


def test_f1_counts_duplicates_once_per_reference_occurrence():
    assert f1_score("a a a a", "a") == pytest.approx(0.4)


def test_f1_empty_inputs():
    assert f1_score("", "") == 1.0
    assert f1_score("", "x") == 0.0


@pytest.mark.parametrize("pct, expected", [(50, 3), (95, 5), (100, 5), (20, 1)])
def test_percentile_nearest_rank(pct, expected):
    assert percentile([5, 1, 3, 2, 4], pct) == expected


@pytest.mark.parametrize("pct", [0, -1, 101])
def test_percentile_rejects_bad_pct(pct):
    with pytest.raises(ValueError):
        percentile([1], pct)


def test_percentile_rejects_empty():
    with pytest.raises(ValueError):
        percentile([], 50)


def test_evaluate_passes_good_output():
    case = EvalCase("c", "q", reference="Paris is the capital", must_contain=["paris"])

    assert evaluate(case, "Paris is the capital", T) == []


def test_evaluate_reports_every_failure():
    case = EvalCase(
        "c", "q", reference="expected answer", must_contain=["foo"],
        must_not_contain=["bad"], expect_json=True,
    )

    failures = evaluate(case, "bad text", T)

    assert len(failures) == 4
    assert any("missing required term" in f for f in failures)
    assert any("forbidden" in f for f in failures)
    assert any("JSON" in f for f in failures)
    assert any("F1" in f for f in failures)


@pytest.mark.parametrize(
    "text, ok", [("", False), ("x", True), ("x" * 4000, True), ("x" * 4001, False)]
)
def test_length_boundaries(text, ok):
    assert (evaluate(EvalCase("c", "q"), text, T) == []) is ok


def test_per_case_f1_overrides_default():
    case = EvalCase("c", "q", reference="a b c d", min_f1=0.1)

    assert evaluate(case, "a", T) == []


# ---- thresholds config --------------------------------------------------------------------


def test_thresholds_env_and_file_precedence(monkeypatch, tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"max_latency_s": 1, "min_f1": 0.2}))
    monkeypatch.setenv("AI_EVAL_THRESHOLDS_FILE", str(f))
    monkeypatch.setenv("AI_MIN_F1", "0.8")

    t = Thresholds.load()

    assert (t.max_latency_s, t.min_f1, t.max_chars) == (1.0, 0.8, 4000)


def test_unknown_threshold_is_rejected(monkeypatch, tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"max_latancy_s": 1}))
    monkeypatch.setenv("AI_EVAL_THRESHOLDS_FILE", str(f))

    with pytest.raises(ValueError, match="Unknown"):
        Thresholds.load()


def test_example_cases_file_is_valid():
    cases = load_cases("ai_eval_cases.example.json")

    assert [c.id for c in cases] == ["capital", "no-leak", "json-output"]


# ---- client against a fake model -----------------------------------------------------------


def test_extract_dotted_path():
    payload = {"choices": [{"message": {"content": "hi"}}]}

    assert extract(payload, "choices.0.message.content") == "hi"


@pytest.mark.asyncio
async def test_ask_returns_text_and_latency():
    async def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"text": f"echo {body['prompt']}"})

    async with fake_model(handler) as api:
        reply = await AIClient(api).ask("hello")

    assert reply.text == "echo hello"
    assert 0 <= reply.latency_s < 5


@pytest.mark.asyncio
async def test_missing_text_field_is_schema_error():
    async with fake_model(lambda r: httpx.Response(200, json={"other": 1})) as api:
        with pytest.raises(ResponseSchemaError, match="text"):
            await AIClient(api).ask("x")


@pytest.mark.asyncio
async def test_non_string_text_is_schema_error():
    async with fake_model(lambda r: httpx.Response(200, json={"text": 5})) as api:
        with pytest.raises(ResponseSchemaError, match="expected str"):
            await AIClient(api).ask("x")


@pytest.mark.asyncio
async def test_nested_path_and_custom_prompt_field():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"out": {"answer": "ok"}})

    async with fake_model(handler) as api:
        client = AIClient(api, prompt_field="input", text_path="out.answer",
                          extra_payload={"temperature": 0})
        reply = await client.ask("q")

    assert reply.text == "ok"
    assert seen == {"temperature": 0, "input": "q"}


@pytest.mark.asyncio
async def test_end_to_end_eval_flags_bad_model_output():
    outputs = {"What is the capital of France?": "Lyon is nice"}

    def handler(request):
        prompt = json.loads(request.content)["prompt"]
        return httpx.Response(200, json={"text": outputs[prompt]})

    case = load_cases("ai_eval_cases.example.json")[0]
    async with fake_model(handler) as api:
        reply = await AIClient(api).ask(case.prompt)

    failures = evaluate(case, reply.text, T)

    assert any("Paris" in f for f in failures)
