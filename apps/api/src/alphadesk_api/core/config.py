"""Type-safe application configuration."""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import quote_plus, urlsplit

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
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

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
    market_backfill_batch_size: int = Field(default=500, ge=1, le=5000)
    market_backfill_request_interval_seconds: float = Field(default=0.1, ge=0, le=10)
    market_backfill_max_retries: int = Field(default=2, ge=0, le=2)
    market_backfill_max_instruments: int = Field(default=500, ge=1, le=500)
    market_daily_default_start_date: date = date(2023, 1, 1)
    market_data_stale_calendar_days: int = Field(default=7, ge=1, le=90)
    market_data_backtest_minimum_bars: int = Field(default=250, ge=20, le=5000)
    market_future_tolerance_seconds: int = Field(default=300, ge=0, le=3600)
    market_minute_stale_seconds: int = Field(default=300, ge=30, le=86400)
    market_csv_max_bytes: int = Field(default=10_000_000, ge=1024, le=100_000_000)
    market_csv_max_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    intraday_import_max_file_size_mb: int = Field(default=64, ge=1, le=512)
    intraday_import_batch_size: int = Field(default=1_000, ge=100, le=5_000)
    intraday_query_max_bars: int = Field(default=5_000, ge=100, le=50_000)
    intraday_max_instruments: int = Field(default=20, ge=1, le=200)
    intraday_max_date_range_days: int = Field(default=31, ge=1, le=366)
    external_market_data_enabled: bool = False
    free_market_enabled: bool = False
    realtime_market_provider: Literal["disabled"] = "disabled"
    historical_market_provider: Literal["baostock"] = "baostock"
    tushare_enabled: bool = False
    tushare_token: SecretStr | None = None
    market_calendar_provider: Literal["fixture", "tushare"] = "fixture"
    market_adjustment_provider: Literal["fixture", "tushare"] = "fixture"
    market_suspension_provider: Literal["fixture", "tushare"] = "fixture"
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
    backtest_max_instruments: int = Field(default=20, ge=1, le=200)
    backtest_max_bars: int = Field(default=100_000, ge=1, le=2_000_000)
    backtest_max_sessions: int = Field(default=5_000, ge=1, le=20_000)
    replay_interval_x1_ms: int = Field(default=1000, ge=100, le=60_000)
    replay_interval_x10_ms: int = Field(default=250, ge=25, le=10_000)
    replay_interval_x100_ms: int = Field(default=50, ge=10, le=1_000)
    replay_max_instruments: int = Field(default=20, ge=1, le=200)
    replay_max_sessions: int = Field(default=5_000, ge=1, le=20_000)
    replay_worker_poll_ms: int = Field(default=250, ge=50, le=10_000)
    replay_worker_lease_seconds: int = Field(default=15, ge=5, le=300)
    replay_worker_heartbeat_seconds: int = Field(default=5, ge=1, le=60)
    risk_max_order_notional: Decimal | None = Decimal("1000000")
    risk_max_instrument_weight: Decimal | None = Decimal("1")
    risk_max_total_exposure: Decimal | None = Decimal("1")
    risk_max_orders_per_window: int | None = Field(default=20, ge=1)
    risk_order_frequency_window_seconds: int = Field(default=60, ge=1)
    risk_allow_market_orders: bool = False
    risk_require_reference_price_for_market_order: bool = True
    risk_kill_switch_enabled: bool = False
    ai_research_provider: Literal["disabled", "fake", "openai_compatible"] = "disabled"
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_model: str | None = None
    ai_request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    ai_max_retries: int = Field(default=1, ge=0, le=3)
    ai_max_input_characters: int = Field(default=50_000, ge=1_000, le=1_000_000)
    ai_max_output_tokens: int = Field(default=2_000, ge=64, le=128_000)
    ai_temperature: Decimal = Field(default=Decimal("0.1"), ge=0, le=2)
    ai_cost_input_per_million: Decimal | None = Field(default=None, ge=0)
    ai_cost_output_per_million: Decimal | None = Field(default=None, ge=0)
    ai_structured_output_enabled: bool = True

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

    @field_validator("ai_base_url")
    @classmethod
    def validate_ai_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "ai_base_url must be an http(s) URL without credentials, query or fragment"
            )
        return normalized

    @field_validator(
        "ai_cost_input_per_million",
        "ai_cost_output_per_million",
        mode="before",
    )
    @classmethod
    def normalize_optional_ai_price(cls, value: object) -> object | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("ai_api_key", "tushare_token", mode="before")
    @classmethod
    def normalize_optional_ai_api_key(cls, value: object) -> object | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("ai_model")
    @classmethod
    def validate_ai_model(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if len(normalized) > 128 or any(char.isspace() for char in normalized):
            raise ValueError("ai_model must be a non-empty model identifier")
        return normalized

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
