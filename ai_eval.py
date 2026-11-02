"""Quality evaluators and thresholds for AI/ML API responses.

Everything here is pure (no network) so it can be unit tested. Default
thresholds are generic placeholders: tune them per model/service via a JSON
file named by AI_EVAL_THRESHOLDS_FILE or the AI_* environment variables.
"""
import json
import math
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class Thresholds:
    max_latency_s: float = 10.0
    p95_latency_s: float = 15.0
    min_f1: float = 0.5
    max_chars: int = 4000
    min_chars: int = 1
    min_pass_rate: float = 0.9

    @classmethod
    def load(cls) -> "Thresholds":
        values: dict = {}
        path = os.getenv("AI_EVAL_THRESHOLDS_FILE")
        if path:
            values.update(json.loads(Path(path).read_text(encoding="utf-8")))
        for f in fields(cls):
            raw = os.getenv(f"AI_{f.name.upper()}")
            if raw not in (None, ""):
                values[f.name] = raw
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown threshold(s): {sorted(unknown)}")
        typed = {f.name: f.type for f in fields(cls)}
        return cls(**{k: _cast(typed[k], v) for k, v in values.items()})


def _cast(annotation, value):
    return int(value) if annotation in (int, "int") else float(value)


@dataclass
class EvalCase:
    id: str
    prompt: str
    reference: str | None = None
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    expect_json: bool = False
    min_f1: float | None = None


def load_cases(path: str | Path) -> list[EvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in data]


_TOKEN = re.compile(r"\w+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def f1_score(candidate: str, reference: str) -> float:
    """Token-overlap F1 (bag of words, SQuAD style)."""
    c, r = tokens(candidate), tokens(reference)
    if not c or not r:
        return 1.0 if c == r else 0.0
    remaining = {}
    for t in r:
        remaining[t] = remaining.get(t, 0) + 1
    overlap = 0
    for t in c:
        if remaining.get(t, 0) > 0:
            remaining[t] -= 1
            overlap += 1
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(c), overlap / len(r)
    return 2 * precision * recall / (precision + recall)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        raise ValueError("No values")
    if not 0 < pct <= 100:
        raise ValueError("pct must be in (0, 100]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def evaluate(case: EvalCase, output: str, thresholds: Thresholds) -> list[str]:
    """Return a list of human-readable failures (empty means pass)."""
    failures = []
    if len(output) < thresholds.min_chars:
        failures.append(f"output shorter than {thresholds.min_chars} chars")
    if len(output) > thresholds.max_chars:
        failures.append(f"output longer than {thresholds.max_chars} chars")
    lowered = output.lower()
    failures += [f"missing required term {t!r}" for t in case.must_contain if t.lower() not in lowered]
    failures += [f"contains forbidden term {t!r}" for t in case.must_not_contain if t.lower() in lowered]
    if case.expect_json:
        try:
            json.loads(output)
        except ValueError:
            failures.append("output is not valid JSON")
    if case.reference is not None:
        minimum = case.min_f1 if case.min_f1 is not None else thresholds.min_f1
        score = f1_score(output, case.reference)
        if score < minimum:
            failures.append(f"F1 {score:.2f} below {minimum:.2f}")
    return failures
