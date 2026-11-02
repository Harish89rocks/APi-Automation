import pytest

pytestmark = [pytest.mark.integration, pytest.mark.negative]

EMAIL = "harish@example.com"


# ---- name boundaries ----------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "H",
        "Harish",
        "H" * 255,
        "H" * 10_000,
        "  padded  ",
        "Zoë Müller",
        "李雷",
        "O'Brien; DROP TABLE users;--",
        "<script>alert(1)</script>",
    ],
    ids=[
        "min-length-1",
        "typical",
        "len-255",
        "len-10000",
        "padded-whitespace",
        "accented",
        "cjk",
        "sql-like",
        "html-like",
    ],
)
def test_valid_name_boundaries_are_accepted(local_api, name):
    response = local_api.post("/users", json={"name": name, "email": EMAIL})

    assert response.status_code == 201
    assert response.json()["user"]["name"] == name


@pytest.mark.parametrize("name", ["", " ", "\t", "\n", "   \t\n  "])
def test_blank_names_are_rejected(local_api, name):
    response = local_api.post("/users", json={"name": name, "email": EMAIL})

    assert response.status_code == 422
    locations = [e["loc"] for e in response.json()["detail"]]
    assert ["body", "name"] in locations


# ---- email boundaries -----------------------------------------------------


def test_email_local_part_at_64_chars_is_accepted(local_api):
    email = f"{'a' * 64}@example.com"

    response = local_api.post("/users", json={"name": "H", "email": email})

    assert response.status_code == 201


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN DEFECT: practice_api accepts a local part >64 chars "
        "(RFC 5321 limit); email-validator 2.3.0 does not enforce it. "
        "Add an explicit length check to User.email to fix."
    ),
)
def test_email_local_part_over_64_chars_is_rejected(local_api):
    email = f"{'a' * 65}@example.com"

    response = local_api.post("/users", json={"name": "H", "email": email})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "email",
    [
        "plainaddress",
        "@example.com",
        "user@",
        "user@@example.com",
        "user name@example.com",
        "user@example..com",
        ".user@example.com",
        "user@-example.com",
    ],
)
def test_malformed_emails_are_rejected(local_api, email):
    response = local_api.post("/users", json={"name": "H", "email": email})

    assert response.status_code == 422


# ---- type confusion ---------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"name": 123, "email": EMAIL},
        {"name": ["H"], "email": EMAIL},
        {"name": {"first": "H"}, "email": EMAIL},
        {"name": True, "email": EMAIL},
        {"name": "H", "email": 123},
        {"name": "H", "email": None},
        {"name": None, "email": EMAIL},
    ],
    ids=[
        "name-int",
        "name-list",
        "name-object",
        "name-bool",
        "email-int",
        "email-null",
        "name-null",
    ],
)
def test_wrong_types_are_rejected(local_api, payload):
    response = local_api.post("/users", json=payload)

    assert response.status_code == 422


# ---- malformed requests -----------------------------------------------------


@pytest.mark.parametrize(
    "body",
    ["", "not json", '{"name": "H", "email":', "[]", "null", '"string"'],
    ids=["empty", "plain-text", "truncated", "array", "null", "string"],
)
def test_malformed_bodies_are_rejected(local_api, body):
    response = local_api.post(
        "/users",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_missing_content_type_with_json_text_is_rejected(local_api):
    response = local_api.post(
        "/users",
        content='{"name": "H", "email": "harish@example.com"}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 422


def test_unknown_fields_are_ignored_not_echoed(local_api):
    response = local_api.post(
        "/users",
        json={"name": "H", "email": EMAIL, "role": "admin", "id": 1},
    )

    assert response.status_code == 201
    assert set(response.json()["user"]) == {"name", "email"}


# ---- routing / method negatives -----------------------------------------


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_unsupported_methods_return_405(local_api, method):
    response = getattr(local_api, method)("/users")

    assert response.status_code == 405
    assert "POST" in response.headers["allow"]


def test_unknown_route_returns_404(local_api):
    assert local_api.post("/does-not-exist", json={}).status_code == 404


def test_error_response_does_not_leak_internals(local_api):
    response = local_api.post("/users", json={"name": "", "email": "x"})

    text = response.text.lower()
    assert "traceback" not in text
    assert "/opt/" not in text and "site-packages" not in text
