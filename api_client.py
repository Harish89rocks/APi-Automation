import requests


class APIClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def get(self, endpoint):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return requests.get(url, timeout=10)

    def post(self, endpoint, payload):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return requests.post(url, json=payload, timeout=10)
