from fastapi import Request
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app, wrap_with_cors
from alphadesk_api.core.config import Settings
from tests.conftest import FakeProbe


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


def test_unhandled_error_keeps_cors_headers_for_browser_clients(settings: Settings) -> None:
    inner = create_app(settings, database=FakeProbe(), redis_service=FakeProbe())

    async def boom(_request: Request) -> None:
        raise RuntimeError("internal detail must not be returned")

    inner.add_api_route("/test/cors-boom", boom)
    app = wrap_with_cors(inner, settings)
    origin = settings.cors_origins[0]
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/cors-boom", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == origin
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"


def test_cors_preflight_allows_put_for_versioned_screening_edits(
    settings: Settings,
) -> None:
    app = wrap_with_cors(
        create_app(settings, database=FakeProbe(), redis_service=FakeProbe()),
        settings,
    )
    origin = settings.cors_origins[0]

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/user-screenings/example",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "PUT" in response.headers["access-control-allow-methods"]
