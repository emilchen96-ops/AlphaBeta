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


def test_local_cors_accepts_both_loopback_hostnames() -> None:
    assert Settings().cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_product_mode_defaults_to_research_and_accepts_full_simulation() -> None:
    assert Settings().product_mode == "RESEARCH_ONLY"
    assert Settings(product_mode="FULL_SIMULATION").product_mode == "FULL_SIMULATION"


def test_ai_provider_defaults_fake_and_incomplete_real_configuration() -> None:
    assert Settings().ai_research_provider == "disabled"
    assert Settings(ai_research_provider="fake").ai_research_provider == "fake"
    incomplete = Settings(
        ai_research_provider="openai_compatible",
        ai_base_url="https://ai.example.test/v1",
        ai_model="model",
    )
    assert incomplete.ai_api_key is None


def test_ai_selectable_models_are_normalized_and_include_configured_defaults() -> None:
    settings = Settings(
        ai_model="qwen3.7-plus",
        ai_quick_model="qwen3.7-flash",
        ai_deep_model="qwen3.7-max",
        ai_selectable_models="qwen-max, qwen3.6-plus,qwen-max",
    )
    assert settings.selectable_ai_models == (
        "qwen3.7-plus",
        "qwen3.7-flash",
        "qwen3.7-max",
        "qwen-max",
        "qwen3.6-plus",
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "not-a-url",
        "file:///tmp/provider",
        "https://user:password@ai.example.test/v1",
        "https://ai.example.test/v1?api_key=secret",
    ],
)
def test_ai_provider_rejects_unsafe_base_url(base_url: str) -> None:
    with pytest.raises(ValidationError, match="ai_base_url"):
        Settings(ai_base_url=base_url)
