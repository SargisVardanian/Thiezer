import math
from datetime import UTC, datetime

import pytest

from thiezer.domain.astronomy import (
    TwilightClass,
    airmass_kasten_young,
    angular_separation_deg,
    classify_twilight,
    equatorial_to_horizontal,
    julian_date,
    local_sidereal_time_deg,
)


def test_j2000_julian_date() -> None:
    timestamp = datetime(2000, 1, 1, 12, tzinfo=UTC)
    assert julian_date(timestamp) == pytest.approx(2451545.0, abs=1e-9)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        julian_date(datetime(2000, 1, 1, 12))


def test_airmass_at_zenith_is_near_one() -> None:
    assert airmass_kasten_young(90.0) == pytest.approx(0.9997, rel=1e-3)
    assert math.isinf(airmass_kasten_young(0.0))


def test_angular_separation_identity() -> None:
    assert angular_separation_deg(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)


def test_object_on_meridian_at_equator_reaches_zenith() -> None:
    timestamp = datetime(2026, 7, 27, 20, tzinfo=UTC)
    ra_deg = local_sidereal_time_deg(timestamp, 0.0)
    _, altitude = equatorial_to_horizontal(
        right_ascension_deg=ra_deg,
        declination_deg=0.0,
        latitude_deg=0.0,
        longitude_deg=0.0,
        timestamp=timestamp,
    )
    assert altitude == pytest.approx(90.0, abs=1e-7)


@pytest.mark.parametrize(
    ("sun_altitude", "expected"),
    [
        (2.0, TwilightClass.DAY),
        (-2.0, TwilightClass.CIVIL),
        (-8.0, TwilightClass.NAUTICAL),
        (-14.0, TwilightClass.ASTRONOMICAL),
        (-20.0, TwilightClass.NIGHT),
    ],
)
def test_twilight_classification(sun_altitude: float, expected: TwilightClass) -> None:
    assert classify_twilight(sun_altitude) == expected
