from thiezer.domain.static_scoring import (
    RawSurfaceFeatures,
    StaticFilterPolicy,
    passes_static_filters,
    score_raw_features,
)
from thiezer.domain.surface import SurfaceDataQuality


def _raw(**overrides: object) -> RawSurfaceFeatures:
    values: dict[str, object] = {
        "h3_index": "872c94d65ffffff",
        "resolution": 7,
        "latitude_deg": 40.3,
        "longitude_deg": 44.3,
        "elevation_m": 1800.0,
        "slope_deg": 4.0,
        "roughness_m": 20.0,
        "mean_radiance_0_5_km": 0.1,
        "mean_radiance_5_25_km": 0.3,
        "mean_radiance_25_80_km": 0.6,
        "water_fraction": 0.0,
        "urban_fraction": 0.02,
        "forest_fraction": 0.1,
        "open_land_fraction": 0.8,
        "distance_to_road_km": 1.0,
        "distance_to_settlement_km": 30.0,
        "restricted": False,
        "uncertainty": 0.1,
        "data_quality": SurfaceDataQuality.CALIBRATED_RASTER,
    }
    values.update(overrides)
    return RawSurfaceFeatures(**values)  # type: ignore[arg-type]


def test_travel_distance_is_not_a_surface_darkness_input() -> None:
    near = score_raw_features(_raw(distance_to_road_km=0.5))
    far = score_raw_features(_raw(distance_to_road_km=8.0))
    assert near.darkness_score == far.darkness_score
    assert near.access_potential > far.access_potential


def test_multiscale_light_pressure_reduces_darkness() -> None:
    dark = score_raw_features(_raw())
    bright = score_raw_features(
        _raw(
            mean_radiance_0_5_km=20.0,
            mean_radiance_5_25_km=10.0,
            mean_radiance_25_80_km=4.0,
        )
    )
    assert dark.darkness_score > bright.darkness_score


def test_static_hard_filters_reject_water_urban_slope_and_restrictions() -> None:
    policy = StaticFilterPolicy()
    assert not passes_static_filters(
        score_raw_features(_raw(water_fraction=0.8)),
        policy,
    )
    assert not passes_static_filters(
        score_raw_features(_raw(urban_fraction=0.7)),
        policy,
    )
    assert not passes_static_filters(
        score_raw_features(_raw(slope_deg=25.0)),
        policy,
    )
    assert not passes_static_filters(
        score_raw_features(_raw(restricted=True)),
        policy,
    )
