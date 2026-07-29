import pytest

from thiezer.domain.contracts import GeoPoint, SearchScope
from thiezer.domain.geospatial import haversine_distance_km
from thiezer.domain.search_cells import cover_circle
from thiezer.domain.static_scoring import (
    StaticFilterPolicy,
    passes_static_filters,
    score_raw_features,
)
from thiezer.providers.access.procedural import ProceduralAccessPointProvider
from thiezer.providers.static_layers.procedural import ProceduralSurfaceLayerProvider
from thiezer.services.surface_search import SurfaceSearchService


@pytest.mark.asyncio
async def test_armenia_coarse_to_fine_matches_exhaustive_res7_oracle() -> None:
    center = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    radius_km = 250.0
    static = ProceduralSurfaceLayerProvider()
    service = SurfaceSearchService(
        static_layers=static,
        access_provider=ProceduralAccessPointProvider(static),
    )
    result = await service.search(
        user_location=center,
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=radius_km,
        limit=40,
    )

    oracle_ids = cover_circle(center, radius_km, 7)
    oracle_raw = await static.evaluate_cells(oracle_ids)
    policy = StaticFilterPolicy()
    oracle_cells = [score_raw_features(item) for item in oracle_raw]
    oracle_cells = [cell for cell in oracle_cells if passes_static_filters(cell, policy)]
    oracle_top = sorted(
        oracle_cells,
        key=lambda cell: cell.static_score,
        reverse=True,
    )[:10]
    production_best = max(site.cell.static_score for site in result.sites)
    oracle_best = oracle_top[0].static_score
    recalled = sum(
        any(haversine_distance_km(cell.center, site.point) <= 15.0 for site in result.sites)
        for cell in oracle_top
    )

    assert result.diagnostics.large_radius_overpass_calls == 0
    assert result.diagnostics.weather_candidates <= 40
    assert oracle_best - production_best <= 0.02
    assert recalled / len(oracle_top) >= 0.95


@pytest.mark.asyncio
async def test_worldwide_search_uses_curated_global_destinations() -> None:
    center = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    radius_km = 150.0
    static = ProceduralSurfaceLayerProvider()
    service = SurfaceSearchService(
        static_layers=static,
        access_provider=ProceduralAccessPointProvider(static),
    )
    from thiezer.repositories.surface import SurfacePlaceRepository

    result = await SurfacePlaceRepository(service).search(
        user_location=center,
        scope=SearchScope.GLOBAL,
        country_code=None,
        max_distance_km=radius_km,
        limit=12,
    )

    assert result.matches
    assert all(place.source_provider == "darksky_catalog_v1" for place, _ in result.matches)
    assert all(place.country_code != "AM" for place, _ in result.matches)
