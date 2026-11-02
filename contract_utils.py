"""Helpers for validating API behaviour against an OpenAPI 3.x document."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import requests
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_openapi_document

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch"}


def validate_document(spec: dict) -> None:
    """Raise if ``spec`` is not a valid OpenAPI document."""
    validate_openapi_document(spec)


def iter_operations(spec: dict):
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def get_operation(spec: dict, path: str, method: str) -> dict:
    return spec["paths"][path][method.lower()]


def documented_statuses(spec: dict, path: str, method: str) -> set[int]:
    responses = get_operation(spec, path, method)["responses"]
    return {int(code) for code in responses if code.isdigit()}


def validate_schema(spec: dict, schema: dict, instance) -> None:
    """Validate ``instance`` against a schema that may contain local $refs."""
    resolved = {**schema, "components": spec.get("components", {})}
    Draft202012Validator(resolved).validate(instance)


def validate_response(
    spec: dict,
    path: str,
    method: str,
    status_code: int,
    body,
) -> None:
    """Validate a response body against the schema documented for its status."""
    responses = get_operation(spec, path, method)["responses"]
    assert str(status_code) in responses, (
        f"{method.upper()} {path} returned undocumented status {status_code};"
        f" documented: {sorted(responses)}"
    )
    content = responses[str(status_code)].get("content", {})
    schema = content.get("application/json", {}).get("schema")
    assert schema, (
        f"{method.upper()} {path} {status_code} documents no JSON schema"
    )
    validate_schema(spec, schema, body)


# ---- loading a spec from a URL or file ---------------------------------------


class SpecLoadError(RuntimeError):
    """A configured OpenAPI source cannot be retrieved, parsed or is invalid."""


def _describe(source: str) -> str:
    """Source for error messages, without query string or credentials."""
    parts = urlsplit(source)
    if parts.scheme in ("http", "https"):
        return f"{parts.scheme}://{parts.hostname}{parts.path}"
    return source


def _parse_document(text: str):
    try:
        return json.loads(text)
    except ValueError as json_error:
        try:
            import yaml
        except ImportError:
            raise SpecLoadError(
                f"not valid JSON ({json_error}); install PyYAML to read YAML specs"
            ) from None
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as yaml_error:
            raise SpecLoadError(
                f"neither valid JSON nor valid YAML ({str(yaml_error).splitlines()[0]})"
            ) from None


def load_spec(source: str, variable: str = "OPENAPI_SPEC_URL", timeout: float = 15) -> dict:
    """Retrieve, parse and validate an OpenAPI 3.x document.

    ``source`` is an http(s) URL or a local file. Every failure raises
    SpecLoadError naming ``variable`` and the cause.
    """
    where = f"{variable} ({_describe(source)})"
    if source.startswith(("http://", "https://")):
        try:
            response = requests.get(source, timeout=timeout)
        except requests.RequestException as error:
            raise SpecLoadError(
                f"{where} is not reachable: {type(error).__name__}"
            ) from None
        if not response.ok:
            raise SpecLoadError(f"{where} returned HTTP {response.status_code}")
        text = response.text
    else:
        path = Path(source)
        if not path.is_file():
            raise SpecLoadError(f"{where}: file not found")
        text = path.read_text(encoding="utf-8")

    try:
        document = _parse_document(text)
    except SpecLoadError as error:
        raise SpecLoadError(f"{where} could not be parsed: {error}") from None
    if not isinstance(document, dict):
        raise SpecLoadError(f"{where} is not an object (got {type(document).__name__})")
    if "openapi" not in document:
        raise SpecLoadError(f"{where} is not an OpenAPI 3.x document (no 'openapi' field)")
    try:
        validate_document(document)
    except Exception as error:
        first_line = (str(error).strip().splitlines() or [type(error).__name__])[0]
        raise SpecLoadError(f"{where} is not a valid OpenAPI document: {first_line}") from None
    return document


# ---- backward-compatibility check against a baseline ----------------------------


def _resolve(spec: dict, schema, seen=()):
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen or not ref.startswith("#/"):
            return {}
        seen += (ref,)
        node = spec
        for part in ref[2:].split("/"):
            node = node.get(part, {})
        schema = node
    return schema if isinstance(schema, dict) else {}


def _json_schema(spec: dict, container: dict) -> dict:
    content = (container or {}).get("content", {})
    return _resolve(spec, content.get("application/json", {}).get("schema", {}))


def _schema_changes(base_spec, base, cur_spec, cur, where, direction, depth=0):
    base, cur = _resolve(base_spec, base), _resolve(cur_spec, cur)
    problems = []
    if depth > 6 or not base:
        return problems
    if base.get("type") and cur.get("type") and base["type"] != cur["type"]:
        problems.append(f"{where}: type changed {base['type']} -> {cur['type']}")
        return problems

    base_props, cur_props = base.get("properties", {}), cur.get("properties", {})
    base_req, cur_req = set(base.get("required", [])), set(cur.get("required", []))
    if direction == "response":
        for name in base_props:
            if name not in cur_props:
                problems.append(f"{where}: property '{name}' removed")
        for name in base_req - cur_req:
            problems.append(f"{where}: property '{name}' is no longer guaranteed (not required)")
    else:
        for name in cur_req - base_req:
            problems.append(f"{where}: new required property '{name}'")
    for name in base_props.keys() & cur_props.keys():
        problems += _schema_changes(
            base_spec, base_props[name], cur_spec, cur_props[name],
            f"{where}.{name}", direction, depth + 1,
        )
    if "items" in base and "items" in cur:
        problems += _schema_changes(
            base_spec, base["items"], cur_spec, cur["items"], f"{where}[]", direction, depth + 1
        )
    return problems


def _effective_security(spec: dict, operation: dict):
    return operation.get("security", spec.get("security", []))


def breaking_changes(baseline: dict, current: dict) -> list[str]:
    """Differences that would break clients written against ``baseline``.

    Only compares what the two documents declare; it cannot prove runtime
    behaviour. Returns an empty list when no breaking change is found.
    """
    problems = []
    for path, item in baseline.get("paths", {}).items():
        for method, base_op in item.items():
            if method not in HTTP_METHODS:
                continue
            label = f"{method.upper()} {path}"
            cur_op = current.get("paths", {}).get(path, {}).get(method)
            if cur_op is None:
                problems.append(f"{label}: operation removed")
                continue

            for status, base_resp in base_op.get("responses", {}).items():
                cur_resp = cur_op.get("responses", {}).get(status)
                if cur_resp is None:
                    problems.append(f"{label}: response {status} removed")
                    continue
                problems += _schema_changes(
                    baseline, _json_schema(baseline, base_resp),
                    current, _json_schema(current, cur_resp),
                    f"{label} response {status}", "response",
                )

            base_body, cur_body = base_op.get("requestBody"), cur_op.get("requestBody")
            if cur_body and cur_body.get("required") and not (base_body or {}).get("required"):
                problems.append(f"{label}: request body is now required")
            if base_body and cur_body:
                problems += _schema_changes(
                    baseline, _json_schema(baseline, base_body),
                    current, _json_schema(current, cur_body),
                    f"{label} request body", "request",
                )

            def params(spec, op):
                merged = item_params(spec, path) + op.get("parameters", [])
                return {(p["in"], p["name"]): p for p in merged if "name" in p}

            base_params, cur_params = params(baseline, base_op), params(current, cur_op)
            for key, param in cur_params.items():
                if param.get("required") and not base_params.get(key, {}).get("required"):
                    problems.append(f"{label}: parameter {key[1]} ({key[0]}) is now required")

            if _effective_security(current, cur_op) and not _effective_security(baseline, base_op):
                problems.append(f"{label}: authentication is now required")
    return problems


def item_params(spec: dict, path: str) -> list:
    return spec.get("paths", {}).get(path, {}).get("parameters", [])


def spec_from_env(variable: str) -> dict:
    """Skip when ``variable`` is unset; fail when it is set but unusable."""
    import os

    import pytest

    source = os.getenv(variable)
    if not source:
        pytest.skip(f"{variable} not set")
    try:
        return load_spec(source, variable)
    except SpecLoadError as error:
        pytest.fail(str(error), pytrace=False)
