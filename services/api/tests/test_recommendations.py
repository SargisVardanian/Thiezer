from datetime import UTC, datetime, timedelta

import pytest
from conftest import FakeAstronomyProvider, FakeWeatherProvider, make_place

from thiezer.domain.celestial_objects import CatalogSource, CelestialObjectId
from thiezer.domain.contracts import (
    GeoPoint,
    ObservationMode,
    RecommendationSearchRequest,
    SearchScope,
    TargetKind,
    WarningCode,
)
from thiezer.providers.catalogs.simbad import simbad_fixture
from thiezer.repositories.seed import SeedPlaceRepository
from thiezer.services.celestial_resolution import CelestialResolutionService
from thiezer.services.celestial_visibility import CelestialVisibilityService
from thiezer.services.recommendations import RecommendationService


@pytest.mark.asyncio
async def test_recommendation_service_batches_weather_and_ranks_deterministically() -> None:
    origin = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    near = make_place(
        place_id="near",
        name="Near dark site",
        latitude_deg=40.30,
        longitude_deg=44.40,
        darkness=0.82,
    )
    far = make_place(
        place_id="far",
        name="Far dark site",
        latitude_deg=40.70,
        longitude_deg=44.10,
        darkness=0.90,
    )
    weather = FakeWeatherProvider()
    service = RecommendationService(
        place_repository=SeedPlaceRepository([near, far]),
        weather_provider=weather,
        astronomy_provider=FakeAstronomyProvider(),
    )
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    response = await service.search(
        RecommendationSearchRequest(
            user_location=origin,
            target=TargetKind.JUPITER,
            observation_mode=ObservationMode.NAKED_EYE,
            start_utc=start,
            end_utc=start + timedelta(hours=3),
            scope=SearchScope.COUNTRY,
            country_code="AM",
            max_distance_km=200.0,
            max_results=2,
            minimum_score=0.1,
        )
    )
    assert weather.batch_calls == 1
    assert [result.rank for result in response.results] == [1, 2]
    assert response.results[0].place.id == "near"
    assert response.results[0].observation_window.best_astronomy.target == TargetKind.JUPITER
    assert any(route.provider == "google_maps" for route in response.results[0].routes)
    assert WarningCode.UNVERIFIED_PLACE in response.results[0].warnings


@pytest.mark.asyncio
async def test_alpha_centauri_returns_honest_no_result_for_armenia_geometry() -> None:
    place = make_place(
        place_id="armenia",
        name="Armenia test site",
        latitude_deg=40.3,
        longitude_deg=44.3,
        darkness=0.9,
    )
    service = RecommendationService(
        place_repository=SeedPlaceRepository([place]),
        weather_provider=FakeWeatherProvider(),
        astronomy_provider=FakeAstronomyProvider(),
    )
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    response = await service.search(
        RecommendationSearchRequest(
            user_location=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
            target=TargetKind.ALPHA_CENTAURI,
            start_utc=start,
            end_utc=start + timedelta(hours=3),
            country_code="AM",
            minimum_score=0.0,
        )
    )
    assert response.results == []
    assert response.warnings == [WarningCode.TARGET_NOT_VISIBLE_IN_SCOPE]


@pytest.mark.asyncio
async def test_best_night_sky_returns_destinations_when_forecast_rejects_every_window() -> None:
    place = make_place(
        place_id="dark-site",
        name="Dark site",
        latitude_deg=40.3,
        longitude_deg=44.3,
        darkness=0.9,
    )
    service = RecommendationService(
        place_repository=SeedPlaceRepository([place]),
        weather_provider=FakeWeatherProvider(cloud_by_longitude={44.3: 1.0}),
        astronomy_provider=FakeAstronomyProvider(),
    )
    start = datetime(2026, 7, 29, 18, tzinfo=UTC)
    response = await service.search(
        RecommendationSearchRequest(
            user_location=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
            target=TargetKind.BEST_NIGHT_SKY,
            start_utc=start,
            end_utc=start + timedelta(hours=3),
            max_distance_km=200.0,
            minimum_score=0.35,
        )
    )

    assert [item.place.id for item in response.results] == ["dark-site"]
    assert WarningCode.LOW_CONFIDENCE in response.results[0].warnings


@pytest.mark.asyncio
async def test_catalog_target_uses_catalog_geometry_per_candidate_hour() -> None:
    place = make_place(
        place_id="m31-site", name="M31 site", latitude_deg=40.3, longitude_deg=44.3, darkness=0.9
    )
    resolution = CelestialResolutionService({CatalogSource.SIMBAD: simbad_fixture()})
    visibility = CelestialVisibilityService(resolution)
    service = RecommendationService(
        place_repository=SeedPlaceRepository([place]),
        weather_provider=FakeWeatherProvider(),
        astronomy_provider=FakeAstronomyProvider(),
        celestial_resolution=resolution,
        celestial_visibility=visibility,
    )
    start = datetime(2026, 10, 1, 18, tzinfo=UTC)
    response = await service.search(
        RecommendationSearchRequest(
            user_location=GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
            target={"catalog_object": {"provider": "simbad", "object_id": "M 31"}},
            start_utc=start,
            end_utc=start + timedelta(hours=3),
            minimum_score=0.0,
        )
    )
    assert response.target.catalog_object == CelestialObjectId(
        provider=CatalogSource.SIMBAD, object_id="M 31"
    )
    assert response.results[0].observation_window.best_astronomy.target_label == "Andromeda Galaxy"
