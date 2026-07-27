import math

import pytest

from thiezer.domain.contracts import ObservationMode, TargetKind, WarningCode
from thiezer.domain.scoring import ScoreInputs, calculate_sky_score


def good_inputs(**overrides: object) -> ScoreInputs:
    values: dict[str, object] = {
        "cloud_clearance": 0.9,
        "darkness": 0.9,
        "transparency": 0.8,
        "moon_conditions": 0.9,
        "dew_margin": 0.8,
        "wind": 0.8,
        "target_altitude": 0.8,
        "accessibility": 0.9,
        "confidence": 0.8,
    }
    values.update(overrides)
    return ScoreInputs(**values)  # type: ignore[arg-type]


def test_hard_gate_invalidates_score() -> None:
    result = calculate_sky_score(
        target=TargetKind.MILKY_WAY,
        mode=ObservationMode.NAKED_EYE,
        inputs=good_inputs(target_above_horizon=False),
    )
    assert not result.valid
    assert result.score == 0.0
    assert WarningCode.TARGET_BELOW_HORIZON in result.warnings


def test_weights_sum_to_one() -> None:
    result = calculate_sky_score(
        target=TargetKind.MILKY_WAY,
        mode=ObservationMode.WIDE_ANGLE_CAMERA,
        inputs=good_inputs(),
    )
    assert abs(sum(component.weight for component in result.components) - 1.0) < 1e-12


@pytest.mark.parametrize(
    ("lower", "higher"),
    [(0.0, 0.1), (0.1, 0.5), (0.5, 1.0), (0.25, 0.25)],
)
def test_more_cloud_clearance_cannot_reduce_score(lower: float, higher: float) -> None:
    low_result = calculate_sky_score(
        target=TargetKind.MILKY_WAY,
        mode=ObservationMode.NAKED_EYE,
        inputs=good_inputs(cloud_clearance=lower),
    )
    high_result = calculate_sky_score(
        target=TargetKind.MILKY_WAY,
        mode=ObservationMode.NAKED_EYE,
        inputs=good_inputs(cloud_clearance=higher),
    )
    assert high_result.score >= low_result.score


@pytest.mark.parametrize("confidence", [0.0, 0.1, 0.5, 0.9, 1.0])
def test_score_is_finite_and_bounded(confidence: float) -> None:
    result = calculate_sky_score(
        target=TargetKind.BRIGHT_PLANET,
        mode=ObservationMode.BINOCULARS,
        inputs=good_inputs(confidence=confidence),
    )
    assert math.isfinite(result.score)
    assert 0.0 <= result.score <= 1.0
