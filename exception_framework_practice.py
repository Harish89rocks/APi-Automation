import requests


class APIRequestError(Exception):
    """Raised when an API request fails."""


def get_user(user_id: int) -> dict:
    url = f"https://jsonplaceholder.typicode.com/users/{user_id}"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()

    except requests.RequestException as error:
        raise APIRequestError(
            f"Failed to retrieve user {user_id}: {error}"
        ) from error


try:
    user = get_user(1)
    print("User retrieved:", user["name"])
    print("Email:", user["email"])

except APIRequestError as error:
    print("API FAILURE:", error)
