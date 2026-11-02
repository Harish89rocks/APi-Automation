import pytest

pytestmark = [pytest.mark.external]


@pytest.mark.parametrize(
    "user_id",
    [1, 2, 3],
)
def test_get_multiple_users(api_client, user_id):
    response = api_client.get(f"/users/{user_id}")

    assert response.status_code == 200

    user = response.json()
    assert user["id"] == user_id
def test_get_user(api_client):
    response = api_client.get("/users/1")

    assert response.status_code == 200

    user = response.json()
    assert user["id"] == 1
    assert "name" in user


def test_create_user(api_client):
    payload = {
        "name": "Harish",
        "username": "qa_engineer",
        "email": "harish@example.com"
    }

    response = api_client.post("/users", payload)

    assert response.status_code == 201

    created_user = response.json()

    assert created_user["name"] == "Harish"
    assert created_user["email"] == "harish@example.com"

def test_get_user_response_time(api_client):
    response = api_client.get("/users/1")

    assert response.status_code == 200

    response_time = response.elapsed.total_seconds()
    print(f"Observed API response time: {response_time:.3f} seconds")
