from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.backend.units.contracts.helpers import build_contract_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_contract_app(), raise_server_exceptions=False)
