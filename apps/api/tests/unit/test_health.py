from conftest import FakeProbe, build_client
from fastapi.testclient import TestClient

from alphadesk_api.core.config import Settings


def test_live_returns_process_status(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    assert response.json()["service"] == "alphadesk-api"


def test_live_does_not_probe_dependencies(
    client: TestClient, probes: tuple[FakeProbe, FakeProbe]
) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert probes[0].ping_count == 0
    assert probes[1].ping_count == 0


def test_ready_returns_200_when_dependencies_are_healthy(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_returns_503_when_database_is_unavailable(settings: Settings) -> None:
    with build_client(settings, FakeProbe(False), FakeProbe(True)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["postgresql"] == "offline"
    assert response.json()["redis"] == "online"


def test_ready_returns_503_when_redis_is_unavailable(settings: Settings) -> None:
    with build_client(settings, FakeProbe(True), FakeProbe(False)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["postgresql"] == "online"
    assert response.json()["redis"] == "offline"
