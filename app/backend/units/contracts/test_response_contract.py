from __future__ import annotations

from fastapi.testclient import TestClient

from app.backend.core.codes import CODE_SPECS, CommonCode
from app.backend.middleware.request_context import REQUEST_ID_HEADER

from app.backend.units.contracts.helpers import assert_api_response


def test_success_response_has_fixed_four_fields(client: TestClient) -> None:
    response = client.get("/contract/success")

    body = assert_api_response(response, http_status=200, message="测试成功")
    assert body["data"] == {"status": "ok"}


def test_created_response_keeps_http_201_and_fixed_body(client: TestClient) -> None:
    response = client.post("/contract/created")

    body = assert_api_response(response, http_status=201, message="创建成功")
    assert body["data"] == {"id": "paper-1"}


def test_no_content_response_keeps_request_id_header_without_json_body(
    client: TestClient,
) -> None:
    response = client.delete("/contract/no-content")

    assert response.status_code == 204
    assert response.headers.get(REQUEST_ID_HEADER)
    assert response.content == b""


def test_redirect_response_is_not_forced_into_json_envelope(
    client: TestClient,
) -> None:
    response = client.get("/contract/redirect", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get(REQUEST_ID_HEADER)
    assert "location" in response.headers
    assert response.content == b""


def test_validation_error_response_is_sanitized(client: TestClient) -> None:
    response = client.get("/contract/validation", params={"page": 0})

    body = assert_api_response(
        response,
        http_status=400,
        message=CODE_SPECS[CommonCode.BAD_REQUEST].message,
    )
    assert body["data"] is None
    assert "greater_than_equal" not in response.text
    assert "page" not in response.text
