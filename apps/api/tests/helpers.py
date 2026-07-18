import os

import pytest
from sqlalchemy.engine import URL, make_url


def require_test_database_url() -> URL:
    if os.getenv("ALPHADESK_RUN_M02_INTEGRATION", "false").lower() != "true":
        pytest.skip("M02 PostgreSQL integration tests require explicit opt-in")
    raw_url = os.getenv("ALPHADESK_TEST_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("ALPHADESK_TEST_DATABASE_URL is required")
    url = make_url(raw_url)
    if url.database is None or "test" not in url.database.lower():
        raise RuntimeError("Refusing destructive test against a non-test database")
    return url


def require_m03_test_database_url() -> URL:
    if os.getenv("ALPHADESK_RUN_M03_INTEGRATION", "false").lower() != "true":
        pytest.skip("M03 PostgreSQL integration tests require explicit opt-in")
    return require_test_database_url()


def require_m04_test_database_url() -> URL:
    if os.getenv("ALPHADESK_RUN_M04_INTEGRATION", "false").lower() != "true":
        pytest.skip("M04 PostgreSQL integration tests require explicit opt-in")
    return require_test_database_url()


def require_b01_test_database_url() -> URL:
    if os.getenv("ALPHADESK_RUN_B01_INTEGRATION", "false").lower() != "true":
        pytest.skip("B01 PostgreSQL integration tests require explicit opt-in")
    return require_test_database_url()


def require_bt01_test_database_url() -> URL:
    if os.getenv("ALPHADESK_RUN_BT01_INTEGRATION", "false").lower() != "true":
        pytest.skip("BT01 PostgreSQL integration tests require explicit opt-in")
    return require_test_database_url()
