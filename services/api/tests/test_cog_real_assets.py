from __future__ import annotations

import math
from pathlib import Path

import pytest

from thiezer.domain.contracts import GeoPoint
from thiezer.providers.static_layers.cog import CogLayerConfig, CogSurfaceLayerProvider

ROOT = Path(__file__).resolve().parents[3]
DEM = ROOT / "data/processed/armenia_300km/copernicus_dem.tif"
WORLDCOVER = ROOT / "data/processed/armenia_300km/worldcover.tif"


@pytest.mark.asyncio
async def test_real_armenia_cogs_sample_surface_features() -> None:
    if not DEM.exists() or not WORLDCOVER.exists():
        pytest.skip("local Armenia real-data COG pack is not installed")
    provider = CogSurfaceLayerProvider(
        CogLayerConfig(dem_url=str(DEM), worldcover_url=str(WORLDCOVER))
    )
    feature = (
        await provider.evaluate_points(
            points=[GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)],
            resolution=7,
        )
    )[0]
    assert all(
        math.isfinite(value)
        for value in (
            feature.elevation_m,
            feature.slope_deg,
            feature.roughness_m,
            feature.water_fraction,
            feature.urban_fraction,
            feature.forest_fraction,
            feature.open_land_fraction,
        )
    )
    assert 0.0 <= feature.water_fraction <= 1.0
    assert 0.0 <= feature.urban_fraction <= 1.0
    assert 0.0 <= feature.forest_fraction <= 1.0
    assert 0.0 <= feature.open_land_fraction <= 1.0
    assert provider.darkness_is_proxy is True
