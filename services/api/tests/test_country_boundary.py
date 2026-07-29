from thiezer.domain.boundaries import StaticCountryBoundaryProvider
from thiezer.domain.contracts import GeoPoint


def test_armenia_boundary_accepts_armenia_and_rejects_neighbouring_countries() -> None:
    boundaries = StaticCountryBoundaryProvider()
    assert boundaries.supports("AM")
    assert boundaries.contains(
        "AM",
        GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
    )
    assert boundaries.contains("AM", GeoPoint(latitude_deg=40.7894, longitude_deg=43.8475))
    assert not boundaries.contains("AM", GeoPoint(latitude_deg=41.7151, longitude_deg=44.8271))
    assert not boundaries.contains("AM", GeoPoint(latitude_deg=39.2348, longitude_deg=43.6702))
    assert not boundaries.contains("AM", GeoPoint(latitude_deg=39.3262, longitude_deg=45.6537))
