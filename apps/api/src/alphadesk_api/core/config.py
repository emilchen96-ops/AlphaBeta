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

    redis_host: str = "redis"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: SecretStr | None = None

    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    websocket_heartbeat_seconds: int = Field(default=20, ge=5, le=300)
    correlation_id_header: str = "X-Correlation-ID"
    max_websocket_message_bytes: int = Field(default=1024, ge=64, le=65536)

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
