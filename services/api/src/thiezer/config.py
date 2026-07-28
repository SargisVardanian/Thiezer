from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="THIEZER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://thiezer:thiezer@localhost:5432/thiezer"

    open_meteo_base_url: AnyHttpUrl = Field(default=AnyHttpUrl("https://api.open-meteo.com/v1"))
    open_meteo_api_key: str | None = None

    overpass_enabled: bool = True
    overpass_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://overpass-api.de/api/interpreter")
    )
    overpass_timeout_seconds: float = Field(default=25.0, ge=5.0, le=60.0)

    cors_allow_all: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
