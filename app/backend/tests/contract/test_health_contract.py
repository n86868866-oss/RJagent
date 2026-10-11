from fastapi.testclient import TestClient

from app.backend.core.exceptions import message_for_http_status
from app.backend.tests.contract.helpers import assert_api_response, build_contract_app, make_settings


def test_health_live_response_is_uniform(client: TestClient) -> None:
    response = client.get("/health/live")
    body = assert_api_response(response, http_status=200)
    assert body["data"] == {
        "status": "ok",
        "name": "Contract Test App",
        "version": "0.0.0",
    }


def test_health_ready_checks_required_components_only(client: TestClient) -> None:
    response = client.get("/health/ready")
    body = assert_api_response(response, http_status=503, code=503, message="服务未就绪")
    assert body["data"]["status"] == "not_ready"
    assert body["data"]["components"]["text_embedding"] == {
        "status": "error",
        "required": True,
    }
    assert "llm" not in body["data"]["components"]


def test_health_details_exposes_optional_diagnostics(client: TestClient) -> None:
    response = client.get("/health/details")
    body = assert_api_response(response, http_status=503, code=503, message="服务未就绪")
    embedding = body["data"]["components"]["text_embedding"]
    assert embedding["probe"] == "real_embedding_request"
    assert embedding["error_type"] == "ConnectError"
    assert embedding["error_message"] == "连接失败"
    assert body["data"]["components"]["llm"]["required"] is False


def test_disabled_health_details_returns_uniform_404() -> None:
    app = build_contract_app(settings=make_settings(health_details_enabled=False))
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health/details")
    body = assert_api_response(response, http_status=404, message=message_for_http_status(404))
    assert body["data"] is None