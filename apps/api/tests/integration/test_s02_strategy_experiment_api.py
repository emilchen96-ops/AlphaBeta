from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from tests.helpers import require_test_database_url


class Probe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def payload(key: str) -> dict[str, object]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "strategy_key": "sma_crossover",
        "parameter_grid": {"short_window": [2, 3], "long_window": [4]},
        "instrument_ids": [str(uuid4())],
        "timeframe": "MINUTE_1",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=8)).isoformat(),
        "idempotency_key": key,
    }


@pytest.mark.integration
@pytest.mark.s01
def test_strategy_experiment_api_end_to_end() -> None:
    require_test_database_url()
    settings = Settings(
        environment="test",
        postgres_host="postgres_test",
        postgres_db="alphadesk_test",
        postgres_user="alphadesk_test",
        postgres_password="local-test-placeholder",
        redis_host="unused",
    )
    app = create_app(settings, redis_service=Probe())
    key = f"api-experiment-{uuid4()}"
    body = payload(key)
    with TestClient(app) as client:
        created = client.post("/api/v1/strategy-experiments", json=body)
        assert created.status_code == 201
        experiment = created.json()
        experiment_id = experiment["experiment_id"]
        assert experiment["status"] == "COMPLETED"
        assert experiment["combination_count"] == 2
        assert experiment["capabilities"]["creates_orders"] is False

        replayed = client.post("/api/v1/strategy-experiments", json=body)
        assert replayed.status_code == 201 and replayed.json()["replayed"] is True
        assert replayed.json()["experiment_id"] == experiment_id

        listing = client.get("/api/v1/strategy-experiments?page=1&page_size=10")
        filtered_in = client.get(
            "/api/v1/strategy-experiments",
            params={
                "created_from": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
                "created_to": datetime(2027, 1, 1, tzinfo=UTC).isoformat(),
            },
        )
        filtered_out = client.get(
            "/api/v1/strategy-experiments",
            params={"created_from": datetime(2099, 1, 1, tzinfo=UTC).isoformat()},
        )
        detail = client.get(f"/api/v1/strategy-experiments/{experiment_id}")
        runs = client.get(f"/api/v1/strategy-experiments/{experiment_id}/runs")
        comparison = client.get(f"/api/v1/strategy-experiments/{experiment_id}/comparison")
        overlap = client.get(f"/api/v1/strategy-experiments/{experiment_id}/signal-overlap")
        assert listing.status_code == detail.status_code == 200
        assert any(row["experiment_id"] == experiment_id for row in filtered_in.json()["items"])
        assert filtered_out.json()["total"] == 0
        assert runs.status_code == comparison.status_code == overlap.status_code == 200
        assert len(runs.json()) == len(comparison.json()) == 2
        assert overlap.json()[0]["similarity"] == "1"
        assert "profit" not in comparison.text.lower()

        changed = payload(key)
        conflict = client.post("/api/v1/strategy-experiments", json=changed)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "STRATEGY_EXPERIMENT_IDEMPOTENCY_CONFLICT"
        assert conflict.json()["error"]["correlation_id"]


@pytest.mark.integration
@pytest.mark.s01
def test_strategy_experiment_api_validation_and_not_found() -> None:
    require_test_database_url()
    settings = Settings(
        environment="test",
        postgres_host="postgres_test",
        postgres_db="alphadesk_test",
        postgres_user="alphadesk_test",
        postgres_password="local-test-placeholder",
        redis_host="unused",
        strategy_experiment_max_combinations=2,
    )
    with TestClient(create_app(settings, redis_service=Probe())) as client:
        body = payload(f"too-large-{uuid4()}")
        body["parameter_grid"] = {"short_window": [2, 3, 4], "long_window": [5]}
        response = client.post("/api/v1/strategy-experiments", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["details"] == {
            "actual_count": 3,
            "max_combinations": 2,
        }
        missing = client.get(f"/api/v1/strategy-experiments/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["correlation_id"]
