import pytest
from pydantic import SecretStr, ValidationError

from alphadesk_api.core.config import Settings, get_settings


def test_settings_read_environment_variables(monkeypatch: object) -> None:
    monkeypatch.setenv("ALPHADESK_APP_NAME", "configured-api")  # type: ignore[attr-defined]
    monkeypatch.setenv("ALPHADESK_POSTGRES_PORT", "5544")  # type: ignore[attr-defined]
    get_settings.cache_clear()
    settings = Settings()
    assert settings.app_name == "configured-api"
    assert settings.postgres_port == 5544
    get_settings.cache_clear()


def test_production_rejects_missing_explicit_database_password() -> None:
    with pytest.raises(ValidationError, match="explicitly supplied PostgreSQL password"):
        Settings(
            environment="production",
            postgres_password=SecretStr("change-me-local-only"),
        )
