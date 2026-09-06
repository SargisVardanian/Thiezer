"""Deterministic gates for a *site-specific, whole-interval* observing opportunity.

This module does not fetch data, compute ephemerides, generate sites or route roads.
Adapters must provide interval extrema and independently verified spatial checks.
Policy thresholds are product defaults, not calibrated probabilities or safety limits.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType


class Profile(StrEnum):
    DARK_SKY = "dark_sky"
    DEEP_SKY = "deep_sky"
    PLANET = "planet"
    MOON = "moon"
    SUN = "sun"


class Status(StrEnum):
    FORECAST_BACKED = "forecast_backed"
    NEEDS_VERIFICATION = "needs_verification"
    PARTIAL_FORECAST = "partial_forecast"
    ASTRONOMY_ONLY = "astronomy_only"
    INSUFFICIENT_DATA = "insufficient_data"
    REJECTED = "rejected"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return value.astimezone(UTC)


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class Evidence:
    """Extremum valid over [valid_from, valid_to], not a midpoint observation.

    `kind` is computed / forecast / modeled / measured / estimated.
    `source` should identify a versioned dataset/model, not only a provider name.
    """
    value: float
    unit: str
    source: str
    kind: str
    valid_from: datetime
    valid_to: datetime
    issued_at: datetime
    resolution_m: float | None = None

    def __post_init__(self) -> None:
        _finite(self.value, "evidence value")
        if not self.unit.strip() or not self.source.strip():
            raise ValueError("Evidence needs units and a source")
        if self.kind not in {"computed", "forecast", "modeled", "measured", "estimated"}:
            raise ValueError("Unsupported evidence kind")
        for key in ("valid_from", "valid_to", "issued_at"):
            object.__setattr__(self, key, _utc(getattr(self, key)))
        if self.valid_to <= self.valid_from:
            raise ValueError("Evidence validity must be a non-empty interval")
        if self.resolution_m is not None:
            _finite(self.resolution_m, "resolution_m")
            if self.resolution_m <= 0:
                raise ValueError("resolution_m must be positive")


@dataclass(frozen=True)
class Policy:
    version: str = "opportunity-policy-v1"
    strict_moonless: bool = True
    max_sun_altitude_deg: float = -18.0
    min_target_clearance_deg: float = 5.0
    min_duration_minutes: float = 60.0
    max_drive_minutes: float = 180.0
    min_darkness_index: float = 0.7
    max_cloud_fraction: float = 0.35
    max_precipitation_mm_per_hour: float = 0.1
    max_wind_mps: float = 8.0
    max_aod550: float = 0.2
    max_pm25_ug_m3: float = 15.0
    max_forecast_age_hours: float = 36.0
    small_country_area_km2: float = 250000.0
    small_country_extent_km: float = 700.0

    def __post_init__(self) -> None:
        if not self.version.strip() or not isinstance(self.strict_moonless, bool):
            raise ValueError("Invalid policy version or strict_moonless")
        for key, value in vars(self).items():
            if key in {"version", "strict_moonless"}:
                continue
            _finite(value, key)
            if key != "max_sun_altitude_deg" and value < 0:
                raise ValueError(f"{key} cannot be negative")
        if not -90 <= self.max_sun_altitude_deg <= 0:
            raise ValueError("Sun altitude threshold out of range")
        if not 0 <= self.min_target_clearance_deg < 90:
            raise ValueError("Target clearance threshold out of range")
        if not 0 <= self.min_darkness_index <= 1 or not 0 <= self.max_cloud_fraction <= 1:
            raise ValueError("Fractions must be between zero and one")
        if min(self.min_duration_minutes, self.max_drive_minutes,
               self.max_forecast_age_hours, self.small_country_area_km2,
               self.small_country_extent_km) <= 0:
            raise ValueError("Time and extent limits must be positive")


@dataclass(frozen=True)
class Opportunity:
    site_id: str
    profile: Profile
    start_utc: datetime
    end_utc: datetime
    as_of_utc: datetime
    metrics: Mapping[str, Evidence] = field(default_factory=dict)
    checks: Mapping[str, bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.site_id.strip() or not isinstance(self.profile, Profile):
            raise ValueError("Opportunity needs a site ID and typed profile")
        for key in ("start_utc", "end_utc", "as_of_utc"):
            object.__setattr__(self, key, _utc(getattr(self, key)))
        if self.end_utc <= self.start_utc:
            raise ValueError("Opportunity end must be after start")
        if any(v is not None and not isinstance(v, bool) for v in self.checks.values()):
            raise ValueError("Checks must be True, False or None")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))


@dataclass(frozen=True)
class Decision:
    site_id: str
    status: Status
    start_utc: datetime
    policy_version: str
    reasons: tuple[str, ...]
    unknowns: tuple[str, ...]
    checks: Mapping[str, bool | None]


# (unit, domain minimum, domain maximum). Units are explicit API contracts.
_DOMAINS = {
    "sun_max": ("deg", -90.0, 90.0),
    "moon_upper_limb_max": ("deg", -91.0, 91.0),
    "target_clearance_min": ("deg", -180.0, 180.0),
    "darkness_min": ("index_0_1", 0.0, 1.0),
    "cloud_max": ("fraction", 0.0, 1.0),
    "precipitation_max": ("mm/h", 0.0, math.inf),
    "wind_max": ("m/s", 0.0, math.inf),
    "aod_max": ("dimensionless", 0.0, math.inf),
    "pm25_max": ("ug/m3", 0.0, math.inf),
    "drive_minutes": ("min", 0.0, math.inf),
}
_GEOMETRY = {"sun_max", "moon_upper_limb_max", "target_clearance_min"}
_WEATHER = {"cloud_max", "precipitation_max", "wind_max", "aod_max", "pm25_max"}


def evaluate(opportunity: Opportunity, policy: Policy) -> Decision:
    """Evaluate whole-interval gates. Missing/stale data can never pass a gate.

    Forecast-backed means 'meets this policy using supplied forecasts', NOT that
    weather or physical safety is guaranteed. No probability is produced.
    """
    o = opportunity
    checks: dict[str, bool | None] = {}

    def threshold(key: str, limit: float, *, minimum: bool = False) -> None:
        item = o.metrics.get(key)
        value: float | None = None
        if item is not None:
            unit, low, high = _DOMAINS[key]
            valid = (
                item.unit == unit and low <= item.value <= high
                and item.valid_from <= o.start_utc and item.valid_to >= o.end_utc
                and item.issued_at <= o.as_of_utc
            )
            if key in _GEOMETRY:
                valid = valid and item.kind == "computed"
            elif key in _WEATHER:
                age = (o.as_of_utc - item.issued_at).total_seconds() / 3600
                valid = valid and item.kind == "forecast" and age <= policy.max_forecast_age_hours
            else:
                valid = valid and item.kind in {"computed", "modeled", "measured"}
            if valid:
                value = item.value
        checks[key] = None if value is None else (value >= limit if minimum else value <= limit)

    checks["future_interval"] = o.start_utc >= o.as_of_utc
    checks["duration"] = (o.end_utc - o.start_utc).total_seconds() / 60 >= policy.min_duration_minutes
    # These checks MUST come from geometry/routing/access/hazard adapters, not an LLM.
    for key in ("destination_in_scope", "route_in_scope", "route_found", "access_allowed", "hazards_clear"):
        checks[key] = o.checks.get(key)
    threshold("drive_minutes", policy.max_drive_minutes)
    if o.profile is not Profile.DARK_SKY:
        threshold("target_clearance_min", policy.min_target_clearance_deg, minimum=True)
    if o.profile not in {Profile.SUN, Profile.MOON}:
        threshold("sun_max", policy.max_sun_altitude_deg)
        if policy.strict_moonless:
            # Upper limb above astronomical horizontal plane, not behind a mountain.
            threshold("moon_upper_limb_max", 0.0)
        threshold("darkness_min", policy.min_darkness_index, minimum=True)
    if o.profile is Profile.SUN:
        checks["solar_safety_acknowledged"] = o.checks.get("solar_safety_acknowledged")
    for key, limit in (
        ("cloud_max", policy.max_cloud_fraction),
        ("precipitation_max", policy.max_precipitation_mm_per_hour),
        ("wind_max", policy.max_wind_mps),
        ("aod_max", policy.max_aod550),
        ("pm25_max", policy.max_pm25_ug_m3),
    ):
        threshold(key, limit)

    reasons = tuple(key for key, value in checks.items() if value is False)
    unknowns = tuple(key for key, value in checks.items() if value is None)
    if reasons:
        status = Status.REJECTED
    elif any(key in _GEOMETRY for key in unknowns):
        status = Status.INSUFFICIENT_DATA
    elif any(key in _WEATHER for key in unknowns):
        weather_unknown = sum(key in _WEATHER for key in unknowns)
        status = Status.ASTRONOMY_ONLY if weather_unknown == len(_WEATHER) else Status.PARTIAL_FORECAST
    elif unknowns:
        status = Status.NEEDS_VERIFICATION
    else:
        status = Status.FORECAST_BACKED
    return Decision(o.site_id, status, o.start_utc, policy.version, reasons, unknowns,
                    MappingProxyType(checks))


@dataclass(frozen=True)
class Scope:
    mode: str
    country_code: str | None
    region_id: str | None
    cross_border: bool = False


def automatic_scope(*, country_code: str | None, region_id: str | None,
                    country_area_km2: float | None, country_extent_km: float | None,
                    policy: Policy) -> Scope:
    """Choose a search label; polygon clipping and travel-time filtering are external.

    Small/large is a versioned UX heuristic, not a geographic or legal definition.
    Missing extent defaults to local-country search, never worldwide.
    """
    if country_code is None:
        return Scope("location_required", None, None)
    if re.fullmatch(r"[A-Z]{2}", country_code) is None:
        raise ValueError("Expected an uppercase ISO-style country code")
    for name, value in (("country_area_km2", country_area_km2),
                        ("country_extent_km", country_extent_km)):
        if value is not None:
            _finite(value, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
    small = (
        country_area_km2 is not None and country_extent_km is not None
        and country_area_km2 <= policy.small_country_area_km2
        and country_extent_km <= policy.small_country_extent_km
    )
    if small:
        return Scope("country", country_code, None)
    return Scope("region" if region_id else "nearby_in_country", country_code, region_id)


def earliest_first(decisions: Sequence[Decision]) -> list[Decision]:
    """Keep evidence classes separate; nearest acceptable date within each class.

    This is not a scientific quality ranking. Rejected and insufficient-data
    decisions remain available to callers for diagnostics but not suggestions.
    """
    order = {Status.FORECAST_BACKED: 0, Status.NEEDS_VERIFICATION: 1,
             Status.PARTIAL_FORECAST: 2, Status.ASTRONOMY_ONLY: 3}
    return sorted((d for d in decisions if d.status in order),
                  key=lambda d: (order[d.status], d.start_utc, d.site_id))
