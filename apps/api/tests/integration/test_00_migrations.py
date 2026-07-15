import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from tests.helpers import require_test_database_url


def migration_environment() -> dict[str, str]:
    url = make_url(require_test_database_url())
    environment = os.environ.copy()
    environment.update(
        {
            "ALPHADESK_ENVIRONMENT": "test",
            "ALPHADESK_POSTGRES_HOST": str(url.host),
            "ALPHADESK_POSTGRES_PORT": str(url.port or 5432),
            "ALPHADESK_POSTGRES_DB": str(url.database),
            "ALPHADESK_POSTGRES_USER": str(url.username),
            "ALPHADESK_POSTGRES_PASSWORD": str(url.password),
        }
    )
    return environment


def run_alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *arguments],
        cwd=Path(__file__).resolve().parents[2],
        env=migration_environment(),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
@pytest.mark.m04
def test_upgrade_downgrade_reupgrade_and_check() -> None:
    run_alembic("upgrade", "head")
    current = run_alembic("current")
    assert "0004_m04" in current.stdout

    run_alembic("downgrade", "0002_m02")
    downgraded = run_alembic("current")
    assert "0002_m02" in downgraded.stdout

    run_alembic("upgrade", "head")
    reupgraded = run_alembic("current")
    assert "0004_m04" in reupgraded.stdout
    check = run_alembic("check")
    assert "No new upgrade operations detected" in check.stdout
