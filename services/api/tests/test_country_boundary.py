from thiezer.domain.boundaries import StaticCountryBoundaryProvider
from thiezer.domain.contracts import GeoPoint


def test_armenia_boundary_accepts_yerevan_and_rejects_tbilisi() -> None:
    boundaries = StaticCountryBoundaryProvider()
    assert boundaries.supports("AM")
    assert boundaries.contains(
        "AM",
        GeoPoint(latitude_deg=40.1772, longitude_deg=44.5035),
    )
    assert not boundaries.contains(
        "AM",
        GeoPoint(latitude_deg=41.7151, longitude_deg=44.8271),
    )
