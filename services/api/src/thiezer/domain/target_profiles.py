from __future__ import annotations

from dataclasses import dataclass

from thiezer.domain.celestial_objects import CelestialObject, CelestialObjectClass
from thiezer.domain.contracts import TargetFamily, TargetKind


@dataclass(frozen=True, slots=True)
class RecommendationProfile:
    """Versioned policy for selecting a useful place, not astronomical geometry itself."""

    family: TargetFamily
    acceptable_score: float
    meaningful_quality_gain: float
    drive_weight: float
    include_observer_location: bool


_PROFILE_VERSION = "recommendation-profile-v1"

_MOON = RecommendationProfile(TargetFamily.MOON, 0.34, 0.14, 0.55, True)
_PLANET = RecommendationProfile(TargetFamily.PLANET, 0.40, 0.12, 0.45, True)
_STAR = RecommendationProfile(TargetFamily.STAR, 0.42, 0.12, 0.40, True)
_DEEP_SKY = RecommendationProfile(TargetFamily.DEEP_SKY, 0.50, 0.07, 0.18, False)
_MILKY_WAY = RecommendationProfile(TargetFamily.MILKY_WAY, 0.50, 0.07, 0.18, False)
_GENERAL = RecommendationProfile(TargetFamily.GENERAL, 0.44, 0.10, 0.24, False)
_SATELLITE = RecommendationProfile(TargetFamily.SATELLITE, 0.40, 0.12, 0.44, True)


def profile_for(
    target: TargetKind,
    catalog_target: CelestialObject | None = None,
) -> RecommendationProfile:
    if catalog_target is not None:
        object_class = catalog_target.object_class
        if object_class == CelestialObjectClass.STAR:
            return _STAR
        if object_class in {
            CelestialObjectClass.GALAXY,
            CelestialObjectClass.NEBULA,
            CelestialObjectClass.CLUSTER,
        }:
            return _DEEP_SKY
        if object_class in {
            CelestialObjectClass.NATURAL_SATELLITE,
            CelestialObjectClass.SPACECRAFT,
        }:
            return _SATELLITE
        if object_class == CelestialObjectClass.EXOPLANET:
            return _STAR
        if object_class in {
            CelestialObjectClass.SOLAR_SYSTEM_BODY,
            CelestialObjectClass.ASTEROID,
            CelestialObjectClass.COMET,
            CelestialObjectClass.DWARF_PLANET,
        }:
            return _PLANET
        return _GENERAL

    if target == TargetKind.MOON:
        return _MOON
    if target == TargetKind.MILKY_WAY:
        return _MILKY_WAY
    if target == TargetKind.BEST_NIGHT_SKY:
        return _GENERAL
    if target in {
        TargetKind.MERCURY,
        TargetKind.VENUS,
        TargetKind.MARS,
        TargetKind.JUPITER,
        TargetKind.SATURN,
        TargetKind.URANUS,
        TargetKind.NEPTUNE,
        TargetKind.BRIGHT_PLANET,
    }:
        return _PLANET
    if target == TargetKind.ALPHA_CENTAURI:
        return _STAR
    return _GENERAL


def scoring_target_for_catalog(target: CelestialObject) -> TargetKind:
    """Map catalog classes to an existing physical score profile without changing identity."""

    if target.object_class in {
        CelestialObjectClass.GALAXY,
        CelestialObjectClass.NEBULA,
        CelestialObjectClass.CLUSTER,
    }:
        return TargetKind.MILKY_WAY
    if target.object_class in {
        CelestialObjectClass.STAR,
        CelestialObjectClass.EXOPLANET,
    }:
        return TargetKind.ALPHA_CENTAURI
    return TargetKind.BRIGHT_PLANET


def profile_version() -> str:
    return _PROFILE_VERSION
