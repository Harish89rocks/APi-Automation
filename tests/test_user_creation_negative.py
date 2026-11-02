import pytest

pytestmark = [pytest.mark.integration, pytest.mark.negative]


@pytest.mark.parametrize(
    "payload, expected_field",
    [
        ({"name": "", "email": "harish@example.com"}, "name"),
        ({"name": "Harish", "email": "not-an-email"}, "email"),
        ({"name": "Harish"}, "email"),
        ({"email": "harish@example.com"}, "name"),
    ],
)
def test_invalid_user_payload_returns_422(
    local_api, payload, expected_field
):
    response = local_api.post("/users", json=payload)

    assert response.status_code == 422

    response_data = response.json()
    assert "detail" in response_data

    errors = response_data["detail"]
    assert any(
        expected_field in error.get("loc", [])
        for error in errors
    )
