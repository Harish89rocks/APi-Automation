"""Extended OpenAPI contract tests.

* Spec loading/validation failures (offline, using local files and a local server).
* Contract of the in-process practice API: operations, parameters, schemas,
  authentication requirements and error responses. (Simulated target: our own app.)
* Breaking-change detection against a baseline: a snapshot of this app's own
  contract, or a real baseline via OPENAPI_BASELINE_SPEC (opt-in).
"""

import copy
import http.server
import json
import threading
from pathlib import Path

import pytest

from auth_api import settings
from contract_utils import (
    SpecLoadError,
    breaking_changes,
    documented_statuses,
    get_operation,
    iter_operations,
    load_spec,
    spec_from_env,
    validate_response,
    validate_schema,
)

pytestmark = [pytest.mark.contract]

BASELINE = Path(__file__).resolve().parent.parent / "contracts" / "practice_api.baseline.json"

VALID_MINIMAL = {
    "openapi": "3.0.3",
    "info": {"title": "t", "version": "1"},
    "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}},
}


# ---- loading and validating a configured spec -------------------------------------------


@pytest.fixture
def spec_server():
    """Local HTTP server returning (status, body) per path; yields (base_url, routes)."""
    routes: dict[str, tuple[int, str]] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = routes.get(self.path, (404, "not found"))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", routes
    server.shutdown()
    server.server_close()


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_valid_file_is_loaded(tmp_path):
    source = write(tmp_path, "spec.json", json.dumps(VALID_MINIMAL))

    assert load_spec(source)["info"]["title"] == "t"


def test_valid_yaml_file_is_loaded(tmp_path):
    yaml = pytest.importorskip("yaml")
    source = write(tmp_path, "spec.yaml", yaml.safe_dump(VALID_MINIMAL))

    assert load_spec(source)["openapi"] == "3.0.3"


def test_valid_spec_is_loaded_over_http(spec_server):
    base, routes = spec_server
    routes["/openapi.json"] = (200, json.dumps(VALID_MINIMAL))

    assert load_spec(f"{base}/openapi.json")["paths"]


@pytest.mark.parametrize(
    "content, message",
    [
        ("{ not json", "could not be parsed"),
        ("[1, 2]", "is not an object"),
        ('{"swagger": "2.0"}', "no 'openapi' field"),
        (json.dumps({"openapi": "3.0.3"}), "not a valid OpenAPI document"),
        (json.dumps({**VALID_MINIMAL, "paths": {"/x": {"get": {}}}}), "not a valid OpenAPI document"),
    ],
    ids=["malformed-json", "wrong-top-level-type", "swagger-2", "missing-required-sections", "operation-without-responses"],
)
def test_bad_documents_fail_with_a_specific_message(tmp_path, content, message):
    with pytest.raises(SpecLoadError, match=message):
        load_spec(write(tmp_path, "bad.json", content), "OPENAPI_SPEC_URL")


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(SpecLoadError, match="file not found"):
        load_spec(str(tmp_path / "nope.json"))


def test_http_error_status_is_reported(spec_server):
    base, routes = spec_server
    routes["/openapi.json"] = (503, "down")

    with pytest.raises(SpecLoadError, match="HTTP 503"):
        load_spec(f"{base}/openapi.json")


def test_unreachable_endpoint_is_reported(spec_server):
    base, _ = spec_server
    dead = base.rsplit(":", 1)[0] + ":1"  # nothing listens on port 1

    with pytest.raises(SpecLoadError, match="not reachable"):
        load_spec(f"{dead}/openapi.json", timeout=2)


def test_html_page_instead_of_spec_is_reported(spec_server):
    base, routes = spec_server
    routes["/openapi.json"] = (200, "<html>login</html>")

    with pytest.raises(SpecLoadError, match="could not be parsed|is not an object"):
        load_spec(f"{base}/openapi.json")


def test_error_messages_never_leak_url_credentials_or_query(spec_server):
    base, _ = spec_server
    secret_url = base.replace("http://", "http://user:s3cr3t@") + "/missing.json?token=abc123"

    with pytest.raises(SpecLoadError) as error:
        load_spec(secret_url)

    assert "s3cr3t" not in str(error.value) and "abc123" not in str(error.value)


