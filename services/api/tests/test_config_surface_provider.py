import pytest
from pydantic import ValidationError

from thiezer.config import Settings


def test_development_allows_procedural_surface_fixture() -> None:
    settings = Settings(environment="development", surface_provider="procedural")
    assert settings.surface_provider == "procedural"


def test_production_rejects_procedural_surface_fixture() -> None:
    with pytest.raises(ValidationError, match="production requires the calibrated COG"):
        Settings(environment="production", surface_provider="procedural")


def test_production_accepts_configured_cog_surface_provider() -> None:
    settings = Settings(
        environment="production",
        surface_provider="cog",
        dem_cog_url="file:///data/copernicus-dem.tif",
        worldcover_cog_url="file:///data/worldcover.tif",
        viirs_cog_url="file:///data/viirs.tif",
    )
    assert settings.surface_provider == "cog"
