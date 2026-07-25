from fastapi.testclient import TestClient


def test_system_status_reports_probes_without_sensitive_configuration(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "online"
    assert body["postgresql"] == "online"
    assert body["redis"] == "online"
    assert body["product_mode"] == "RESEARCH_ONLY"
    serialized = response.text.lower()
    for forbidden in ("password", "database_url", "redis_url", "change-me-local-only"):
        assert forbidden not in serialized


def test_websocket_supports_ping_pong(client: TestClient) -> None:
    with client.websocket_connect("/ws/system") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["type"] == "pong"
        assert pong["timestamp"].endswith("Z") or "+00:00" in pong["timestamp"]
