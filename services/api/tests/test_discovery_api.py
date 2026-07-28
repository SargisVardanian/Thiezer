from datetime import UTC, datetime, timedelta

from conftest import FakeAstronomyProvider, FakeWeatherProvider, make_place
from fastapi.testclient import TestClient

from thiezer.api.dependencies import get_recommendation_service, get_store_service
from thiezer.main import app
from thiezer.repositories.seed import SeedPlaceRepository, SeedStoreRepository
from thiezer.services.recommendations import RecommendationService
from thiezer.services.stores import StoreSearchService


def test_targets_endpoint_lists_requested_targets() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/targets")
    assert response.status_code == 200
    identifiers = {item["id"] for item in response.json()}
    assert {
        "alpha_centauri",
        "mars",
        "jupiter",
        "moon",
        "milky_way",
        "best_night_sky",
    } <= identifiers


def test_store_search_returns_route_for_physical_store_without_live_network() -> None:
    app.dependency_overrides[get_store_service] = lambda: StoreSearchService(SeedStoreRepository())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/stores/search",
                json={
                    "user_location": {"latitude_deg": 40.1772, "longitude_deg": 44.5035},
                    "scope": "country",
                    "country_code": "AM",
                    "max_distance_km": 300,
                    "max_results": 10,
                },
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    physical = next(item for item in body["results"] if item["distance_km"] is not None)
    assert any(route["provider"] == "google_maps" for route in physical["routes"])


def test_recommendation_api_uses_injected_services_without_live_network() -> None:
    place = make_place(
        place_id="api-site",
        name="API test site",
        latitude_deg=40.3,
        longitude_deg=44.3,
        darkness=0.9,
    )
    service = RecommendationService(
        place_repository=SeedPlaceRepository([place]),
        weather_provider=FakeWeatherProvider(),
        astronomy_provider=FakeAstronomyProvider(),
    )
    app.dependency_overrides[get_recommendation_service] = lambda: service
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/recommendations/search",
                json={
                    "user_location": {
                        "latitude_deg": 40.1772,
                        "longitude_deg": 44.5035,
                    },
                    "target": "milky_way",
                    "observation_mode": "naked_eye",
                    "start_utc": start.isoformat(),
                    "end_utc": (start + timedelta(hours=3)).isoformat(),
                    "scope": "adaptive",
                    "max_distance_km": 200,
                    "minimum_score": 0.1,
                },
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["place"]["id"] == "api-site"
    assert body["search_radius_km"] == 200
