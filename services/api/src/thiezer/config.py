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
    open_meteo_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://api.open-meteo.com/v1")
    )
    open_meteo_api_key: str | None = None
    overpass_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://overpass-api.de/api/interpreter")
    )
    dynamic_discovery_enabled: bool = True
    surface_pack_path: str | None = None
    surface_coarse_parent_budget: int = 24
    surface_static_shortlist_budget: int = 60
    local_access_radius_km: float = 6.0
    provider_max_connections: int = 12
    provider_max_keepalive_connections: int = 6


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
