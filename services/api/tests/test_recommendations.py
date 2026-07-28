from datetime import UTC, datetime, timedelta

import pytest
from conftest import FakeAstronomyProvider, FakeWeatherProvider, make_place

from thiezer.domain.contracts import (
    GeoPoint,
    ObservationMode,
    RecommendationSearchRequest,
    SearchScope,
    TargetKind,
    WarningCode,
)
from thiezer.repositories.seed import SeedPlaceRepository
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
