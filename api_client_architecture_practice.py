import requests


class APIClientError(Exception):
    """Base exception for API client failures."""


class APIHTTPError(APIClientError):
    """Raised when an HTTP response indicates failure."""


class APITransportError(APIClientError):
    """Raised when a request cannot complete."""


def get_json(url: str) -> dict:
    try:
        response = requests.get(url, timeout=5)
    except requests.RequestException as error:
        raise APITransportError(
            f"Request failed: {error}"
        ) from error

    if not response.ok:
        raise APIHTTPError(
            f"HTTP {response.status_code} returned by {url}"
        )

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise APIClientError("Response was not valid JSON") from error

    if not isinstance(data, dict):
        raise APIClientError("Expected a JSON object")

    return data


if __name__ == "__main__":
    try:
        user = get_json(
            "https://jsonplaceholder.typicode.com/users/1"
        )
        print("User:", user["name"])
        print("Email:", user["email"])

    except APIClientError as error:
        print("API CLIENT FAILURE:", error)
