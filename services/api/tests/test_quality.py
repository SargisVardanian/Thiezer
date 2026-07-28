from datetime import UTC, datetime

from conftest import make_condition, make_place

from thiezer.domain.contracts import AstronomySnapshot, GeoPoint, ObservationMode, TargetKind
from thiezer.domain.quality import (
    build_score_inputs,
    cloud_clearance_score,
    dew_margin_score,
    forecast_confidence_score,
    moon_interference_score,
    site_altitude_score,
)


def _snapshot(
    *,
    moon_altitude: float,
    moon_illumination: float,
    separation: float,
) -> AstronomySnapshot:
    return AstronomySnapshot(
        timestamp_utc=datetime(2026, 7, 29, 20, tzinfo=UTC),
        target=TargetKind.MILKY_WAY,
        target_label="Milky Way",
        altitude_deg=45.0,
        azimuth_deg=180.0,
        sun_altitude_deg=-24.0,
        moon_altitude_deg=moon_altitude,
        moon_illumination_fraction=moon_illumination,
        moon_separation_deg=separation,
        airmass=1.4,
        above_geometric_horizon=True,
    )


def test_more_cloud_cannot_improve_clearance() -> None:
    point = GeoPoint(latitude_deg=40.3, longitude_deg=44.3)
    timestamp = datetime(2026, 7, 29, 20, tzinfo=UTC)
    clear = make_condition(point=point, timestamp_utc=timestamp, cloud=0.05)
    cloudy = make_condition(point=point, timestamp_utc=timestamp, cloud=0.8)
    assert cloud_clearance_score(clear) > cloud_clearance_score(cloudy)


def test_moon_below_horizon_has_no_interference() -> None:
    below = _snapshot(moon_altitude=-2.0, moon_illumination=1.0, separation=10.0)
    bright_nearby = _snapshot(moon_altitude=60.0, moon_illumination=1.0, separation=10.0)
    assert moon_interference_score(target=TargetKind.MILKY_WAY, astronomy=below) == 1.0
    assert moon_interference_score(target=TargetKind.MILKY_WAY, astronomy=bright_nearby) < 0.3


def test_dew_and_altitude_scores_are_bounded_and_monotonic() -> None:
    assert dew_margin_score(temperature_c=5.0, dew_point_c=5.0) == 0.0
    assert dew_margin_score(temperature_c=15.0, dew_point_c=0.0) == 1.0
    assert site_altitude_score(2500.0) > site_altitude_score(500.0)


def test_forecast_confidence_decreases_with_lead_time() -> None:
    start = datetime(2026, 7, 29, tzinfo=UTC)
    near = forecast_confidence_score(forecast_time_utc=start, search_started_utc=start)
    week = forecast_confidence_score(
        forecast_time_utc=datetime(2026, 8, 5, tzinfo=UTC),
        search_started_utc=start,
    )
    two_weeks = forecast_confidence_score(
        forecast_time_utc=datetime(2026, 8, 12, tzinfo=UTC),
        search_started_utc=start,
    )
    assert near > week > two_weeks


def test_alpha_centauri_below_horizon_triggers_hard_gate() -> None:
    point = GeoPoint(latitude_deg=40.3, longitude_deg=44.3)
    timestamp = datetime(2026, 7, 29, 20, tzinfo=UTC)
    condition = make_condition(point=point, timestamp_utc=timestamp)
    astronomy = _snapshot(moon_altitude=-2.0, moon_illumination=0.1, separation=120.0).model_copy(
        update={
            "target": TargetKind.ALPHA_CENTAURI,
            "altitude_deg": -12.0,
            "above_geometric_horizon": False,
        }
    )
    inputs = build_score_inputs(
        target=TargetKind.ALPHA_CENTAURI,
        mode=ObservationMode.NAKED_EYE,
        place=make_place(
            place_id="test",
            name="Test",
            latitude_deg=40.3,
            longitude_deg=44.3,
            darkness=0.9,
        ),
        conditions=condition,
        astronomy=astronomy,
        search_started_utc=timestamp,
        distance_km=10.0,
        maximum_distance_km=100.0,
    )
    assert inputs.target_above_horizon is False
