from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from starlette.requests import Request

from alphadesk_api.api.v1 import research_backtests as api_module
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
            "price_adjustment_mode": "QFQ",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "COMPLETED"
    request = captured["request"]
    assert request.spec.name == "10日价格突破与放量策略"
    assert str(request.initial_cash) == "100000"
    assert request.user_strategy_id is None
    assert request.price_adjustment_mode.value == "QFQ"
