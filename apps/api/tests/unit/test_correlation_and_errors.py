from conftest import FakeProbe
from fastapi import Request
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings


def test_correlation_id_is_generated(client: TestClient) -> None:
    response = client.get("/health/live")
    generated = response.headers["X-Correlation-ID"]
    assert len(generated) == 36
    assert generated == generated.strip()


def test_valid_correlation_id_is_forwarded(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "desktop-request_123"})
    assert response.headers["X-Correlation-ID"] == "desktop-request_123"


def test_invalid_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "x" * 129})
    assert response.headers["X-Correlation-ID"] != "x" * 129
    assert len(response.headers["X-Correlation-ID"]) == 36


def test_unhandled_error_has_safe_shape_and_correlation_id(settings: Settings) -> None:
    app = create_app(settings, database=FakeProbe(), redis_service=FakeProbe())

    async def boom(_request: Request) -> None:
        raise RuntimeError("internal detail must not be returned")

    app.add_api_route("/test/boom", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/boom", headers={"X-Correlation-ID": "error-test"})
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "INTERNAL_SERVER_ERROR"
    assert body["correlation_id"] == "error-test"
    assert "internal detail" not in response.text
