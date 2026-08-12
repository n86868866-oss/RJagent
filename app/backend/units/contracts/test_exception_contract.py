from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.backend.core.codes import CODE_SPECS, BusinessCode, CommonCode

from app.backend.units.contracts.helpers import assert_api_response


@pytest.mark.parametrize(
    ("method", "path", "http_status", "expected_message"),
    [
        ("GET", "/missing-route", 404, CODE_SPECS[CommonCode.NOT_FOUND].message),
        (
            "POST",
            "/contract/success",
            405,
            CODE_SPECS[CommonCode.METHOD_NOT_ALLOWED].message,
        ),
        (
            "GET",
            "/contract/http-error/401",
            401,
            CODE_SPECS[CommonCode.UNAUTHORIZED].message,
        ),
        (
            "GET",
            "/contract/http-error/403",
            403,
            CODE_SPECS[CommonCode.FORBIDDEN].message,
        ),
        (
            "GET",
            "/contract/http-error/429",
            429,
            CODE_SPECS[CommonCode.TOO_MANY_REQUESTS].message,
        ),
        (
            "GET",
            "/contract/http-error/502",
            502,
            CODE_SPECS[CommonCode.BAD_GATEWAY].message,
        ),
        (
            "GET",
            "/contract/http-error/504",
            504,
            CODE_SPECS[CommonCode.GATEWAY_TIMEOUT].message,
        ),
    ],
)
def test_http_exception_response_is_uniform(
    client: TestClient,
    method: str,
    path: str,
    http_status: int,
    expected_message: str,
) -> None:
    response = client.request(method, path)

    body = assert_api_response(
        response,
        http_status=http_status,
        message=expected_message,
    )
    assert body["data"] is None


def test_http_401_keeps_authenticate_header(client: TestClient) -> None:
    response = client.get("/contract/http-error/401")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("path", "http_status", "business_code"),
    [
        ("/contract/duplicate-paper", 409, BusinessCode.PAPER_ALREADY_EXISTS),
        (
            "/contract/unsupported-paper",
            415,
            BusinessCode.PAPER_FORMAT_UNSUPPORTED,
        ),
        ("/contract/permission-denied", 403, CommonCode.FORBIDDEN),
    ],
)
def test_app_error_response_uses_business_code_and_message(
    client: TestClient,
    path: str,
    http_status: int,
    business_code: int,
) -> None:
    response = client.get(path)

    body = assert_api_response(
        response,
        http_status=http_status,
        code=int(business_code),
        message=CODE_SPECS[business_code].message,
    )
    assert body["data"] is None


def test_unknown_exception_response_hides_internal_error(client: TestClient) -> None:
    response = client.get("/contract/unknown-error")

    body = assert_api_response(
        response,
        http_status=500,
        message=CODE_SPECS[CommonCode.INTERNAL_SERVER_ERROR].message,
    )
    assert body["data"] is None
    assert "sensitive internal database url" not in response.text
