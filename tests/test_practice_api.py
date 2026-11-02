import pytest

pytestmark = [pytest.mark.integration]


def test_create_user_valid_payload(local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish", "email": "harish@example.com"},
    )

    assert response.status_code == 201
    assert response.json()["user"]["name"] == "Harish"


def test_create_user_empty_name(local_api):
    response = local_api.post(
        "/users",
        json={"name": "", "email": "harish@example.com"},
    )

    assert response.status_code == 422


def test_create_user_invalid_email(local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish", "email": "not-an-email"},
    )

    assert response.status_code == 422


def test_create_user_missing_email(local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish"},
    )

    assert response.status_code == 422


def test_create_user_missing_name(local_api):
    response = local_api.post(
        "/users",
        json={"email": "harish@example.com"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "email",
    [
        "not-an-email",
        "missing-at-symbol.com",
        "user@",
        "",
    ],
)
def test_invalid_email_formats(email, local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish", "email": email},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("name", ["", "   "])
def test_invalid_names(name, local_api):
    response = local_api.post(
        "/users",
        json={"name": name, "email": "harish@example.com"},
    )

    assert response.status_code == 422

def test_valid_user_response_body(local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish", "email": "harish@example.com"},
    )

    assert response.status_code == 201

    body = response.json()
    assert body["message"] == "User created successfully"
    assert body["user"]["name"] == "Harish"
    assert body["user"]["email"] == "harish@example.com"


def test_invalid_email_error_identifies_email_field(local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish", "email": "not-an-email"},
    )

    assert response.status_code == 422

    body = response.json()
    assert "detail" in body

    error_locations = [error["loc"] for error in body["detail"]]
    assert ["body", "email"] in error_locations


def test_missing_email_error_identifies_email_field(local_api):
    response = local_api.post(
        "/users",
        json={"name": "Harish"},
    )

    assert response.status_code == 422

    body = response.json()
    error_locations = [error["loc"] for error in body["detail"]]
    assert ["body", "email"] in error_locations


def test_whitespace_name_error_identifies_name_field(local_api):
    response = local_api.post(
        "/users",
        json={"name": "   ", "email": "harish@example.com"},
    )

    assert response.status_code == 422

    body = response.json()
    error_locations = [error["loc"] for error in body["detail"]]
    assert ["body", "name"] in error_locations

