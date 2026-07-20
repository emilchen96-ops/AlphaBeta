from alphadesk_api.app_factory import create_app
from alphadesk_api.cli.backtests import build_parser
from alphadesk_api.core.config import Settings


class FakeProbe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def test_bt01_openapi_exposes_only_local_backtest_fact_endpoints() -> None:
    app = create_app(Settings(environment="test"), database=FakeProbe(), redis_service=FakeProbe())
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/backtests",
        "/api/v1/backtests/{backtest_id}",
        "/api/v1/backtests/{backtest_id}/metrics",
        "/api/v1/backtests/{backtest_id}/equity-curve",
        "/api/v1/backtests/{backtest_id}/trades",
        "/api/v1/backtests/{backtest_id}/signals",
        "/api/v1/backtests/{backtest_id}/risk-decisions",
        "/api/v1/backtests/{backtest_id}/orders",
        "/api/v1/backtests/{backtest_id}/fills",
        "/api/v1/backtests/{backtest_id}/timeline",
        "/api/v1/backtests/{backtest_id}/integrity",
    }
    assert required <= set(paths)
    assert "post" in paths["/api/v1/backtests"]
    assert all("live" not in path and "miniqmt" not in path for path in required)


def test_bt01_cli_declares_required_commands() -> None:
    parser = build_parser()
    for command in ("list", "run-demo"):
        assert parser.parse_args([command]).command == command
    assert (
        parser.parse_args(
            [
                "run",
                "--strategy-key",
                "sma_crossover",
                "--instrument",
                "00000000-0000-0000-0000-000000000001",
                "--start",
                "2025-01-01",
                "--end",
                "2025-12-31",
                "--initial-cash",
                "100000",
                "--idempotency-key",
                "bt01-test",
            ]
        ).command
        == "run"
    )
    for command in ("show", "metrics", "verify-integrity"):
        parsed = parser.parse_args(
            [command, "--backtest-id", "00000000-0000-0000-0000-000000000001"]
        )
        assert parsed.command == command
