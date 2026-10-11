from __future__ import annotations

from fastapi.testclient import TestClient

from app.backend.middleware.request_context import REQUEST_ID_HEADER

from app.backend.tests.contract.helpers import (
    assert_api_response,
    build_contract_app,
    make_settings,
)


def test_generated_request_id_is_shared_by_header_and_body(
    client: TestClient,
) -> None:
    response = client.get("/contract/success")

    body = assert_api_response(response, http_status=200)
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert len(body["request_id"]) == 32


def test_inbound_request_id_is_ignored_by_default() -> None:
    app = build_contract_app(settings=make_settings(trust_inbound_request_id=False))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/contract/success",
        headers={REQUEST_ID_HEADER: "client-request-id-001"},
    )

    body = assert_api_response(response, http_status=200)
    assert body["request_id"] != "client-request-id-001"


def test_valid_inbound_request_id_can_be_trusted_when_enabled() -> None:
    app = build_contract_app(settings=make_settings(trust_inbound_request_id=True))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/contract/success",
        headers={REQUEST_ID_HEADER: "client-request-id-001"},
    )

    body = assert_api_response(response, http_status=200)
    assert body["request_id"] == "client-request-id-001"
