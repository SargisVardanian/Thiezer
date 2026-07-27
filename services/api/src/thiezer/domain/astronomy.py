from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum


class TwilightClass(StrEnum):
    DAY = "day"
    CIVIL = "civil_twilight"
    NAUTICAL = "nautical_twilight"
    ASTRONOMICAL = "astronomical_twilight"
    NIGHT = "night"


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def julian_date(timestamp: datetime) -> float:
    """Return Julian Date for a timezone-aware timestamp."""

    value = _require_aware_utc(timestamp)
    year = value.year
    month = value.month
    day_fraction = (
        value.day
        + value.hour / 24.0
        + value.minute / 1440.0
        + (value.second + value.microsecond / 1_000_000.0) / 86400.0
    )
    if month <= 2:
        year -= 1
        month += 12
    century = math.floor(year / 100)
    correction = 2 - century + math.floor(century / 4)
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day_fraction
        + correction
        - 1524.5
    )


def greenwich_mean_sidereal_time_deg(timestamp: datetime) -> float:
    """Approximate Greenwich mean sidereal time in degrees."""

    jd = julian_date(timestamp)
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t**2
        - t**3 / 38710000.0
    )
    return gmst % 360.0


def local_sidereal_time_deg(timestamp: datetime, longitude_deg: float) -> float:
    return (greenwich_mean_sidereal_time_deg(timestamp) + longitude_deg) % 360.0


def equatorial_to_horizontal(
    *,
    right_ascension_deg: float,
    declination_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    timestamp: datetime,
) -> tuple[float, float]:
    """Convert equatorial coordinates to azimuth and altitude in degrees.

    Azimuth is measured clockwise from north in [0, 360).
    """

    lst = local_sidereal_time_deg(timestamp, longitude_deg)
    hour_angle = math.radians((lst - right_ascension_deg) % 360.0)
    latitude = math.radians(latitude_deg)
    declination = math.radians(declination_deg)

    sin_altitude = (
        math.sin(latitude) * math.sin(declination)
        + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle)
    )
    altitude = math.asin(max(-1.0, min(1.0, sin_altitude)))

    y = -math.sin(hour_angle) * math.cos(declination)
    x = (
        math.sin(declination) * math.cos(latitude)
        - math.cos(declination) * math.sin(latitude) * math.cos(hour_angle)
    )
    azimuth = math.atan2(y, x)
    return math.degrees(azimuth) % 360.0, math.degrees(altitude)


def angular_separation_deg(
    ra1_deg: float,
    dec1_deg: float,
    ra2_deg: float,
    dec2_deg: float,
) -> float:
    ra1 = math.radians(ra1_deg)
    dec1 = math.radians(dec1_deg)
    ra2 = math.radians(ra2_deg)
    dec2 = math.radians(dec2_deg)
    cosine = (
        math.sin(dec1) * math.sin(dec2)
        + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def airmass_kasten_young(altitude_deg: float) -> float:
    """Kasten-Young relative optical air mass.

    Returns infinity at or below the geometric horizon.
    """

    if altitude_deg <= 0.0:
        return math.inf
    zenith_deg = 90.0 - altitude_deg
    denominator = math.cos(math.radians(zenith_deg)) + 0.50572 * (
        96.07995 - zenith_deg
    ) ** -1.6364
    return 1.0 / denominator


def classify_twilight(sun_altitude_deg: float) -> TwilightClass:
    if sun_altitude_deg >= 0.0:
        return TwilightClass.DAY
    if sun_altitude_deg >= -6.0:
        return TwilightClass.CIVIL
    if sun_altitude_deg >= -12.0:
        return TwilightClass.NAUTICAL
    if sun_altitude_deg >= -18.0:
        return TwilightClass.ASTRONOMICAL
    return TwilightClass.NIGHT
