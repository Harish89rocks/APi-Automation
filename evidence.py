"""Defect evidence: record redacted HTTP exchanges and attach them to failures.

``EvidenceRecorder`` wraps the ``send`` methods of requests/httpx/httpx2 for the
duration of a test. On failure the conftest hook writes the exchanges to
``artifacts/evidence/<test>.json`` and embeds them in the pytest-html report.
Secrets are redacted before anything is stored.
"""

import importlib
import json
import re
import time
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "***REDACTED***"
MAX_BODY = 4000
SENSITIVE_KEYS = re.compile(
    r"authorization|cookie|token|secret|password|passwd|api[-_]?key|private[-_]?key|assertion",
    re.IGNORECASE,
)
JWT_PATTERN = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]*")
BEARER_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[\w.~+/=-]+")


KEY_VALUE_PATTERN = re.compile(
    r"""(?i)((?:authorization|cookie|[\w-]*(?:token|secret|password|passwd|api[-_]?key|private[-_]?key))
    ["']?\s*[:=]\s*["']?)([^"'\s,&}]+)""",
    re.VERBOSE,
)


def redact_text(text: str) -> str:
    text = KEY_VALUE_PATTERN.sub(lambda m: m.group(1) + REDACTED, text)
    text = JWT_PATTERN.sub(REDACTED, text)
    return BEARER_PATTERN.sub(lambda m: f"{m.group(1)} {REDACTED}", text)


def redact_value(value):
    if isinstance(value, dict):
        return {k: REDACTED if SENSITIVE_KEYS.search(str(k)) else redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_headers(headers) -> dict:
    return {k: REDACTED if SENSITIVE_KEYS.search(k) else redact_text(v) for k, v in dict(headers).items()}


def redact_url(url: str) -> str:
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    query = urlencode(
        [(k, REDACTED if SENSITIVE_KEYS.search(k) else v) for k, v in parse_qsl(parts.query)]
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def redact_body(body) -> str:
    if body is None or body == b"":
        return ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    try:
        text = json.dumps(redact_value(json.loads(body)))
    except ValueError:
        if "=" in body and "&" in body or re.fullmatch(r"[\w.%+-]+=[^\s]*", body):
            text = urlencode([(k, REDACTED if SENSITIVE_KEYS.search(k) else v) for k, v in parse_qsl(body)])
        else:
            text = redact_text(body)
    return text if len(text) <= MAX_BODY else text[:MAX_BODY] + f"...[truncated {len(text) - MAX_BODY} chars]"


def _request_body(request):
    if hasattr(request, "body"):  # requests.PreparedRequest
        return request.body
    try:
        return request.content  # httpx
    except Exception:
        return None


class EvidenceRecorder:
    def __init__(self):
        self.exchanges: list[dict] = []

    def _record(self, request, response, started, error=None):
        entry = {
            "method": request.method,
            "url": redact_url(request.url),
            "request_headers": redact_headers(request.headers),
            "request_body": redact_body(_request_body(request)),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if response is not None:
            entry["status"] = response.status_code
            entry["response_headers"] = redact_headers(response.headers)
            try:
                entry["response_body"] = redact_body(response.content)
            except Exception:
                entry["response_body"] = "<streaming body not captured>"
        if error is not None:
            entry["error"] = type(error).__name__
        self.exchanges.append(entry)

    @contextmanager
    def active(self):
        patches = []

        def wrap(owner, name, is_async):
            original = getattr(owner, name)
            recorder = self

            if is_async:
                async def patched(self_, request, *a, **kw):
                    started = time.perf_counter()
                    try:
                        response = await original(self_, request, *a, **kw)
                    except Exception as error:
                        recorder._record(request, None, started, error)
                        raise
                    recorder._record(request, response, started)
                    return response
            else:
                def patched(self_, request, *a, **kw):
                    started = time.perf_counter()
                    try:
                        response = original(self_, request, *a, **kw)
                    except Exception as error:
                        recorder._record(request, None, started, error)
                        raise
                    recorder._record(request, response, started)
                    return response

            setattr(owner, name, patched)
            patches.append((owner, name, original))

        for module_name, client_cls, async_cls in (
            ("requests", "Session", None),
            ("httpx", "Client", "AsyncClient"),
            ("httpx2", "Client", "AsyncClient"),
        ):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            wrap(getattr(module, client_cls), "send", False)
            if async_cls:
                wrap(getattr(module, async_cls), "send", True)
        try:
            yield self
        finally:
            for owner, name, original in reversed(patches):
                setattr(owner, name, original)


def safe_filename(nodeid: str) -> str:
    return re.sub(r"[^\w.-]+", "_", nodeid)[:150]


def render_html(exchanges: list[dict]) -> str:
    from html import escape

    if not exchanges:
        return "<p>No HTTP exchanges were recorded for this test.</p>"
    rows = []
    for i, e in enumerate(exchanges, 1):
        status = e.get("status", e.get("error", "n/a"))
        rows.append(
            f"<details><summary>#{i} {escape(e['method'])} {escape(e['url'])} → {escape(str(status))} "
            f"({e['elapsed_ms']} ms)</summary><pre>{escape(json.dumps(e, indent=2))}</pre></details>"
        )
    return "".join(rows)
