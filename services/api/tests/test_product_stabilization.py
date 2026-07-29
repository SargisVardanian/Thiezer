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


class _CountrySurfaceSearch:
    async def search(self, **_: object) -> SurfaceSearchResult:
        inside = GeoPoint(latitude_deg=40.35, longitude_deg=44.65)
        outside = GeoPoint(latitude_deg=40.60, longitude_deg=43.10)
        return SurfaceSearchResult(
            sites=[_site("armenia", inside), _site("across-border", outside)],
            diagnostics=SurfaceSearchDiagnostics(
                coarse_resolution=5,
                fine_resolution=7,
                coarse_cells=2,
                coarse_after_filters=2,
                selected_parents=2,
                fine_cells=2,
                fine_after_filters=2,
                selected_fine_cells=2,
                materialized_sites=2,
                weather_candidates=2,
                static_evaluations=4,
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
    identifiers = {place.id for place, _ in batch.matches}
    assert identifiers == {"inside", "observer-location:+0:+0"}
    assert all(distance <= 250.5 for _, distance in batch.matches)
    coordinates = {
        (place.point.latitude_deg, place.point.longitude_deg) for place, _ in batch.matches
    }
    assert len(coordinates) == len(batch.matches)


@pytest.mark.asyncio
async def test_final_surface_points_respect_country_after_access_materialization() -> None:
    repository = SurfacePlaceRepository(_CountrySurfaceSearch())  # type: ignore[arg-type]
    batch = await repository.search(
        user_location=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
        scope=SearchScope.COUNTRY,
        country_code="AM",
        max_distance_km=250.0,
        limit=10,
    )

    identifiers = {place.id for place, _ in batch.matches}
    assert "armenia" in identifiers
    assert "across-border" not in identifiers


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


@pytest.mark.asyncio
async def test_travel_destination_ranks_before_observer_location_for_bright_targets() -> None:
    origin = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    observer = make_place(
        place_id="observer",
        name="Current location",
        latitude_deg=origin.latitude_deg,
        longitude_deg=origin.longitude_deg,
        darkness=0.001,
    ).model_copy(update={"source_provider": "user_origin"})
    destination = make_place(
        place_id="destination",
        name="Dark-sky site",
        latitude_deg=40.5,
        longitude_deg=44.2,
        darkness=0.82,
    ).model_copy(update={"accessibility_score": 0.08})
    service = RecommendationService(
        place_repository=SeedPlaceRepository([observer, destination]),
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
            scope=SearchScope.COUNTRY,
            country_code="AM",
            max_distance_km=250.0,
            max_results=2,
            minimum_score=0.1,
        )
    )

    assert [item.place.id for item in response.results] == ["destination", "observer"]
