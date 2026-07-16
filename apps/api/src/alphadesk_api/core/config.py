"""Type-safe application configuration."""

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional local .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ALPHADESK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "alphadesk-api"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    postgres_host: str = "postgres"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "alphadesk"
    postgres_user: str = "alphadesk"
    postgres_password: SecretStr = SecretStr("change-me-local-only")
    postgres_pool_size: int = Field(default=5, ge=1, le=50)
    postgres_max_overflow: int = Field(default=5, ge=0, le=50)
    test_database_url: SecretStr | None = None

    redis_host: str = "redis"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: SecretStr | None = None

    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    websocket_heartbeat_seconds: int = Field(default=20, ge=5, le=300)
    correlation_id_header: str = "X-Correlation-ID"
    max_websocket_message_bytes: int = Field(default=1024, ge=64, le=65536)
    instrument_page_size_max: int = Field(default=100, ge=10, le=500)
    watchlist_item_limit: int = Field(default=200, ge=1, le=2000)
    market_bar_query_limit: int = Field(default=2000, ge=100, le=10000)
    market_sync_batch_size: int = Field(default=500, ge=10, le=5000)
    market_future_tolerance_seconds: int = Field(default=300, ge=0, le=3600)
    market_minute_stale_seconds: int = Field(default=300, ge=30, le=86400)
    market_csv_max_bytes: int = Field(default=10_000_000, ge=1024, le=100_000_000)
    market_csv_max_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    external_market_data_enabled: bool = False
    free_market_enabled: bool = False
    realtime_market_provider: Literal["disabled"] = "disabled"
    historical_market_provider: Literal["baostock"] = "baostock"
    free_market_data_enabled: bool = False
    free_market_poll_seconds: int = Field(default=30, ge=30, le=3600)
    free_market_idle_poll_seconds: int = Field(default=120, ge=60, le=3600)
    free_market_closed_poll_seconds: int = Field(default=600, ge=600, le=3600)
    free_market_minute_sync_seconds: int = Field(default=300, ge=300, le=3600)
    free_market_minute_max_symbols: int = Field(default=20, ge=1, le=20)
    free_market_minute_lookback_minutes: int = Field(default=120, ge=5, le=480)
    free_market_provider_min_interval_seconds: float = Field(default=5.0, ge=5, le=300)
    free_market_provider_max_concurrency: int = Field(default=1, ge=1, le=1)
    free_market_provider_max_retries: int = Field(default=2, ge=0, le=5)
    free_market_circuit_failure_threshold: int = Field(default=5, ge=1, le=20)
    free_market_circuit_open_seconds: int = Field(default=600, ge=30, le=3600)
    free_market_quote_ttl_seconds: int = Field(default=120, ge=30, le=3600)
    free_market_stale_seconds: int = Field(default=60, ge=10, le=3600)
    free_market_worker_lock_ttl_seconds: int = Field(default=45, ge=15, le=300)
    free_market_websocket_queue_size: int = Field(default=100, ge=10, le=1000)
    free_market_max_subscriptions_per_client: int = Field(default=200, ge=1, le=2000)
    strategy_experiment_max_combinations: int = Field(default=50, ge=1, le=50)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("api_prefix must start with '/' and must not end with '/'")
        return value

    @field_validator("correlation_id_header")
    @classmethod
    def validate_header_name(cls, value: str) -> str:
        if not value or any(char.isspace() for char in value):
            raise ValueError("correlation_id_header must be a valid non-empty header name")
        return value

    @model_validator(mode="after")
    def validate_required_connections(self) -> Self:
        required_text = {
            "postgres_host": self.postgres_host,
            "postgres_db": self.postgres_db,
            "postgres_user": self.postgres_user,
            "redis_host": self.redis_host,
        }
        missing = [name for name, value in required_text.items() if not value.strip()]
        if missing:
            raise ValueError(f"Required connection settings are empty: {', '.join(missing)}")
        if (
            self.environment == "production"
            and self.postgres_password.get_secret_value() == "change-me-local-only"
        ):
            raise ValueError("Production requires an explicitly supplied PostgreSQL password")
        return self

    @property
    def database_url(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        database = quote_plus(self.postgres_db)
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:"
            f"{self.postgres_port}/{database}"
        )

    @property
    def redis_url(self) -> str:
        credentials = ""
        if self.redis_password is not None:
            credentials = f":{quote_plus(self.redis_password.get_secret_value())}@"
        return f"redis://{credentials}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings object for the process."""

    return Settings()
