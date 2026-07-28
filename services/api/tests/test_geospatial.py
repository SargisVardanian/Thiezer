from urllib.parse import parse_qs, urlparse

import pytest

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.geospatial import build_route_handoffs, haversine_distance_km


def test_haversine_is_symmetric_and_zero_for_same_point() -> None:
    yerevan = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    gyumri = GeoPoint(latitude_deg=40.7929, longitude_deg=43.8465)
    assert haversine_distance_km(yerevan, yerevan) == pytest.approx(0.0)
    assert haversine_distance_km(yerevan, gyumri) == pytest.approx(
        haversine_distance_km(gyumri, yerevan)
    )
    assert 80.0 < haversine_distance_km(yerevan, gyumri) < 100.0


def test_google_route_handoff_is_no_key_universal_url() -> None:
    origin = GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035)
    destination = GeoPoint(latitude_deg=40.3307, longitude_deg=44.2735)
    routes = build_route_handoffs(origin=origin, destination=destination, label="Byurakan")
    google = next(route for route in routes if route.provider == "google_maps")
    parsed = urlparse(google.url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "www.google.com"
    assert query["api"] == ["1"]
    assert query["travelmode"] == ["driving"]
    assert google.requires_api_key is False
    assert {route.provider for route in routes} == {
        "google_maps",
        "apple_maps",
        "yandex_maps_web",
        "geo_uri",
    }
