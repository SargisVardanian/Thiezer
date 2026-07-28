from __future__ import annotations

from thiezer.domain.contracts import (
    CandidatePlace,
    TravelUtilityBreakdown,
    VerificationStatus,
)


def calculate_travel_utility(
    *,
    sky_quality: float,
    distance_km: float,
    maximum_distance_km: float,
    place: CandidatePlace,
    forecast_confidence: float,
) -> TravelUtilityBreakdown:
    distance_penalty = 0.20 * _bounded(distance_km / max(1.0, maximum_distance_km))
    risk_penalty = 0.15 * _bounded(place.risk_score)
    uncertainty_penalty = 0.10 * _bounded(place.static_uncertainty) + 0.08 * (
        1.0 - _bounded(forecast_confidence)
    )
    verification_penalty = {
        VerificationStatus.VERIFIED: 0.0,
        VerificationStatus.PARTNER_VERIFIED: 0.015,
        VerificationStatus.UNVERIFIED_SEED: 0.04,
        VerificationStatus.UNVERIFIED_DISCOVERED: 0.07,
    }[place.verification_status]
    total = (
        _bounded(sky_quality)
        - distance_penalty
        - risk_penalty
        - uncertainty_penalty
        - verification_penalty
    )
    return TravelUtilityBreakdown(
        sky_quality=_bounded(sky_quality),
        distance_penalty=distance_penalty,
        risk_penalty=risk_penalty,
        uncertainty_penalty=uncertainty_penalty,
        verification_penalty=verification_penalty,
        total=total,
    )


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))
