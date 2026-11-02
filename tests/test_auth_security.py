"""API security tests.

SIMULATED: these run in-process against the controlled practice app
(``auth_api.py``), not against a real backend. They verify the *test
harness's* contract for failures and information disclosure. Object-level
access to "another user's resources" is not applicable: the app has no
per-user resource endpoint, so none is invented. The identity endpoint is
checked instead to confirm it cannot be redirected to another subject.
"""

import logging
import time

import jwt
import pytest

from auth_api import settings
from tests.test_auth_jwt import bearer, forge, get_token, login

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PROTECTED = [("get", "/me"), ("get", "/reports"), ("post", "/auth/revoke"), ("delete", "/admin/users/1")]
FORBIDDEN_FRAGMENTS = ["Traceback", "File \"", "jwt.", "PyJWT", "site-packages", "secret", "algorithm"]


def assert_safe_error(response, status, *secrets):
    assert response.status_code == status
    body = response.json()
    assert set(body) <= {"detail", "error", "error_description"}
    text = response.text
    for fragment in (*FORBIDDEN_FRAGMENTS[:5], settings.secret, *secrets):
        assert fragment not in text, f"{fragment!r} leaked in error response"


@pytest.mark.parametrize("method, path", PROTECTED)
def test_unauthenticated_errors_are_uniform_and_safe(local_api, method, path):
    response = getattr(local_api, method)(path)

    assert_safe_error(response, 401)
    assert response.json() == {"detail": "Missing bearer token"}
    assert response.headers["www-authenticate"] == "Bearer"


def bad_tokens(good):
    head, payload, sig = good.split(".")
    return {
        "garbage": "not-a-jwt",
        "empty": "x",
        "two-segments": f"{head}.{payload}",
        "tampered-signature": f"{head}.{payload}.{sig[:-2]}AA",
        "wrong-key": jwt.encode(
            jwt.decode(good, options={"verify_signature": False}),
            "a-completely-different-signing-key-0123456789", algorithm="HS256"),
        "alg-none": jwt.encode({"sub": "admin"}, key=None, algorithm="none"),
        "expired": forge(exp=int(time.time()) - 60, iat=int(time.time()) - 400),
    }


def test_invalid_tokens_give_identical_generic_responses_without_an_oracle(local_api):
    good = login(local_api)
    seen = set()
    for name, token in bad_tokens(good).items():
        response = local_api.get("/me", headers=bearer(token))
        assert_safe_error(response, 401, token)
        seen.add((response.status_code, response.text) if name != "expired" else None)
    seen.discard(None)

    assert len(seen) == 1, "invalid tokens must not reveal why they were rejected"


@pytest.mark.parametrize("scheme", ["Basic", "Token", "bearer-x"])
def test_non_bearer_schemes_are_rejected(local_api, scheme):
    response = local_api.get("/me", headers={"Authorization": f"{scheme} abc"})

    assert_safe_error(response, 401, "abc")


def test_token_in_query_string_is_not_accepted(local_api):
    token = login(local_api)

    for key in ("access_token", "token"):
        assert local_api.get("/me", params={key: token}).status_code == 401


def test_identity_cannot_be_spoofed_by_query_or_headers(local_api):
    token = login(local_api, "reader")

    response = local_api.get(
        "/me?sub=admin&user=admin&role=admin",
        headers={**bearer(token), "X-User": "admin", "X-Forwarded-User": "admin", "X-Role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["sub"] == "reader" and response.json()["role"] == "user"


def test_role_and_scope_are_taken_from_the_signed_token_not_the_request(local_api):
    token = login(local_api, "reader")

    response = local_api.delete("/admin/users/1?role=admin&scope=admin", headers=bearer(token))

    assert_safe_error(response, 403)


def test_forbidden_response_does_not_list_required_roles_or_scopes_of_other_clients(local_api):
    response = local_api.get("/reports", headers=bearer(login(local_api, "noscope")))

    assert_safe_error(response, 403)
    assert "admin" not in response.text


def test_failed_login_responses_are_identical_for_unknown_client_and_wrong_secret(local_api):
    unknown = get_token(local_api, "reader", secret="x" * 22)
    form = {"grant_type": "client_credentials", "client_id": "ghost", "client_secret": "x" * 22}
    ghost = local_api.post("/auth/token", data=form)

    assert unknown.status_code == ghost.status_code == 401
    assert unknown.json() == ghost.json()


def test_login_errors_never_echo_submitted_secret(local_api):
    submitted = "SubmittedSecret-123456"
    response = get_token(local_api, "reader", secret=submitted)

    assert submitted not in response.text and settings.clients["reader"].secret not in response.text


def test_token_response_never_contains_client_secret_or_signing_key(local_api):
    response = get_token(local_api, "admin")

    assert settings.clients["admin"].secret not in response.text
    assert settings.secret not in response.text


def test_tokens_and_secrets_are_not_written_to_logs(local_api, caplog):
    with caplog.at_level(logging.DEBUG):
        token = login(local_api)
        local_api.get("/me", headers=bearer(token))
        local_api.get("/me", headers=bearer("bad." + token))
        get_token(local_api, "reader", secret="wrong-secret-value-1234")

    logged = caplog.text
    assert token not in logged
    assert settings.secret not in logged and settings.clients["reader"].secret not in logged
    assert "wrong-secret-value-1234" not in logged


def test_token_payload_holds_no_secrets(local_api):
    claims = jwt.decode(login(local_api, "admin"), options={"verify_signature": False})

    flattened = str(claims)
    assert settings.clients["admin"].secret not in flattened and settings.secret not in flattened
    assert "password" not in flattened.lower()
