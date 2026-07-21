from alphadesk_api.app_factory import create_app
from alphadesk_api.cli.replays import build_parser
from alphadesk_api.core.config import Settings


class FakeProbe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def test_rt01_openapi_exposes_control_and_read_only_fact_endpoints() -> None:
    app = create_app(Settings(environment="test"), database=FakeProbe(), redis_service=FakeProbe())
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/replays",
        "/api/v1/replays/{replay_id}",
        "/api/v1/replays/{replay_id}/start",
        "/api/v1/replays/{replay_id}/pause",
        "/api/v1/replays/{replay_id}/resume",
        "/api/v1/replays/{replay_id}/step",
        "/api/v1/replays/{replay_id}/stop",
        "/api/v1/replays/{replay_id}/speed",
        "/api/v1/replays/{replay_id}/events",
        "/api/v1/replays/{replay_id}/state",
        "/api/v1/replays/{replay_id}/equity",
        "/api/v1/replays/{replay_id}/signals",
        "/api/v1/replays/{replay_id}/risk-decisions",
        "/api/v1/replays/{replay_id}/orders",
        "/api/v1/replays/{replay_id}/fills",
        "/api/v1/replays/{replay_id}/integrity",
    }
    assert required <= set(paths)
    assert "/ws/replays/{replay_id}" in {
        path for route in app.routes if (path := getattr(route, "path", None)) is not None
    }
    assert all("miniqmt" not in path and "broker" not in path for path in required)


def test_rt01_cli_declares_all_control_and_integrity_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["list"]).command == "list"
    assert parser.parse_args(["run-demo"]).command == "run-demo"
    replay_id = "00000000-0000-0000-0000-000000000001"
    for command in ("show", "verify-integrity"):
        assert parser.parse_args([command, "--replay-id", replay_id]).command == command
    for command in ("start", "pause", "resume", "step", "stop"):
        parsed = parser.parse_args(
            [
                command,
                "--replay-id",
                replay_id,
                "--idempotency-key",
                f"{command}-1",
                "--expected-run-version",
                "1",
            ]
        )
        assert parsed.command == command
    speed = parser.parse_args(
        [
            "set-speed",
            "--replay-id",
            replay_id,
            "--idempotency-key",
            "speed-1",
            "--expected-run-version",
            "1",
            "--speed",
            "X10",
        ]
    )
    assert speed.speed == "X10"
