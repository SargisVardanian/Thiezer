from __future__ import annotations

import math
from dataclasses import dataclass

from thiezer.domain.contracts import (
    ObservationMode,
    SkyScoreBreakdown,
    SkyScoreComponent,
    TargetKind,
    WarningCode,
)

SCORING_VERSION = "v2"


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    cloud_clearance: float
    darkness: float
    transparency: float
    moon_conditions: float
    dew_margin: float
    wind: float
    target_altitude: float
    accessibility: float
    confidence: float
    altitude: float = 0.5
    horizon_openness: float = 0.7
    sun_dark_enough: bool = True
    target_above_horizon: bool = True
    severe_cloud: bool = False
    precipitation: bool = False
    place_accessible: bool = True
    # Retained for API/backward compatibility. Travel penalties are no longer applied here.
    normalized_drive_cost: float = 0.0
    normalized_risk: float = 0.0


_PLANET_WEIGHTS = {
    "cloud_clearance": 0.27,
    "darkness": 0.03,
    "transparency": 0.12,
    "moon_conditions": 0.02,
    "dew_margin": 0.05,
    "wind": 0.11,
    "target_altitude": 0.22,
    "altitude": 0.04,
    "horizon_openness": 0.04,
    "accessibility": 0.04,
    "confidence": 0.06,
}

_BASE_WEIGHTS: dict[TargetKind, dict[str, float]] = {
    TargetKind.MILKY_WAY: {
        "cloud_clearance": 0.23,
        "darkness": 0.20,
        "transparency": 0.13,
        "moon_conditions": 0.13,
        "dew_margin": 0.05,
        "wind": 0.04,
        "target_altitude": 0.07,
        "altitude": 0.04,
        "horizon_openness": 0.04,
        "accessibility": 0.03,
        "confidence": 0.04,
    },
    TargetKind.MOON: {
        "cloud_clearance": 0.29,
        "darkness": 0.01,
        "transparency": 0.12,
        "moon_conditions": 0.02,
        "dew_margin": 0.05,
        "wind": 0.08,
        "target_altitude": 0.22,
        "altitude": 0.04,
        "horizon_openness": 0.05,
        "accessibility": 0.05,
        "confidence": 0.07,
    },
    TargetKind.MARS: dict(_PLANET_WEIGHTS),
    TargetKind.JUPITER: dict(_PLANET_WEIGHTS),
    TargetKind.BRIGHT_PLANET: dict(_PLANET_WEIGHTS),
    TargetKind.ALPHA_CENTAURI: {
        "cloud_clearance": 0.25,
        "darkness": 0.14,
        "transparency": 0.15,
        "moon_conditions": 0.07,
        "dew_margin": 0.05,
        "wind": 0.04,
        "target_altitude": 0.16,
        "altitude": 0.03,
        "horizon_openness": 0.05,
        "accessibility": 0.02,
        "confidence": 0.04,
    },
    TargetKind.BEST_NIGHT_SKY: {
        "cloud_clearance": 0.24,
        "darkness": 0.23,
        "transparency": 0.15,
        "moon_conditions": 0.11,
        "dew_margin": 0.05,
        "wind": 0.04,
        "target_altitude": 0.01,
        "altitude": 0.05,
        "horizon_openness": 0.05,
        "accessibility": 0.03,
        "confidence": 0.04,
    },
}


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("score inputs must be finite")
    return min(1.0, max(0.0, value))


def _component_strength(value: float) -> str:
    if value >= 0.75:
        return "strong"
    if value < 0.4:
        return "weak"
    return "moderate"


def weights_for(target: TargetKind, mode: ObservationMode) -> dict[str, float]:
    weights = dict(_BASE_WEIGHTS[target])
    if mode == ObservationMode.WIDE_ANGLE_CAMERA:
        weights["wind"] += 0.02
        weights["accessibility"] -= 0.01
        weights["confidence"] -= 0.01
    elif mode == ObservationMode.BINOCULARS:
        weights["target_altitude"] += 0.01
        weights["darkness"] -= 0.01
    total = sum(weights.values())
    return {name: value / total for name, value in weights.items()}


def calculate_sky_score(
    *,
    target: TargetKind,
    mode: ObservationMode,
    inputs: ScoreInputs,
) -> SkyScoreBreakdown:
    warnings: list[WarningCode] = []
    if not inputs.sun_dark_enough:
        warnings.append(WarningCode.INVALID_SUN_ALTITUDE)
    if not inputs.target_above_horizon:
        warnings.append(WarningCode.TARGET_BELOW_HORIZON)
    if inputs.severe_cloud:
        warnings.append(WarningCode.SEVERE_CLOUD)
    if inputs.precipitation:
        warnings.append(WarningCode.PRECIPITATION)
    if not inputs.place_accessible:
        warnings.append(WarningCode.INACCESSIBLE)

    hard_invalid = bool(warnings)
    if inputs.confidence < 0.4:
        warnings.append(WarningCode.LOW_CONFIDENCE)
    if inputs.dew_margin < 0.3:
        warnings.append(WarningCode.HIGH_DEW_RISK)
    if inputs.wind < 0.3:
        warnings.append(WarningCode.STRONG_WIND)

    weights = weights_for(target, mode)
    values = {
        "cloud_clearance": _bounded(inputs.cloud_clearance),
        "darkness": _bounded(inputs.darkness),
        "transparency": _bounded(inputs.transparency),
        "moon_conditions": _bounded(inputs.moon_conditions),
        "dew_margin": _bounded(inputs.dew_margin),
        "wind": _bounded(inputs.wind),
        "target_altitude": _bounded(inputs.target_altitude),
        "altitude": _bounded(inputs.altitude),
        "horizon_openness": _bounded(inputs.horizon_openness),
        "accessibility": _bounded(inputs.accessibility),
        "confidence": _bounded(inputs.confidence),
    }
    components = [
        SkyScoreComponent(name=name, value=values[name], weight=weight)
        for name, weight in weights.items()
    ]

    if hard_invalid:
        score = 0.0
    else:
        epsilon = 1e-6
        score = math.exp(
            sum(weight * math.log(max(epsilon, values[name])) for name, weight in weights.items())
        )
        score = _bounded(score)

    explanations = [
        f"{component.name}:{_component_strength(component.value)}" for component in components
    ]
    return SkyScoreBreakdown(
        valid=not hard_invalid,
        score=score,
        utility=score,
        components=components,
        warnings=warnings,
        explanation_codes=explanations,
        scoring_version=SCORING_VERSION,
    )
