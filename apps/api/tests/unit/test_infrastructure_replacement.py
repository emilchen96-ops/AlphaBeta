from fastapi.testclient import TestClient

from tests.conftest import FakeProbe


def test_database_and_redis_clients_are_replaceable(
    client: TestClient, probes: tuple[FakeProbe, FakeProbe]
) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert probes[0].ping_count == 1
    assert probes[1].ping_count == 1
