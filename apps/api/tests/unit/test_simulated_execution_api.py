from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alphadesk_api.api.v1.market_common import to_app_error
from alphadesk_api.app_factory import create_app
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.cli.simulated_broker import build_parser
from alphadesk_api.core.config import Settings
from alphadesk_api.schemas.simulated_execution import SimulatedExecutionBody


class FakeProbe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _body(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "idempotency_key": "b01-api-1",
        "timestamp": datetime(2026, 7, 18, tzinfo=UTC),
        "trading_status": "TRADING",
        "last_price": "10.01",
        "bid_price": "10.00",
        "ask_price": "10.02",
        "available_volume": "100",
        "source": "UNIT_TEST",
        "is_stale": False,
    }
    value.update(changes)
    return value


def test_simulated_execution_body_requires_decimal_strings_and_aware_timestamp() -> None:
    parsed = SimulatedExecutionBody.model_validate(_body())
    assert parsed.last_price == "10.01"
    with pytest.raises(ValidationError):
        SimulatedExecutionBody.model_validate(_body(last_price=10.01))
    with pytest.raises(ValidationError):
        SimulatedExecutionBody.model_validate(_body(timestamp=datetime(2026, 7, 18)))


def test_b01_c_openapi_is_read_only_for_fills_and_has_no_real_broker_route() -> None:
    settings = Settings(environment="test", postgres_host="unused", redis_host="unused")
    app = create_app(settings, database=FakeProbe(), redis_service=FakeProbe())
    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/orders/{order_id}/simulated-executions"]
    assert set(paths["/api/v1/fills"]) == {"get"}
    assert set(paths["/api/v1/fills/{fill_id}"]) == {"get"}
    assert not any("miniqmt" in path.lower() or "real-broker" in path.lower() for path in paths)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("BROKER_EXECUTION_IDEMPOTENCY_CONFLICT", 409),
        ("BROKER_ORDER_NOT_EXECUTABLE", 409),
        ("BROKER_EXECUTION_ATTEMPT_NOT_FOUND", 404),
        ("BROKER_EXECUTION_INVALID_REQUEST", 422),
    ],
)
def test_b01_c_error_mapping(code: str, status: int) -> None:
    assert to_app_error(ApplicationError(code, "safe message")).status_code == status


@pytest.mark.parametrize(
    "command", ["execute", "list-attempts", "list-fills", "verify-integrity", "run-demo"]
)
def test_simulated_broker_cli_exposes_required_commands(command: str) -> None:
    parser = build_parser()
    args = [command]
    if command == "execute":
        args += [
            "--order-id",
            "11111111-1111-4111-8111-111111111111",
            "--idempotency-key",
            "cli-key",
            "--last-price",
            "10.01",
        ]
    elif command != "run-demo":
        args += ["--order-id", "11111111-1111-4111-8111-111111111111"]
    assert parser.parse_args(args).command == command
