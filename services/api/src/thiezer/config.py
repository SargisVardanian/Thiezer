from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
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
    storage_mode: Literal["ephemeral"] = "ephemeral"
    database_enabled: bool = False
    query_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    result_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    weather_cache_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    elevation_cache_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    stac_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    catalog_cache_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    horizons_cache_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    overpass_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    database_url: str = "postgresql+asyncpg://thiezer:thiezer@localhost:5432/thiezer"

    open_meteo_base_url: AnyHttpUrl = Field(default=AnyHttpUrl("https://api.open-meteo.com/v1"))
    open_meteo_api_key: str | None = None

    overpass_enabled: bool = True
    overpass_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://overpass-api.de/api/interpreter")
    )
    overpass_timeout_seconds: float = Field(default=25.0, ge=5.0, le=60.0)
    overpass_local_radius_km: float = Field(default=5.0, ge=2.0, le=10.0)

    routing_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://router.project-osrm.org/route/v1")
    )
    routing_timeout_seconds: float = Field(default=20.0, ge=5.0, le=45.0)

    surface_provider: Literal["procedural", "cog"] = "procedural"
    dem_cog_url: str | None = None
    worldcover_cog_url: str | None = None
    viirs_cog_url: str | None = None

    cors_allow_all: bool = True

    @model_validator(mode="after")
    def validate_surface_provider(self) -> "Settings":
        if self.surface_provider == "cog" and (not self.dem_cog_url or not self.worldcover_cog_url):
            raise ValueError("cog surface provider requires DEM and WorldCover COG URLs")
        if self.environment.casefold() in {"production", "prod"} and self.surface_provider != "cog":
            raise ValueError("production requires the calibrated COG surface provider")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
