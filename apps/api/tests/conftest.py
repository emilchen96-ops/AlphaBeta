from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import ManagedProbe, create_app
from alphadesk_api.core.config import Settings


class FakeProbe:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.ping_count = 0
        self.closed = False

    async def ping(self) -> bool:
        self.ping_count += 1
        return self.healthy

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        postgres_host="unused",
        redis_host="unused",
        dependency_timeout_seconds=0.1,
    )


@pytest.fixture
def probes() -> tuple[FakeProbe, FakeProbe]:
    return FakeProbe(), FakeProbe()


@pytest.fixture
def client(settings: Settings, probes: tuple[FakeProbe, FakeProbe]) -> Iterator[TestClient]:
    database, redis = probes
    app = create_app(
        settings,
        database=database,
        redis_service=redis,
    )
    with TestClient(app) as test_client:
        yield test_client


def build_client(
    settings: Settings,
    database: ManagedProbe,
    redis: ManagedProbe,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(settings, database=database, redis_service=redis)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)