def test_unset_spec_variable_skips(monkeypatch):
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)

    with pytest.raises(pytest.skip.Exception):
        spec_from_env("OPENAPI_SPEC_URL")


def test_set_but_invalid_spec_variable_fails_not_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAPI_SPEC_URL", write(tmp_path, "bad.json", "{ nope"))

    with pytest.raises(pytest.fail.Exception, match="could not be parsed"):
        spec_from_env("OPENAPI_SPEC_URL")


def test_set_but_unreachable_spec_variable_fails_not_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAPI_SPEC_URL", str(tmp_path / "absent.json"))

    with pytest.raises(pytest.fail.Exception, match="file not found"):
        spec_from_env("OPENAPI_SPEC_URL")


# ---- the practice API's contract ------------------------------------------------------------

EXPECTED_OPERATIONS = {
    ("/health", "get"): {200},
    ("/users", "post"): {201, 422},
    ("/auth/token", "post"): {200, 400, 401},
    ("/auth/revoke", "post"): {200, 401},
    ("/me", "get"): {200, 401},
    ("/reports", "get"): {200, 401, 403},
    ("/admin/users/{user_id}", "delete"): {204, 401, 403, 422},
}
PROTECTED = [("/auth/revoke", "post"), ("/me", "get"), ("/reports", "get"),
             ("/admin/users/{user_id}", "delete")]
PUBLIC = [("/health", "get"), ("/users", "post"), ("/auth/token", "post")]


def test_all_expected_operations_are_declared_with_their_statuses(openapi_spec):
    declared = {(p, m) for p, m, _ in iter_operations(openapi_spec)}

    assert declared == set(EXPECTED_OPERATIONS), "undeclared or unexpected operations"
    for (path, method), statuses in EXPECTED_OPERATIONS.items():
        assert documented_statuses(openapi_spec, path, method) >= statuses, (path, method)


def test_every_operation_has_a_documented_success_response(openapi_spec):
    for path, method, operation in iter_operations(openapi_spec):
        assert any(c.startswith("2") for c in operation["responses"]), (path, method)


def test_path_parameter_schema(openapi_spec):
    params = get_operation(openapi_spec, "/admin/users/{user_id}", "delete")["parameters"]

    assert params == [{"name": "user_id", "in": "path", "required": True,
                       "schema": {"type": "integer", "title": "User Id"}}]


def test_user_request_schema_required_fields_and_types(openapi_spec):
    schema = openapi_spec["components"]["schemas"]["User"]

    assert set(schema["required"]) == {"name", "email"}
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["email"]["format"] == "email"


def test_token_request_is_documented_as_form_encoded(openapi_spec):
    body = get_operation(openapi_spec, "/auth/token", "post")["requestBody"]
    schema = body["content"]["application/x-www-form-urlencoded"]["schema"]

    assert body["required"] is True
    assert set(schema["required"]) == {"grant_type", "client_id", "client_secret"}
    assert schema["properties"]["grant_type"]["enum"] == ["client_credentials"]


def test_token_response_schema_required_fields(openapi_spec):
    schema = openapi_spec["components"]["schemas"]["TokenResponse"]

    assert set(schema["required"]) == {"access_token", "token_type", "expires_in", "scope"}
    assert schema["properties"]["expires_in"]["type"] == "integer"


def test_bearer_security_scheme_is_declared(openapi_spec):
    scheme = openapi_spec["components"]["securitySchemes"]["HTTPBearer"]

    assert (scheme["type"], scheme["scheme"], scheme["bearerFormat"]) == ("http", "bearer", "JWT")


@pytest.mark.parametrize("path, method", PROTECTED)
def test_protected_operations_declare_authentication(openapi_spec, path, method):
    assert get_operation(openapi_spec, path, method).get("security") == [{"HTTPBearer": []}]


@pytest.mark.parametrize("path, method", PUBLIC)
def test_public_operations_declare_no_authentication(openapi_spec, path, method):
    assert not get_operation(openapi_spec, path, method).get("security")


def auth_headers(api, client="reader", **form):
    response = api.post("/auth/token", data={
        "grant_type": "client_credentials", "client_id": client,
        "client_secret": settings.clients[client].secret, **form})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_live_token_response_matches_contract(local_api, openapi_spec):
    response = local_api.post("/auth/token", data={
        "grant_type": "client_credentials", "client_id": "reader",
        "client_secret": settings.clients["reader"].secret})

    validate_response(openapi_spec, "/auth/token", "post", 200, response.json())


@pytest.mark.parametrize(
    "form, status",
    [({"grant_type": "password"}, 400),
     ({"grant_type": "client_credentials", "client_id": "reader", "client_secret": "bad"}, 401)],
    ids=["unsupported-grant", "bad-credentials"],
)
def test_live_oauth_error_responses_match_contract(local_api, openapi_spec, form, status):
    response = local_api.post("/auth/token", data=form)

    assert response.status_code == status
    validate_response(openapi_spec, "/auth/token", "post", status, response.json())


def test_live_unauthenticated_error_matches_contract(local_api, openapi_spec):
    response = local_api.get("/me")

    assert response.status_code == 401
    validate_response(openapi_spec, "/me", "get", 401, response.json())


def test_live_forbidden_error_matches_contract(local_api, openapi_spec):
    response = local_api.get("/reports", headers=auth_headers(local_api, "noscope"))

    assert response.status_code == 403
    validate_response(openapi_spec, "/reports", "get", 403, response.json())


def test_live_identity_response_matches_contract(local_api, openapi_spec):
    response = local_api.get("/me", headers=auth_headers(local_api))

    validate_response(openapi_spec, "/me", "get", 200, response.json())


def test_error_schema_rejects_non_string_detail(openapi_spec):
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        validate_schema(openapi_spec, {"$ref": "#/components/schemas/ErrorDetail"}, {"detail": 5})


# ---- breaking-change detection --------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_current_contract_has_no_breaking_changes_against_snapshot(baseline, openapi_spec):
    assert breaking_changes(baseline, openapi_spec) == []


def mutated(baseline, change):
    spec = copy.deepcopy(baseline)
    change(spec)
    return spec


@pytest.mark.parametrize(
    "change, expected",
    [
        (lambda s: s["paths"].pop("/users"), "POST /users: operation removed"),
        (lambda s: s["paths"]["/users"]["post"]["responses"].pop("422"), "response 422 removed"),
        (lambda s: s["components"]["schemas"]["CreateUserResponse"]["properties"].pop("message"),
         "property 'message' removed"),
        (lambda s: s["components"]["schemas"]["CreateUserResponse"]["required"].remove("message"),
         "no longer guaranteed"),
        (lambda s: s["components"]["schemas"]["CreateUserResponse"]["properties"]["message"].update(type="integer"),
         "type changed string -> integer"),
        (lambda s: s["components"]["schemas"]["User"]["required"].append("phone"),
         "new required property 'phone'"),
        (lambda s: s["paths"]["/health"]["get"].update(security=[{"HTTPBearer": []}]),
         "authentication is now required"),
        (lambda s: s["paths"]["/health"]["get"].update(
            parameters=[{"name": "v", "in": "query", "required": True, "schema": {"type": "string"}}]),
         "parameter v (query) is now required"),
    ],
    ids=["operation-removed", "status-removed", "response-field-removed", "response-field-optional",
         "type-changed", "new-required-input", "auth-added", "required-param-added"],
)
def test_breaking_changes_are_detected(baseline, change, expected):
    problems = breaking_changes(baseline, mutated(baseline, change))

    assert any(expected in p for p in problems), problems


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s["paths"].update({"/new": {"get": {"responses": {"200": {"description": "ok"}}}}}),
        lambda s: s["paths"]["/health"]["get"]["responses"].update({"503": {"description": "down"}}),
        lambda s: s["components"]["schemas"]["CreateUserResponse"]["properties"].update(
            {"extra": {"type": "string"}}),
        lambda s: s["components"]["schemas"]["User"]["properties"].update({"nickname": {"type": "string"}}),
    ],
    ids=["new-operation", "new-status", "new-optional-response-field", "new-optional-request-field"],
)
def test_additive_changes_are_not_reported_as_breaking(baseline, change):
    assert breaking_changes(baseline, mutated(baseline, change)) == []


# ---- real backend: opt-in ---------------------------------------------------------------------


@pytest.mark.external
def test_backend_has_no_breaking_changes_against_baseline(backend_openapi_spec, baseline_openapi_spec):
    problems = breaking_changes(baseline_openapi_spec, backend_openapi_spec)

    assert problems == [], "\n".join(problems)
