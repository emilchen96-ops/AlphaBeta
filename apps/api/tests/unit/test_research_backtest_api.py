from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from starlette.requests import Request

from alphadesk_api.api.v1 import research_backtests as api_module
from alphadesk_api.application.backtest_batches import (
    BacktestBatchService,
    CreateBacktestBatchRequest,
)
from alphadesk_api.application.research_backtests import (
    QuickBacktestRequest,
    QuickBacktestService,
)

CORE_TEXT = "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线"  # noqa: RUF001


def test_openapi_exposes_product_quick_backtest_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/api/v1/research/quick-backtests"]
    assert "get" in paths["/api/v1/research/backtests"]
    assert "get" in paths["/api/v1/research/backtests/{run_id}/summary"]
    assert "post" in paths["/api/v1/research/backtest-batches"]
    assert "get" in paths["/api/v1/research/backtest-batches/{batch_id}"]
    assert "get" in paths["/api/v1/research/backtest-batches/{batch_id}/results"]


def test_quick_backtest_requires_exactly_one_strategy(client: TestClient) -> None:
    body = {
        "instrument_id": "11111111-1111-4111-8111-111111111111",
        "start_at": "2024-01-01T00:00:00+08:00",
        "end_at": "2026-01-01T00:00:00+08:00",
    }

    response = client.post("/api/v1/research/quick-backtests", json=body)
    assert response.status_code == 422

    body["spec"] = client.post("/api/v1/strategy-specs/parse", json={"text": CORE_TEXT}).json()[
        "spec"
    ]
    body["user_strategy_id"] = "22222222-2222-4222-8222-222222222222"
    response = client.post("/api/v1/research/quick-backtests", json=body)
    assert response.status_code == 422


def test_quick_backtest_accepts_confirmed_spec_and_calls_unified_service(
    client: TestClient, monkeypatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run(self: QuickBacktestService, request: QuickBacktestRequest) -> dict[str, Any]:
        captured["request"] = request
        return {
            "id": "33333333-3333-4333-8333-333333333333",
            "status": "COMPLETED",
            "simulation_notice": "回测仅为历史模拟, 不会发送给券商。",
        }

    monkeypatch.setattr(QuickBacktestService, "run", fake_run)

    def fake_dependency(request: Request) -> object:
        del request
        return object()

    monkeypatch.setattr(api_module, "uow_factory", fake_dependency)
    monkeypatch.setattr(api_module, "_registry", fake_dependency)
    monkeypatch.setattr(api_module, "_settings", fake_dependency)
    spec = client.post("/api/v1/strategy-specs/parse", json={"text": CORE_TEXT}).json()["spec"]

    response = client.post(
        "/api/v1/research/quick-backtests",
        json={
            "instrument_id": "11111111-1111-4111-8111-111111111111",
            "start_at": "2024-01-01T00:00:00+08:00",
            "end_at": "2026-01-01T00:00:00+08:00",
            "initial_cash": "100000",
            "spec": spec,
            "minimum_commission": None,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "COMPLETED"
    request = captured["request"]
    assert request.spec.name == "10日价格突破与放量策略"
    assert str(request.initial_cash) == "100000"
    assert request.user_strategy_id is None
    assert request.price_adjustment_mode.value == "RAW"
    assert request.minimum_commission == Decimal("5")
    assert request.execution_price_mode.value == "NEXT_OPEN"
    assert request.position_size_ratio == Decimal("1")
    assert request.maximum_entry_gap_ratio == Decimal("0.05")
    assert request.time_in_force.value == "DAY"


def test_batch_backtest_accepts_watchlist_scope_and_returns_durable_job(
    client: TestClient, monkeypatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create(
        self: BacktestBatchService, request: CreateBacktestBatchRequest
    ) -> dict[str, Any]:
        captured["request"] = request
        return {
            "id": "44444444-4444-4444-8444-444444444444",
            "scope": "WATCHLIST",
            "status": "CREATED",
            "total_count": 3,
        }

    monkeypatch.setattr(BacktestBatchService, "create", fake_create)

    def fake_dependency(request: Request) -> object:
        del request
        return object()

    monkeypatch.setattr(api_module, "uow_factory", fake_dependency)
    monkeypatch.setattr(api_module, "_registry", fake_dependency)
    monkeypatch.setattr(api_module, "_settings", fake_dependency)
    spec = client.post("/api/v1/strategy-specs/parse", json={"text": CORE_TEXT}).json()["spec"]
    response = client.post(
        "/api/v1/research/backtest-batches",
        json={
            "scope": "WATCHLIST",
            "watchlist_id": "55555555-5555-4555-8555-555555555555",
            "start_at": "2024-01-01T00:00:00+08:00",
            "end_at": "2026-01-01T00:00:00+08:00",
            "initial_cash": "100000",
            "spec": spec,
            "exclude_st": True,
            "idempotency_key": "batch-api-test",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CREATED"
    request = captured["request"]
    assert request.scope.value == "WATCHLIST"
    assert request.watchlist_id is not None
    assert request.exclude_st is True
    assert request.position_size_ratio == Decimal("1")


def test_batch_backtest_accepts_full_a_share_scope_and_filters(
    client: TestClient, monkeypatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create(
        self: BacktestBatchService, request: CreateBacktestBatchRequest
    ) -> dict[str, Any]:
        captured["request"] = request
        return {
            "id": "66666666-6666-4666-8666-666666666666",
            "scope": "ALL_A_SHARES",
            "status": "CREATED",
            "total_count": 4200,
        }

    monkeypatch.setattr(BacktestBatchService, "create", fake_create)

    def fake_dependency(request: Request) -> object:
        del request
        return object()

    monkeypatch.setattr(api_module, "uow_factory", fake_dependency)
    monkeypatch.setattr(api_module, "_registry", fake_dependency)
    monkeypatch.setattr(api_module, "_settings", fake_dependency)
    spec = client.post("/api/v1/strategy-specs/parse", json={"text": CORE_TEXT}).json()["spec"]
    response = client.post(
        "/api/v1/research/backtest-batches",
        json={
            "scope": "ALL_A_SHARES",
            "start_at": "2024-01-01T00:00:00+08:00",
            "end_at": "2026-01-01T00:00:00+08:00",
            "initial_cash": "100000",
            "spec": spec,
            "exclude_st": True,
            "exclude_bse": True,
            "exclude_star_market": True,
            "exclude_chinext": False,
            "idempotency_key": "full-a-batch-api-test",
        },
    )

    assert response.status_code == 202
    assert response.json()["total_count"] == 4200
    request = captured["request"]
    assert request.scope.value == "ALL_A_SHARES"
    assert request.watchlist_id is None
    assert request.exclude_st is True
    assert request.exclude_bse is True
    assert request.exclude_star_market is True
    assert request.exclude_chinext is False
