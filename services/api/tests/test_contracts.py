from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from thiezer.domain.contracts import (
    AstronomicalPlanRequest,
    BoundingBox,
    GeoPoint,
    HourlySkyCondition,
    TargetKind,
)


def test_geo_point_rejects_invalid_latitude() -> None:
    with pytest.raises(ValidationError):
        GeoPoint(latitude_deg=91.0, longitude_deg=0.0)


def test_bounding_box_rejects_inverted_latitudes() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(
            south_west=GeoPoint(latitude_deg=50.0, longitude_deg=0.0),
            north_east=GeoPoint(latitude_deg=40.0, longitude_deg=1.0),
        )


def test_hourly_condition_requires_aware_timestamp() -> None:
    point = GeoPoint(latitude_deg=40.18, longitude_deg=44.51)
    with pytest.raises(ValidationError):
        HourlySkyCondition(
            timestamp_utc=datetime(2026, 7, 27, 20),
            total_cloud_fraction=0.1,
            low_cloud_fraction=0.1,
            mid_cloud_fraction=0.0,
            high_cloud_fraction=0.0,
            temperature_c=18.0,
            relative_humidity_fraction=0.4,
            dew_point_c=4.0,
            precipitation_mm=0.0,
            wind_speed_mps=2.0,
            provider="test",
            requested_point=point,
            returned_grid_point=point,
            attribution="test",
        )


def test_hourly_condition_accepts_utc() -> None:
    point = GeoPoint(latitude_deg=40.18, longitude_deg=44.51)
    condition = HourlySkyCondition(
        timestamp_utc=datetime(2026, 7, 27, 20, tzinfo=UTC),
        total_cloud_fraction=0.1,
        low_cloud_fraction=0.1,
        mid_cloud_fraction=0.0,
        high_cloud_fraction=0.0,
        temperature_c=18.0,
        relative_humidity_fraction=0.4,
        dew_point_c=4.0,
        precipitation_mm=0.0,
        wind_speed_mps=2.0,
        provider="test",
        requested_point=point,
        returned_grid_point=point,
        attribution="test",
    )
    assert condition.timestamp_utc.tzinfo is UTC


def test_best_night_sky_is_not_an_astronomical_plan_target() -> None:
    with pytest.raises(ValidationError, match="near-term place search"):
        AstronomicalPlanRequest(
            user_location=GeoPoint(latitude_deg=40.18, longitude_deg=44.51),
            target=TargetKind.BEST_NIGHT_SKY,
            start_utc=datetime(2026, 7, 29, tzinfo=UTC),
        )
