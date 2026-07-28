from conftest import make_place

from thiezer.domain.travel import calculate_travel_utility


def test_travel_distance_changes_utility_not_sky_quality() -> None:
    place = make_place(
        place_id="utility",
        name="Utility test",
        latitude_deg=40.2,
        longitude_deg=44.5,
        darkness=0.9,
    )
    near = calculate_travel_utility(
        sky_quality=0.82,
        distance_km=20.0,
        maximum_distance_km=250.0,
        place=place,
        forecast_confidence=0.9,
    )
    far = calculate_travel_utility(
        sky_quality=0.82,
        distance_km=220.0,
        maximum_distance_km=250.0,
        place=place,
        forecast_confidence=0.9,
    )
    assert near.sky_quality == far.sky_quality == 0.82
    assert near.total > far.total
