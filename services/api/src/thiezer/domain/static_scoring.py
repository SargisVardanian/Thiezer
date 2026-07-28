from __future__ import annotations

import math
from dataclasses import dataclass

from thiezer.domain.contracts import GeoPoint
from thiezer.domain.surface import SurfaceCell, SurfaceDataQuality


@dataclass(frozen=True, slots=True)
class RawSurfaceFeatures:
    h3_index: str
    resolution: int
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    slope_deg: float
    roughness_m: float
    mean_radiance_0_5_km: float
    mean_radiance_5_25_km: float
    mean_radiance_25_80_km: float
    water_fraction: float
    urban_fraction: float
    forest_fraction: float
    open_land_fraction: float
    distance_to_road_km: float
    distance_to_settlement_km: float
    restricted: bool
    uncertainty: float
    data_quality: SurfaceDataQuality
    attribution: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StaticFilterPolicy:
    minimum_land_fraction: float = 0.60
    maximum_urban_fraction: float = 0.35
    maximum_slope_deg: float = 15.0
    minimum_access_potential: float = 0.08
    maximum_uncertainty: float = 0.95


def multiscale_light_pressure(
    *,
    mean_radiance_0_5_km: float,
    mean_radiance_5_25_km: float,
    mean_radiance_25_80_km: float,
) -> float:
    return (
        0.55 * math.log1p(max(0.0, mean_radiance_0_5_km))
        + 0.30 * math.log1p(max(0.0, mean_radiance_5_25_km))
        + 0.15 * math.log1p(max(0.0, mean_radiance_25_80_km))
    )


def darkness_score_from_pressure(pressure: float, *, scale: float = 3.2) -> float:
    return _bounded(math.exp(-max(0.0, pressure) / scale))


def terrain_score(*, elevation_m: float, slope_deg: float, roughness_m: float) -> float:
    elevation = 0.30 + 0.70 * (1.0 - math.exp(-max(0.0, elevation_m) / 1800.0))
    slope = math.exp(-((max(0.0, slope_deg) / 10.0) ** 2))
    roughness = math.exp(-max(0.0, roughness_m) / 90.0)
    return weighted_geometric_mean(
        {"elevation": elevation, "slope": slope, "roughness": roughness},
        {"elevation": 0.45, "slope": 0.30, "roughness": 0.25},
    )


def land_score(
    *,
    water_fraction: float,
    urban_fraction: float,
    forest_fraction: float,
    open_land_fraction: float,
) -> float:
    dry_land = 1.0 - _bounded(water_fraction)
    non_urban = 1.0 - _bounded(urban_fraction)
    forest_clearance = 1.0 - 0.75 * _bounded(forest_fraction)
    openness = 0.20 + 0.80 * _bounded(open_land_fraction)
    return weighted_geometric_mean(
        {
            "dry_land": dry_land,
            "non_urban": non_urban,
            "forest_clearance": forest_clearance,
            "openness": openness,
        },
        {
            "dry_land": 0.35,
            "non_urban": 0.30,
            "forest_clearance": 0.15,
            "openness": 0.20,
        },
    )


def access_potential(*, distance_to_road_km: float, distance_to_settlement_km: float) -> float:
    road = math.exp(-max(0.0, distance_to_road_km) / 3.0)
    isolation_penalty = 1.0 - 0.18 * _bounded((distance_to_settlement_km - 80.0) / 120.0)
    return _bounded(road * isolation_penalty)


def score_raw_features(raw: RawSurfaceFeatures) -> SurfaceCell:
    pressure = multiscale_light_pressure(
        mean_radiance_0_5_km=raw.mean_radiance_0_5_km,
        mean_radiance_5_25_km=raw.mean_radiance_5_25_km,
        mean_radiance_25_80_km=raw.mean_radiance_25_80_km,
    )
    darkness = darkness_score_from_pressure(pressure)
    terrain = terrain_score(
        elevation_m=raw.elevation_m,
        slope_deg=raw.slope_deg,
        roughness_m=raw.roughness_m,
    )
    land = land_score(
        water_fraction=raw.water_fraction,
        urban_fraction=raw.urban_fraction,
        forest_fraction=raw.forest_fraction,
        open_land_fraction=raw.open_land_fraction,
    )
    access = access_potential(
        distance_to_road_km=raw.distance_to_road_km,
        distance_to_settlement_km=raw.distance_to_settlement_km,
    )
    static = weighted_geometric_mean(
        {"darkness": darkness, "terrain": terrain, "land": land, "access": access},
        {"darkness": 0.42, "terrain": 0.24, "land": 0.20, "access": 0.14},
    )
    static = _bounded(static - 0.12 * _bounded(raw.uncertainty))
    upper_bound = _bounded(static + 0.16 * (1.0 - _bounded(raw.uncertainty)))

    return SurfaceCell(
        h3_index=raw.h3_index,
        resolution=raw.resolution,
        center=GeoPoint(
            latitude_deg=raw.latitude_deg,
            longitude_deg=raw.longitude_deg,
        ),
        elevation_m=raw.elevation_m,
        slope_deg=raw.slope_deg,
        roughness_m=raw.roughness_m,
        mean_radiance_0_5_km=raw.mean_radiance_0_5_km,
        mean_radiance_5_25_km=raw.mean_radiance_5_25_km,
        mean_radiance_25_80_km=raw.mean_radiance_25_80_km,
        water_fraction=_bounded(raw.water_fraction),
        urban_fraction=_bounded(raw.urban_fraction),
        forest_fraction=_bounded(raw.forest_fraction),
        open_land_fraction=_bounded(raw.open_land_fraction),
        distance_to_road_km=max(0.0, raw.distance_to_road_km),
        distance_to_settlement_km=max(0.0, raw.distance_to_settlement_km),
        restricted=raw.restricted,
        darkness_score=darkness,
        terrain_score=terrain,
        land_score=land,
        access_potential=access,
        static_score=static,
        static_upper_bound=upper_bound,
        uncertainty=_bounded(raw.uncertainty),
        data_quality=raw.data_quality,
        attribution=raw.attribution,
    )


def passes_static_filters(cell: SurfaceCell, policy: StaticFilterPolicy) -> bool:
    if cell.restricted:
        return False
    if 1.0 - cell.water_fraction < policy.minimum_land_fraction:
        return False
    if cell.urban_fraction > policy.maximum_urban_fraction:
        return False
    if cell.slope_deg > policy.maximum_slope_deg:
        return False
    if cell.access_potential < policy.minimum_access_potential:
        return False
    return cell.uncertainty <= policy.maximum_uncertainty


def weighted_geometric_mean(values: dict[str, float], weights: dict[str, float]) -> float:
    if set(values) != set(weights):
        raise ValueError("values and weights must contain the same keys")
    total = sum(weights.values())
    if total <= 0.0:
        raise ValueError("weights must sum to a positive number")
    epsilon = 1e-8
    log_value = sum(
        (weights[name] / total) * math.log(max(epsilon, _bounded(value)))
        for name, value in values.items()
    )
    return _bounded(math.exp(log_value))


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("surface score inputs must be finite")
    return min(1.0, max(0.0, value))
