import pytest
from fastapi.testclient import TestClient

from app.backend.core.exceptions import message_for_http_status
from app.backend.tests.contract.helpers import assert_api_response


@pytest.mark.parametrize(
    ("method", "path", "http_status"),
    [
        ("GET", "/missing-route", 404),
        ("POST", "/contract/success", 405),
        ("GET", "/contract/http-error/401", 401),
        ("GET", "/contract/http-error/403", 403),
        ("GET", "/contract/http-error/429", 429),
        ("GET", "/contract/http-error/502", 502),
        ("GET", "/contract/http-error/504", 504),
    ],
)
def test_http_exception_response_is_uniform(
    client: TestClient,
    method: str,
    path: str,
    http_status: int,
) -> None:
    response = client.request(method, path)
    body = assert_api_response(
        response,
        http_status=http_status,
        message=message_for_http_status(http_status),
    )
    assert body["data"] is None


def test_http_401_keeps_authenticate_header(client: TestClient) -> None:
    response = client.get("/contract/http-error/401")
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("path", "http_status", "expected_message"),
    [
        ("/contract/duplicate-paper", 409, "论文已存在"),
        ("/contract/unsupported-paper", 415, message_for_http_status(415)),
    ],
)
def test_app_error_uses_http_status_and_message(
    client: TestClient,
    path: str,
    http_status: int,
    expected_message: str,
) -> None:
    response = client.get(path)
    body = assert_api_response(response, http_status=http_status, message=expected_message)
    assert body["data"] is None


def test_temporary_dependency_failure_returns_503(client: TestClient) -> None:
    response = client.get("/contract/dependency-unavailable")
    assert_api_response(response, http_status=503, message=message_for_http_status(503))
    assert "dependency address" not in response.text


def test_non_temporary_dependency_failure_returns_500(client: TestClient) -> None:
    response = client.get("/contract/dependency-failure")
    assert_api_response(response, http_status=500, message=message_for_http_status(500))
    assert "sensitive filesystem path" not in response.text


def test_unknown_exception_response_hides_internal_error(client: TestClient) -> None:
    response = client.get("/contract/unknown-error")
    assert_api_response(response, http_status=500, message=message_for_http_status(500))
    assert "sensitive internal database url" not in response.text