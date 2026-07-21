import argparse
import json

import pytest

from alphadesk_api.application.common import ApplicationError
from alphadesk_api.cli.ai import execute, fail
from alphadesk_api.core.config import Settings

pytestmark = [pytest.mark.unit, pytest.mark.a01]


@pytest.mark.asyncio
async def test_failed_provider_connectivity_check_is_a_cli_failure() -> None:
    settings = Settings(
        environment="test",
        postgres_host="unused",
        redis_host="unused",
        ai_research_provider="disabled",
    )
    with pytest.raises(ApplicationError) as captured:
        await execute(argparse.Namespace(command="test-provider"), settings)
    assert captured.value.code == "AI_PROVIDER_DISABLED"


def test_cli_failure_has_stable_code_and_nonzero_exit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        fail("connectivity failed", code="AI_PROVIDER_TIMEOUT")
    assert captured.value.code == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "error": {"code": "AI_PROVIDER_TIMEOUT", "message": "connectivity failed"},
    }
