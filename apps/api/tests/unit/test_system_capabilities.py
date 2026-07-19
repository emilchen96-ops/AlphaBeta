from alphadesk_api.application.system_capabilities import (
    CapabilityDataSnapshot,
    assess_system_capabilities,
)
from alphadesk_api.core.config import Settings

EXPECTED_MODULES = {
    "market_data",
    "scanner",
    "strategy_research",
    "strategy_experiments",
    "information_center",
    "ai_research",
    "orders",
    "risk",
    "simulated_broker",
    "backtest",
    "realtime_market_data",
    "miniqmt",
}


def test_capability_endpoint_is_read_only_complete_and_secret_free(client) -> None:
    response = client.get("/api/v1/system/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["database_reachable"] is False
    assert {item["module_key"] for item in body["items"]} == EXPECTED_MODULES
    assert all(
        item["available"] is False
        for item in body["items"]
        if item["module_key"] != "information_center"
    )
    assert body["counts"]["instrument_count"] is None
    serialized = response.text.lower()
    for forbidden in ("password", "database_url", "redis_url", "secret", "change-me-local-only"):
        assert forbidden not in serialized


def test_capability_assessment_separates_data_config_and_implementation() -> None:
    settings = Settings(
        environment="test",
        postgres_host="unused",
        redis_host="unused",
        ai_research_provider="fake",
    )
    data = CapabilityDataSnapshot(
        database_reachable=True,
        instrument_count=3,
        market_bar_count=900,
        daily_market_bar_count=900,
        market_bar_instrument_count=3,
        simulated_account_count=1,
        information_item_count=2,
        executable_order_count=1,
    )
    items = {
        item.module_key: item
        for item in assess_system_capabilities(
            settings,
            data,
            ai_provider_configured=True,
            ai_provider_key="fake",
        )
    }

    assert items["scanner"].available is True
    assert items["strategy_experiments"].data_status == "READY"
    assert items["ai_research"].configuration_status == "READY"
    assert items["simulated_broker"].available is True
    assert items["backtest"].implementation_status == "PARTIAL"
    assert items["backtest"].available is False
    assert items["miniqmt"].implementation_status == "NOT_IMPLEMENTED"


def test_disabled_ai_and_missing_market_data_are_not_reported_available() -> None:
    settings = Settings(environment="test", postgres_host="unused", redis_host="unused")
    items = {
        item.module_key: item
        for item in assess_system_capabilities(
            settings,
            CapabilityDataSnapshot(database_reachable=True),
            ai_provider_configured=False,
            ai_provider_key="disabled",
        )
    }

    assert items["market_data"].data_status == "MISSING"
    assert items["scanner"].available is False
    assert items["ai_research"].configuration_status == "DISABLED"
    assert items["ai_research"].available is False
