from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import FakeAstronomyProvider, FakeWeatherProvider, make_place

from thiezer.domain.contracts import (
    GeoPoint,
    RecommendationSearchRequest,
    SearchScope,
    TargetKind,
)
from thiezer.domain.surface import (
    SurfaceCell,
    SurfaceDataQuality,
    SurfaceSearchDiagnostics,
    SurfaceSearchResult,
    SurfaceSite,
)
from thiezer.repositories.seed import SeedPlaceRepository
from thiezer.repositories.surface import SurfacePlaceRepository
from thiezer.services.recommendations import RecommendationService


def _cell(point: GeoPoint) -> SurfaceCell:
    return SurfaceCell(
        h3_index="872b5a375ffffff",
        resolution=7,
        center=point,
        elevation_m=1200.0,
        slope_deg=2.0,
        roughness_m=10.0,
        mean_radiance_0_5_km=0.1,
        mean_radiance_5_25_km=0.1,
        mean_radiance_25_80_km=0.1,
        water_fraction=0.0,
        urban_fraction=0.0,
        forest_fraction=0.1,
        open_land_fraction=0.9,
        distance_to_road_km=1.0,
        distance_to_settlement_km=10.0,
        restricted=False,
        darkness_score=0.9,
        terrain_score=0.9,
        land_score=0.9,
        access_potential=0.8,
        static_score=0.9,
        static_upper_bound=0.95,
        uncertainty=0.2,
        data_quality=SurfaceDataQuality.PROCEDURAL_FALLBACK,
    )


def _site(identifier: str, point: GeoPoint) -> SurfaceSite:
    cell = _cell(point)
    return SurfaceSite(
        id=identifier,
        name=identifier,
        point=point,
        cell=cell,
        elevation_m=cell.elevation_m,
        slope_deg=cell.slope_deg,
        horizon_openness_score=0.9,
        accessibility_score=0.8,
        risk_score=0.1,
        road_access="test",
        source_url=None,
        source_provider="test",
    )


class _FakeSurfaceSearch:
    async def search(self, **_: object) -> SurfaceSearchResult:
        inside = GeoPoint(latitude_deg=0.0, longitude_deg=1.0)
        outside = GeoPoint(latitude_deg=0.0, longitude_deg=2.51)
        return SurfaceSearchResult(
            sites=[
                _site("inside", inside),
                _site("duplicate", inside),
                _site("outside", outside),
            ],
            diagnostics=SurfaceSearchDiagnostics(
                coarse_resolution=5,
                fine_resolution=7,
                coarse_cells=3,
                coarse_after_filters=3,
                selected_parents=3,
                fine_cells=3,
                fine_after_filters=3,
                selected_fine_cells=3,
                materialized_sites=3,
                weather_candidates=3,
                static_evaluations=6,
                large_radius_overpass_calls=0,
            ),
            attributions=("test",),
            darkness_is_proxy=True,
        )


@pytest.mark.asyncio
async def test_final_surface_points_respect_radius_and_are_deduplicated() -> None:
    repository = SurfacePlaceRepository(_FakeSurfaceSearch())  # type: ignore[arg-type]
    batch = await repository.search(
        user_location=GeoPoint(latitude_deg=0.0, longitude_deg=0.0),
        scope=SearchScope.ADAPTIVE,
        country_code=None,
        max_distance_km=250.0,
        limit=10,
    )
    assert len(batch.matches) == 1
    assert batch.matches[0][0].id == "inside"
    assert batch.matches[0][1] <= 250.5


@pytest.mark.asyncio
async def test_moon_prefers_nearest_acceptable_place() -> None:
    origin = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    near = make_place(
        place_id="near",
        name="Nearby open site",
        latitude_deg=40.20,
        longitude_deg=44.52,
        darkness=0.55,
    )
    far = make_place(
        place_id="far",
        name="Distant dark site",
        latitude_deg=40.90,
        longitude_deg=44.00,
        darkness=0.98,
    )
    service = RecommendationService(
        place_repository=SeedPlaceRepository([near, far]),
        weather_provider=FakeWeatherProvider(),
        astronomy_provider=FakeAstronomyProvider(),
    )
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    response = await service.search(
        RecommendationSearchRequest(
            user_location=origin,
            target=TargetKind.MOON,
            start_utc=start,
            end_utc=start + timedelta(hours=3),
            scope=SearchScope.ADAPTIVE,
            max_distance_km=250.0,
            max_results=2,
            minimum_score=0.1,
        )
    )
    assert response.results[0].place.id == "near"
    assert response.results[0].distance_km < response.results[1].distance_km
