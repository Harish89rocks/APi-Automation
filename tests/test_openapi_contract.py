import pytest
from jsonschema import ValidationError

from contract_utils import (
    documented_statuses,
    get_operation,
    iter_operations,
    validate_document,
    validate_response,
    validate_schema,
)

pytestmark = [pytest.mark.contract]

VALID_USER = {"name": "Harish", "email": "harish@example.com"}


# ---- the practice API's generated spec ------------------------------------


def test_spec_is_a_valid_openapi_document(openapi_spec):
    validate_document(openapi_spec)
    assert openapi_spec["openapi"].startswith("3.")
    assert openapi_spec["info"]["title"]


def test_create_user_operation_is_documented(openapi_spec):
    operation = get_operation(openapi_spec, "/users", "post")

    assert operation["requestBody"]["required"] is True
    assert "application/json" in operation["requestBody"]["content"]
    assert documented_statuses(openapi_spec, "/users", "post") == {201, 422}


def test_user_request_schema_constraints(openapi_spec):
    user = openapi_spec["components"]["schemas"]["User"]

    assert set(user["required"]) == {"name", "email"}
    assert user["properties"]["name"]["minLength"] == 1
    assert user["properties"]["email"]["format"] == "email"


def test_success_response_schema_is_not_empty(openapi_spec):
    """Guards against an undocumented 201 body (schema ``{}``)."""
    content = get_operation(openapi_spec, "/users", "post")["responses"]["201"][
        "content"
    ]["application/json"]

    assert content["schema"], "201 response has no schema in the contract"


def test_every_operation_has_a_success_response(openapi_spec):
    for path, method, operation in iter_operations(openapi_spec):
        codes = [c for c in operation["responses"] if c.startswith("2")]
        assert codes, f"{method.upper()} {path} documents no 2xx response"


# ---- live responses conform to the contract --------------------------------


def test_created_user_response_matches_contract(local_api, openapi_spec):
    response = local_api.post("/users", json=VALID_USER)

    assert response.status_code == 201
    validate_response(openapi_spec, "/users", "post", 201, response.json())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "", "email": "harish@example.com"},
        {"name": "   ", "email": "harish@example.com"},
        {"name": "Harish", "email": "not-an-email"},
        {"name": 123, "email": "harish@example.com"},
        {"name": None, "email": None},
    ],
    ids=[
        "empty-object",
        "empty-name",
        "blank-name",
        "bad-email",
        "wrong-type",
        "nulls",
    ],
)
def test_validation_error_matches_contract(local_api, openapi_spec, payload):
    response = local_api.post("/users", json=payload)

    assert response.status_code == 422
    validate_response(openapi_spec, "/users", "post", 422, response.json())


def test_response_status_is_always_documented(local_api, openapi_spec):
    documented = documented_statuses(openapi_spec, "/users", "post")
    payloads = [VALID_USER, {}, {"name": ""}, {"email": "x"}]

    for payload in payloads:
        status = local_api.post("/users", json=payload).status_code
        assert status in documented, f"undocumented status {status}"


def test_contract_validator_rejects_a_broken_response(openapi_spec):
    """The validator must fail on a body that violates the contract."""
    broken = {"message": "ok", "user": {"name": "Harish"}}

    with pytest.raises(ValidationError):
        validate_response(openapi_spec, "/users", "post", 201, broken)


def test_undocumented_status_is_flagged(openapi_spec):
    with pytest.raises(AssertionError, match="undocumented status 500"):
        validate_response(openapi_spec, "/users", "post", 500, {})


def test_request_schema_accepts_valid_and_rejects_invalid(openapi_spec):
    schema = {"$ref": "#/components/schemas/User"}

    validate_schema(openapi_spec, schema, VALID_USER)
    with pytest.raises(ValidationError):
        validate_schema(openapi_spec, schema, {"name": "Harish"})


# ---- real backend service spec (opt-in via OPENAPI_SPEC_URL) ----------------


@pytest.mark.external
def test_backend_spec_is_valid(backend_openapi_spec):
    validate_document(backend_openapi_spec)


@pytest.mark.external
def test_backend_operations_are_well_formed(backend_openapi_spec):
    operation_ids = []

    for path, method, operation in iter_operations(backend_openapi_spec):
        codes = [c for c in operation["responses"] if c.startswith("2")]
        assert codes, f"{method.upper()} {path} documents no 2xx response"
        if "operationId" in operation:
            operation_ids.append(operation["operationId"])

    assert len(operation_ids) == len(set(operation_ids)), (
        "operationId values must be unique"
    )
