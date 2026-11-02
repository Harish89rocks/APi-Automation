"""Helpers for validating API behaviour against an OpenAPI 3.x document."""

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
