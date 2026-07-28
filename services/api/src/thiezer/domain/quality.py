from __future__ import annotations

import math
from datetime import UTC, datetime

from thiezer.domain.contracts import (
    AstronomySnapshot,
    CandidatePlace,
    HourlySkyCondition,
    ObservationMode,
    TargetKind,
)
from thiezer.domain.scoring import ScoreInputs


def build_score_inputs(
    *,
    target: TargetKind,
    mode: ObservationMode,
    place: CandidatePlace,
    conditions: HourlySkyCondition,
    astronomy: AstronomySnapshot,
    search_started_utc: datetime,
    distance_km: float,
    maximum_distance_km: float,
) -> ScoreInputs:
    cloud_clearance = cloud_clearance_score(conditions)
    darkness = place.darkness_score * astronomical_darkness_score(
        target=target,
        sun_altitude_deg=astronomy.sun_altitude_deg,
    )
    transparency = transparency_score(conditions=conditions, astronomy=astronomy)
    moon_conditions = moon_interference_score(target=target, astronomy=astronomy)
    dew_margin = dew_margin_score(
        temperature_c=conditions.temperature_c,
        dew_point_c=conditions.dew_point_c,
    )
    wind = wind_score(conditions.wind_speed_mps, mode=mode)
    target_altitude = target_altitude_score(target=target, altitude_deg=astronomy.altitude_deg)
    altitude = site_altitude_score(place.elevation_m)
    confidence = forecast_confidence_score(
        forecast_time_utc=conditions.timestamp_utc,
        search_started_utc=search_started_utc,
    )
    minimum_altitude = minimum_target_altitude_deg(target)

    return ScoreInputs(
        cloud_clearance=cloud_clearance,
        darkness=darkness,
        transparency=transparency,
        moon_conditions=moon_conditions,
        dew_margin=dew_margin,
        wind=wind,
        target_altitude=target_altitude,
        altitude=altitude,
        horizon_openness=place.horizon_openness_score,
        accessibility=place.accessibility_score,
        confidence=confidence,
        sun_dark_enough=sun_is_dark_enough(target, astronomy.sun_altitude_deg),
        target_above_horizon=(
            target == TargetKind.BEST_NIGHT_SKY or astronomy.altitude_deg >= minimum_altitude
        ),
        severe_cloud=(conditions.total_cloud_fraction >= 0.92 or cloud_clearance < 0.08),
        precipitation=conditions.precipitation_mm >= 0.2,
        place_accessible=place.accessibility_score >= 0.25,
        normalized_drive_cost=min(1.0, max(0.0, distance_km / maximum_distance_km)),
        normalized_risk=place.risk_score,
    )


def cloud_clearance_score(conditions: HourlySkyCondition) -> float:
    """Layer-aware cloud transmission proxy.

    Low clouds receive the highest penalty because they tend to be optically thicker and can
    amplify artificial skyglow near settlements. High clouds still matter, but less strongly.
    """

    optical_penalty = (
        2.8 * conditions.low_cloud_fraction
        + 2.0 * conditions.mid_cloud_fraction
        + 1.4 * conditions.high_cloud_fraction
    )
    layer_score = math.exp(-optical_penalty)
    total_score = 1.0 - conditions.total_cloud_fraction
    return _bounded(0.65 * layer_score + 0.35 * total_score)


def astronomical_darkness_score(*, target: TargetKind, sun_altitude_deg: float) -> float:
    threshold = -6.0 if target == TargetKind.MOON else -18.0
    if sun_altitude_deg <= threshold:
        return 1.0
    if sun_altitude_deg >= -4.0:
        return 0.0
    return _bounded((-4.0 - sun_altitude_deg) / (-4.0 - threshold))


def sun_is_dark_enough(target: TargetKind, sun_altitude_deg: float) -> bool:
    if target == TargetKind.MOON:
        return sun_altitude_deg <= -4.0
    if target in {TargetKind.MARS, TargetKind.JUPITER, TargetKind.BRIGHT_PLANET}:
        return sun_altitude_deg <= -8.0
    return sun_altitude_deg <= -12.0


def transparency_score(
    *,
    conditions: HourlySkyCondition,
    astronomy: AstronomySnapshot,
) -> float:
    if conditions.visibility_m is None:
        visibility = 0.55
    else:
        visibility = _bounded((conditions.visibility_m / 1000.0 - 5.0) / 35.0)
    humidity = 1.0 - 0.55 * _bounded((conditions.relative_humidity_fraction - 0.55) / 0.45)
    airmass = astronomy.airmass
    airmass_factor = 1.0 if airmass is None else _bounded(1.35 / max(1.0, airmass))
    return _bounded(0.50 * visibility + 0.30 * humidity + 0.20 * airmass_factor)


def moon_interference_score(*, target: TargetKind, astronomy: AstronomySnapshot) -> float:
    if target == TargetKind.MOON:
        return 1.0
    if astronomy.moon_altitude_deg <= 0.0:
        return 1.0
    altitude_factor = _bounded(math.sin(math.radians(astronomy.moon_altitude_deg)))
    proximity = _bounded((120.0 - astronomy.moon_separation_deg) / 120.0)
    interference = (
        astronomy.moon_illumination_fraction * altitude_factor * (0.35 + 0.65 * proximity)
    )
    sensitivity = 0.95 if target in {TargetKind.MILKY_WAY, TargetKind.BEST_NIGHT_SKY} else 0.55
    return _bounded(1.0 - sensitivity * interference)


def dew_margin_score(*, temperature_c: float, dew_point_c: float) -> float:
    spread_c = temperature_c - dew_point_c
    return _bounded((spread_c - 0.5) / 5.0)


def wind_score(wind_speed_mps: float, *, mode: ObservationMode) -> float:
    upper_limit = 9.0 if mode == ObservationMode.WIDE_ANGLE_CAMERA else 12.0
    comfortable = 2.0
    if wind_speed_mps <= comfortable:
        return 1.0
    return _bounded(1.0 - (wind_speed_mps - comfortable) / (upper_limit - comfortable))


def target_altitude_score(*, target: TargetKind, altitude_deg: float) -> float:
    if target == TargetKind.BEST_NIGHT_SKY:
        return 1.0
    minimum = minimum_target_altitude_deg(target)
    optimal = 60.0 if target != TargetKind.MOON else 50.0
    return _bounded((altitude_deg - minimum) / (optimal - minimum))


def minimum_target_altitude_deg(target: TargetKind) -> float:
    if target == TargetKind.MOON:
        return 5.0
    if target in {TargetKind.MARS, TargetKind.JUPITER, TargetKind.BRIGHT_PLANET}:
        return 12.0
    if target == TargetKind.ALPHA_CENTAURI:
        return 3.0
    if target == TargetKind.MILKY_WAY:
        return 8.0
    return 0.0


def site_altitude_score(elevation_m: float) -> float:
    # A saturating benefit: most gains occur below roughly 2,500 m; extreme altitude is not
    # rewarded indefinitely because safety and accessibility are represented separately.
    return _bounded(0.35 + 0.65 * (1.0 - math.exp(-max(0.0, elevation_m) / 1800.0)))


def forecast_confidence_score(
    *,
    forecast_time_utc: datetime,
    search_started_utc: datetime,
) -> float:
    lead_hours = max(
        0.0,
        (forecast_time_utc.astimezone(UTC) - search_started_utc.astimezone(UTC)).total_seconds()
        / 3600.0,
    )
    if lead_hours <= 72.0:
        return 0.92
    if lead_hours <= 168.0:
        return 0.75
    if lead_hours <= 240.0:
        return 0.55
    return 0.35


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))
