import time
import uuid

import jwt
import pytest

from auth_api import ALGORITHM, settings

pytestmark = [pytest.mark.integration, pytest.mark.auth]


def get_token(api, client_id="reader", scope=None, secret=None):
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret or settings.clients[client_id].secret,
    }
    if scope is not None:
        data["scope"] = scope
    return api.post("/auth/token", data=data)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def login(api, client_id="reader", **kw):
    response = get_token(api, client_id, **kw)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def forge(**overrides):
    """Build a token signed with the real key, with chosen claim overrides."""
    now = int(time.time())
    claims = {
        "iss": settings.issuer, "aud": settings.audience, "sub": "reader",
        "iat": now, "nbf": now, "exp": now + 300, "jti": str(uuid.uuid4()),
        "scope": "reports:read", "role": "user",
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None},
                      settings.secret, algorithm=ALGORITHM)


# ---- token endpoint -------------------------------------------------------------------


def test_token_response_follows_oauth2_shape(local_api):
    response = get_token(local_api, "admin")
    body = response.json()

    assert response.status_code == 200
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == settings.ttl_seconds
    assert body["scope"] == "admin reports:read"
    assert response.headers["Cache-Control"] == "no-store"


def test_token_claims_are_correct(local_api):
    token = login(local_api, "admin")

    claims = jwt.decode(token, settings.secret, algorithms=[ALGORITHM],
                        audience=settings.audience)

    assert (claims["iss"], claims["sub"], claims["role"]) == (settings.issuer, "admin", "admin")
    assert claims["exp"] - claims["iat"] == settings.ttl_seconds
    assert claims["jti"]


def test_each_token_has_unique_jti(local_api):
    a, b = login(local_api), login(local_api)

    ids = {jwt.decode(t, options={"verify_signature": False})["jti"] for t in (a, b)}
    assert len(ids) == 2


def test_requested_scope_narrows_token(local_api):
    body = get_token(local_api, "admin", scope="reports:read").json()

    assert body["scope"] == "reports:read"


@pytest.mark.parametrize(
    "client_id, secret",
    [("reader", "wrong"), ("reader", ""), ("ghost", "anything"), ("", "")],
    ids=["bad-secret", "empty-secret", "unknown-client", "empty-both"],
)
def test_bad_client_credentials_are_401(local_api, client_id, secret):
    response = local_api.post("/auth/token", data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": secret})

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    assert "access_token" not in response.text


def test_unknown_client_and_wrong_secret_are_indistinguishable(local_api):
    wrong = local_api.post("/auth/token", data={
        "grant_type": "client_credentials", "client_id": "reader", "client_secret": "x"})
    unknown = local_api.post("/auth/token", data={
        "grant_type": "client_credentials", "client_id": "ghost", "client_secret": "x"})

    assert wrong.json() == unknown.json()


def test_unsupported_grant_type(local_api):
    response = local_api.post("/auth/token", data={"grant_type": "password"})

    assert (response.status_code, response.json()["error"]) == (400, "unsupported_grant_type")


def test_scope_not_allowed_for_client_is_rejected(local_api):
    response = get_token(local_api, "reader", scope="admin")

    assert (response.status_code, response.json()["error"]) == (400, "invalid_scope")


# ---- authentication (401) ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/me", "/reports"])
def test_missing_token_is_401_with_challenge(local_api, path):
    response = local_api.get(path)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer ", "Basic abc", "bearer-token", "Token abc", "Bearer not.a.jwt"],
)
def test_malformed_authorization_header_is_401(local_api, header):
    assert local_api.get("/me", headers={"Authorization": header}).status_code == 401


def test_valid_token_authenticates(local_api):
    response = local_api.get("/me", headers=bearer(login(local_api)))

    assert response.status_code == 200
    assert response.json() == {"sub": "reader", "role": "user", "scope": "reports:read"}


