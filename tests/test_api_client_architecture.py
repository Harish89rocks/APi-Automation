import pytest
import requests
from unittest.mock import Mock, patch

from api_client_architecture_practice import (
    get_json,
    APIHTTPError,
    APITransportError,
    APIClientError,
)

pytestmark = [pytest.mark.unit]


@patch("api_client_architecture_practice.requests.get")
def test_successful_response(mock_get):
    response = Mock()
    response.ok = True
    response.json.return_value = {"id": 1, "name": "Harish"}
    mock_get.return_value = response

    result = get_json("https://example.com/users/1")

    assert result["name"] == "Harish"
    mock_get.assert_called_once()


@patch("api_client_architecture_practice.requests.get")
def test_http_500_raises_http_error(mock_get):
    response = Mock()
    response.ok = False
    response.status_code = 500
    mock_get.return_value = response

    with pytest.raises(APIHTTPError, match="500"):
        get_json("https://example.com/users/1")


@patch("api_client_architecture_practice.requests.get")
def test_timeout_raises_transport_error(mock_get):
    mock_get.side_effect = requests.Timeout("Request timed out")

    with pytest.raises(APITransportError, match="Request failed"):
        get_json("https://example.com/users/1")


@patch("api_client_architecture_practice.requests.get")
def test_invalid_json_type_raises_client_error(mock_get):
    response = Mock()
    response.ok = True
    response.json.return_value = ["unexpected", "list"]
    mock_get.return_value = response

    with pytest.raises(APIClientError, match="Expected a JSON object"):
        get_json("https://example.com/users/1")
