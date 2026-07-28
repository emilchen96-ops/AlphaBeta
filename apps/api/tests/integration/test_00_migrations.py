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
@pytest.mark.m05
@pytest.mark.s01
@pytest.mark.r01
@pytest.mark.b01
@pytest.mark.sc01
@pytest.mark.n01
@pytest.mark.a01
@pytest.mark.bt01
@pytest.mark.rt01
def test_upgrade_downgrade_reupgrade_and_check() -> None:
    run_alembic("upgrade", "head")
    current = run_alembic("current")
    assert "0026_sc02d" in current.stdout

    run_alembic("downgrade", "0017_d02")
    d03_downgraded = run_alembic("current")
    assert "0017_d02" in d03_downgraded.stdout

    run_alembic("upgrade", "head")
    d03_reupgraded = run_alembic("current")
    assert "0026_sc02d" in d03_reupgraded.stdout

    run_alembic("downgrade", "0015_bt01")
    rt01_downgraded = run_alembic("current")
    assert "0015_bt01" in rt01_downgraded.stdout

    run_alembic("upgrade", "head")
    rt01_reupgraded = run_alembic("current")
    assert "0026_sc02d" in rt01_reupgraded.stdout

    run_alembic("downgrade", "0014_d01")
    bt01_downgraded = run_alembic("current")
    assert "0014_d01" in bt01_downgraded.stdout

    run_alembic("upgrade", "head")
    bt01_reupgraded = run_alembic("current")
    assert "0026_sc02d" in bt01_reupgraded.stdout

    run_alembic("downgrade", "0013_a01")
    d01_downgraded = run_alembic("current")
    assert "0013_a01" in d01_downgraded.stdout

    run_alembic("upgrade", "head")
    d01_reupgraded = run_alembic("current")
    assert "0026_sc02d" in d01_reupgraded.stdout

    run_alembic("downgrade", "0012_n01")
    a01_downgraded = run_alembic("current")
    assert "0012_n01" in a01_downgraded.stdout

    run_alembic("upgrade", "head")
    a01_reupgraded = run_alembic("current")
    assert "0026_sc02d" in a01_reupgraded.stdout

    run_alembic("downgrade", "0011_sc01")
    n01_downgraded = run_alembic("current")
    assert "0011_sc01" in n01_downgraded.stdout

    run_alembic("upgrade", "head")
    n01_reupgraded = run_alembic("current")
    assert "0026_sc02d" in n01_reupgraded.stdout

    run_alembic("downgrade", "0010_b01")
    downgraded = run_alembic("current")
    assert "0010_b01" in downgraded.stdout

    run_alembic("upgrade", "head")
    sc01_reupgraded = run_alembic("current")
    assert "0026_sc02d" in sc01_reupgraded.stdout

    run_alembic("downgrade", "0009_r01")
    b01_downgraded = run_alembic("current")
    assert "0009_r01" in b01_downgraded.stdout

    run_alembic("upgrade", "head")
    reupgraded = run_alembic("current")
    assert "0026_sc02d" in reupgraded.stdout
    check = run_alembic("check")
    assert "No new upgrade operations detected" in check.stdout