def test_expired_token_is_401(local_api):
    token = forge(iat=int(time.time()) - 600, exp=int(time.time()) - 10)

    response = local_api.get("/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired"


def test_token_expires_at_the_boundary(local_api, monkeypatch):
    monkeypatch.setattr(settings, "ttl_seconds", 1)
    token = login(local_api)
    assert local_api.get("/me", headers=bearer(token)).status_code == 200

    time.sleep(2.1)

    assert local_api.get("/me", headers=bearer(token)).status_code == 401


def test_token_not_yet_valid_is_401(local_api):
    token = forge(nbf=int(time.time()) + 3600)

    assert local_api.get("/me", headers=bearer(token)).status_code == 401


def test_tampered_payload_is_rejected(local_api):
    head, _, sig = login(local_api).split(".")
    evil = jwt.encode({"sub": "reader", "role": "admin"}, "x" * 32, algorithm=ALGORITHM).split(".")[1]

    assert local_api.get("/me", headers=bearer(f"{head}.{evil}.{sig}")).status_code == 401


def test_token_signed_with_wrong_key_is_rejected(local_api):
    token = jwt.encode(
        {"iss": settings.issuer, "aud": settings.audience, "sub": "admin", "role": "admin",
         "jti": "1", "iat": int(time.time()), "exp": int(time.time()) + 300},
        "attacker-key-attacker-key-attacker-key", algorithm=ALGORITHM)

    assert local_api.get("/me", headers=bearer(token)).status_code == 401


def test_alg_none_token_is_rejected(local_api):
    token = jwt.encode({"sub": "admin", "role": "admin", "scope": "admin reports:read"},
                       key=None, algorithm="none")

    assert local_api.get("/reports", headers=bearer(token)).status_code == 401


# The real key is deliberately reused (to prove only the algorithm differs); it is
# shorter than HS512 recommends, which PyJWT flags.
@pytest.mark.filterwarnings("ignore:The HMAC key is:Warning")
def test_other_hmac_algorithm_is_rejected(local_api):
    token = jwt.encode(
        {"iss": settings.issuer, "aud": settings.audience, "sub": "a", "jti": "1",
         "iat": int(time.time()), "exp": int(time.time()) + 300},
        settings.secret, algorithm="HS512")

    assert local_api.get("/me", headers=bearer(token)).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "someone-else"}, {"iss": "evil-issuer"}, {"exp": None}, {"sub": None}, {"jti": None}],
    ids=["wrong-audience", "wrong-issuer", "no-exp", "no-sub", "no-jti"],
)
def test_token_with_bad_or_missing_claims_is_rejected(local_api, overrides):
    assert local_api.get("/me", headers=bearer(forge(**overrides))).status_code == 401


# ---- authorization (403) -------------------------------------------------------------------


def test_missing_scope_is_403_not_401(local_api):
    token = login(local_api, "noscope")

    response = local_api.get("/reports", headers=bearer(token))

    assert response.status_code == 403
    assert "reports:read" in response.json()["detail"]


def test_required_scope_grants_access(local_api):
    response = local_api.get("/reports", headers=bearer(login(local_api)))

    assert response.status_code == 200
    assert response.json()["requested_by"] == "reader"


def test_role_user_cannot_use_admin_endpoint(local_api):
    response = local_api.delete("/admin/users/1", headers=bearer(login(local_api)))

    assert response.status_code == 403


def test_admin_role_and_scope_can_use_admin_endpoint(local_api):
    response = local_api.delete("/admin/users/1", headers=bearer(login(local_api, "admin")))

    assert response.status_code == 204


def test_admin_role_without_admin_scope_is_403(local_api):
    token = login(local_api, "admin", scope="reports:read")

    assert local_api.delete("/admin/users/1", headers=bearer(token)).status_code == 403


def test_role_claim_forged_in_unsigned_part_cannot_escalate(local_api):
    token = forge(role="admin")  # properly signed but scope lacks "admin"

    assert local_api.delete("/admin/users/1", headers=bearer(token)).status_code == 403


def test_scope_matching_is_exact_not_substring(local_api):
    token = forge(scope="reports:readonly")

    assert local_api.get("/reports", headers=bearer(token)).status_code == 403


# ---- revocation -----------------------------------------------------------------------------


def test_revoked_token_cannot_be_replayed(local_api):
    token = login(local_api)
    assert local_api.get("/me", headers=bearer(token)).status_code == 200

    assert local_api.post("/auth/revoke", headers=bearer(token)).status_code == 200

    response = local_api.get("/me", headers=bearer(token))
    assert response.status_code == 401 and response.json()["detail"] == "Token revoked"


def test_revoking_one_token_does_not_affect_another(local_api):
    first, second = login(local_api), login(local_api)

    local_api.post("/auth/revoke", headers=bearer(first))

    assert local_api.get("/me", headers=bearer(second)).status_code == 200


# ---- existing public endpoints stay open --------------------------------------------------------


def test_public_endpoints_do_not_require_auth(local_api):
    assert local_api.get("/health").status_code == 200
    assert local_api.post("/users", json={"name": "H", "email": "h@example.com"}).status_code == 201
