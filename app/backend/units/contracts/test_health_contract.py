from __future__ import annotations

from fastapi.testclient import TestClient

from app.backend.core.codes import CODE_SPECS, CommonCode

from app.backend.units.contracts.helpers import (
    assert_api_response,
    build_contract_app,
    make_settings,
)


def test_health_live_response_is_uniform(client: TestClient) -> None:
    response = client.get("/health/live")

    body = assert_api_response(response, http_status=200)
    assert body["data"] == {
        "status": "ok",
        "name": "Contract Test App",
        "version": "0.0.0",
    }


def test_health_ready_503_response_still_has_uniform_body(
    client: TestClient,
) -> None:
    response = client.get("/health/ready")

    body = assert_api_response(
        response,
        http_status=503,
        code=CommonCode.SERVICE_UNAVAILABLE,
    )
    assert body["data"]["status"] == "not_ready"
    assert body["data"]["components"]["text_embedding"] == {
        "status": "error",
        "required": True,
    }
    assert isinstance(body["message"], str)
    assert body["message"]


def test_health_details_exposes_diagnostic_error_fields(
    client: TestClient,
) -> None:
    response = client.get("/health/details")

    body = assert_api_response(
        response,
        http_status=503,
        code=CommonCode.SERVICE_UNAVAILABLE,
    )
    text_embedding = body["data"]["components"]["text_embedding"]
    assert text_embedding["status"] == "error"
    assert text_embedding["probe"] == "real_embedding_request"
    assert text_embedding["latency_ms"] == 12.34
    assert text_embedding["error_type"] == "ConnectError"
    assert text_embedding["error_message"] == "连接失败"


def test_disabled_health_details_returns_uniform_404() -> None:
    app = build_contract_app(settings=make_settings(health_details_enabled=False))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health/details")

    body = assert_api_response(
        response,
        http_status=404,
        message=CODE_SPECS[CommonCode.NOT_FOUND].message,
    )
    assert body["data"] is None
