import requests


class APIClient:
    def __init__(self, base_url: str, session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def get_user(self, user_id: int) -> dict:
        url = f"{self.base_url}/users/{user_id}"

        response = self.session.get(url, timeout=5)
        response.raise_for_status()

        return response.json()


if __name__ == "__main__":
    client = APIClient("https://jsonplaceholder.typicode.com")
    user = client.get_user(1)

    print("Name:", user["name"])
    print("Email:", user["email"])
